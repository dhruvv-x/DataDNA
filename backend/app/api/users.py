"""Create, list, view, deactivate and reset users, all scoped by role (S3)."""
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import errors
from pydantic import BaseModel, field_validator

from app.api.auth import revoke_all_refresh_tokens
from app.api.deps import current_user, get_db
from app.core import auditlog, clock, security
from app.core.scope import (
    DEAN,
    CurrentUser,
    can_create_user,
    can_manage_user,
    forbidden,
    not_found,
    require_role,
    user_filter,
)

router = APIRouter(prefix="/users", tags=["users"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SELECT = """
    SELECT u.id, u.email, u.full_name, u.role, u.department_id, d.code AS department_code,
           u.employee_code, u.is_active, u.created_at, u.last_login_at, u.must_change_password
    FROM users u LEFT JOIN departments d ON d.id = u.department_id
"""

_CONFLICTS = {
    "users_email_key": "A user with this email already exists.",
    "users_employee_code_key": "A user with this employee code already exists.",
    "users_one_active_hod_per_department": "This department already has an active HOD.",
}


class UserCreate(BaseModel):
    email: str
    full_name: str
    role: Literal["HOD", "FACULTY"]
    department_id: uuid.UUID
    employee_code: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "\x00" in v or not _EMAIL_RE.match(v) or len(v) > 254:
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 200 or "\x00" in v:
            raise ValueError("Name must be 1 to 200 characters.")
        return v

    @field_validator("employee_code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 50 or "\x00" in v:
            raise ValueError("Employee code is too long or contains an invalid character.")
        return v or None


class ActiveBody(BaseModel):
    is_active: bool


def _conflict(exc: errors.UniqueViolation) -> HTTPException:
    name = exc.diag.constraint_name or ""
    return HTTPException(status_code=409, detail=_CONFLICTS.get(name, "This record conflicts with an existing one."))


def _visible_user(db, actor: CurrentUser, user_id: uuid.UUID) -> dict:
    """The user if the actor may see them, else 404 (same answer as 'does not exist')."""
    scope_sql, scope_params = user_filter(actor)
    row = db.execute(f"{_SELECT} WHERE u.id = %s AND ({scope_sql})", (user_id, *scope_params)).fetchone()
    if row is None:
        raise not_found()
    return row


# ------------------------------------------------------------------ create
@router.post("", status_code=201)
def create_user(body: UserCreate, actor: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(actor, DEAN, "HOD")
    if not can_create_user(actor, body.role, body.department_id):
        raise forbidden()
    if db.execute("SELECT 1 FROM departments WHERE id = %s", (body.department_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Department not found.")

    temporary = security.generate_temporary_password()
    try:
        new_id = db.execute(
            """
            INSERT INTO users (email, password_hash, full_name, role, department_id, employee_code,
                               must_change_password)
            VALUES (%s, %s, %s, %s, %s, %s, true)
            RETURNING id
            """,
            (
                body.email, security.hash_password(temporary), body.full_name, body.role,
                body.department_id, body.employee_code,
            ),
        ).fetchone()["id"]
    except errors.UniqueViolation as exc:
        db.rollback()
        raise _conflict(exc)

    auditlog.write(
        db, actor_id=actor.id, actor_role=actor.role, action="USER_CREATED", entity_type="user",
        entity_id=new_id, payload={"role": body.role, "department_id": str(body.department_id)},
    )
    created = db.execute(f"{_SELECT} WHERE u.id = %s", (new_id,)).fetchone()
    db.commit()
    return {**created, "temporary_password": temporary}


# ------------------------------------------------------------------ list / get
@router.get("")
def list_users(
    department_id: uuid.UUID | None = None,
    role: Literal["FACULTY", "HOD", "DEAN"] | None = None,
    is_active: bool | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    actor: CurrentUser = Depends(current_user),
    db=Depends(get_db),
):
    require_role(actor, DEAN, "HOD")
    scope_sql, params = user_filter(actor)
    where, args = [f"({scope_sql})"], list(params)
    if department_id is not None:
        where.append("u.department_id = %s")
        args.append(department_id)
    if role is not None:
        where.append("u.role = %s")
        args.append(role)
    if is_active is not None:
        where.append("u.is_active = %s")
        args.append(is_active)
    rows = db.execute(
        f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY u.full_name, u.id LIMIT %s OFFSET %s",
        (*args, limit, offset),
    ).fetchall()
    return rows


@router.get("/{user_id}")
def get_user(user_id: uuid.UUID, actor: CurrentUser = Depends(current_user), db=Depends(get_db)):
    return _visible_user(db, actor, user_id)


# ------------------------------------------------------------------ deactivate / reactivate
@router.patch("/{user_id}/active")
def set_active(
    user_id: uuid.UUID, body: ActiveBody, actor: CurrentUser = Depends(current_user), db=Depends(get_db)
):
    require_role(actor, DEAN, "HOD")
    target = _visible_user(db, actor, user_id)
    if not can_manage_user(actor, target):
        raise forbidden()
    if target["id"] == actor.id:
        raise HTTPException(status_code=400, detail="You cannot change your own active status.")
    if target["is_active"] == body.is_active:
        return target  # nothing to do

    if target["role"] == DEAN and not body.is_active:
        # Lock every active Dean row first (always in id order), then count. Without the lock, two
        # Deans deactivating each other at the same moment would both pass the check and leave nobody.
        active_deans = db.execute(
            "SELECT id FROM users WHERE role = 'DEAN' AND is_active ORDER BY id FOR UPDATE"
        ).fetchall()
        if not [d for d in active_deans if d["id"] != user_id]:
            db.rollback()
            raise HTTPException(status_code=409, detail="The last active Dean cannot be deactivated.")

    now = clock.utcnow()
    try:
        if body.is_active:
            # Reactivating a deactivated user also clears any lockout. (A locked but active user: use reset-password.)
            db.execute(
                "UPDATE users SET is_active = true, failed_login_count = 0, locked_until = NULL WHERE id = %s",
                (user_id,),
            )
        else:
            db.execute("UPDATE users SET is_active = false WHERE id = %s", (user_id,))
    except errors.UniqueViolation as exc:  # second active HOD in the department
        db.rollback()
        raise _conflict(exc)
    if not body.is_active:
        revoke_all_refresh_tokens(db, user_id, now)
    auditlog.write(
        db, actor_id=actor.id, actor_role=actor.role,
        action="USER_ACTIVATED" if body.is_active else "USER_DEACTIVATED",
        entity_type="user", entity_id=user_id,
    )
    updated = db.execute(f"{_SELECT} WHERE u.id = %s", (user_id,)).fetchone()
    db.commit()
    return updated


# ------------------------------------------------------------------ reset password
@router.post("/{user_id}/reset-password")
def reset_password(user_id: uuid.UUID, actor: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """New temporary password, shown once. The user must change it at the next login."""
    require_role(actor, DEAN, "HOD")
    target = _visible_user(db, actor, user_id)
    if not can_manage_user(actor, target):
        raise forbidden()
    if target["id"] == actor.id:
        raise HTTPException(status_code=400, detail="Use change-password for your own account.")

    now = clock.utcnow()
    temporary = security.generate_temporary_password()
    db.execute(
        """
        UPDATE users
        SET password_hash = %s, password_changed_at = %s, must_change_password = true,
            failed_login_count = 0, locked_until = NULL
        WHERE id = %s
        """,
        (security.hash_password(temporary), now, user_id),
    )
    revoke_all_refresh_tokens(db, user_id, now)
    auditlog.write(
        db, actor_id=actor.id, actor_role=actor.role, action="PASSWORD_RESET",
        entity_type="user", entity_id=user_id,
    )
    db.commit()
    return {"user_id": user_id, "temporary_password": temporary}
