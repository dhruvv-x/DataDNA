"""Login, refresh, logout, change password, who am I (S3)."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.api.deps import current_user_any, get_db
from app.core import auditlog, clock, security, settings
from app.core.scope import CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "dd_refresh"
GENERIC_LOGIN_ERROR = "Invalid email or password."
MAX_EMAIL_LENGTH = 254

_USER_COLUMNS = (
    "id, email, full_name, role, department_id, is_active, failed_login_count, locked_until, "
    "must_change_password, password_changed_at, password_hash"
)


def _login_failed() -> HTTPException:
    return HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR, headers={"WWW-Authenticate": "Bearer"})


def _public_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "department_id": row["department_id"],
    }


def _set_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw,
        max_age=settings.refresh_token_days() * 86400,
        httponly=True,
        secure=settings.cookie_secure(),
        samesite=settings.cookie_samesite(),
        path=settings.cookie_path(),
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path=settings.cookie_path(),
        httponly=True,
        secure=settings.cookie_secure(),
        samesite=settings.cookie_samesite(),
    )


def _issue_session(db, user: dict, response: Response, now) -> dict:
    """Store a new refresh token, set it as a cookie, and return the access token body."""
    raw, token_hash = security.new_refresh_token()
    db.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, issued_at, expires_at) VALUES (%s, %s, %s, %s)",
        (user["id"], token_hash, now, now + timedelta(days=settings.refresh_token_days())),
    )
    access = security.create_access_token(user["id"], user["password_changed_at"], now)
    _set_cookie(response, raw)
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes() * 60,
        "must_change_password": user["must_change_password"],
        "user": _public_user(user),
    }


def revoke_all_refresh_tokens(db, user_id, now) -> None:
    db.execute(
        "UPDATE refresh_tokens SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
        (now, user_id),
    )


def _register_failure(db, user: dict, now, reason: str) -> None:
    """Count a wrong password. At the threshold the account locks for a while."""
    count = user["failed_login_count"] + 1
    if count >= settings.lockout_threshold():
        until = now + timedelta(minutes=settings.lockout_minutes())
        db.execute("UPDATE users SET failed_login_count = 0, locked_until = %s WHERE id = %s", (until, user["id"]))
        auditlog.write(
            db, actor_id=user["id"], actor_role=user["role"], action="ACCOUNT_LOCKED",
            entity_type="user", entity_id=user["id"],
            payload={"locked_until": until.isoformat(), "reason": reason},
        )
    else:
        db.execute("UPDATE users SET failed_login_count = %s WHERE id = %s", (count, user["id"]))
        auditlog.write(
            db, actor_id=user["id"], actor_role=user["role"], action="LOGIN_FAILED",
            entity_type="user", entity_id=user["id"],
            payload={"reason": reason, "attempt": count},
        )


# ------------------------------------------------------------------ login
@router.post("/login")
def login(response: Response, form: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    """
    The form field called "username" holds the email.
    Every failure gives the same 401 message, so nobody can learn which emails exist.
    """
    email = form.username.strip().lower()
    now = clock.utcnow()
    if len(email) > MAX_EMAIL_LENGTH or "\x00" in email:
        user = None  # cannot be a real address; PostgreSQL would refuse a NUL byte with a 500
    else:
        user = db.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE email = %s FOR UPDATE", (email,)).fetchone()

    if user is None:
        security.verify_password(form.password, security.dummy_hash())  # same time as a real check
        auditlog.write(
            db, actor_id=None, actor_role=None, action="LOGIN_FAILED", entity_type="user",
            payload={"reason": "unknown_email", "email_hmac": auditlog.email_fingerprint(email)},
        )
        db.commit()
        raise _login_failed()

    password_ok = security.verify_password(form.password, user["password_hash"])
    locked = user["locked_until"] is not None and user["locked_until"] > now

    if locked:
        auditlog.write(
            db, actor_id=user["id"], actor_role=user["role"], action="LOGIN_BLOCKED",
            entity_type="user", entity_id=user["id"], payload={"reason": "locked"},
        )
        db.commit()
        raise _login_failed()

    if not user["is_active"]:
        auditlog.write(
            db, actor_id=user["id"], actor_role=user["role"], action="LOGIN_FAILED",
            entity_type="user", entity_id=user["id"], payload={"reason": "inactive"},
        )
        db.commit()
        raise _login_failed()

    if not password_ok:
        _register_failure(db, user, now, "wrong_password")
        db.commit()  # keep the counter even though we answer 401
        raise _login_failed()

    db.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = %s WHERE id = %s",
        (now, user["id"]),
    )
    body = _issue_session(db, user, response, now)
    auditlog.write(
        db, actor_id=user["id"], actor_role=user["role"], action="LOGIN_SUCCESS",
        entity_type="user", entity_id=user["id"],
    )
    db.commit()
    return body


# ------------------------------------------------------------------ refresh
def _refresh_denied() -> JSONResponse:
    resp = JSONResponse(
        status_code=401,
        content={"detail": "Session expired. Please log in again."},
        headers={"WWW-Authenticate": "Bearer"},
    )
    _clear_cookie(resp)
    return resp


@router.post("/refresh")
def refresh(request: Request, response: Response, db=Depends(get_db)):
    """Swap the refresh cookie for a new access token and a new refresh cookie (rotation)."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return _refresh_denied()

    now = clock.utcnow()
    token = db.execute(
        "SELECT id, user_id, expires_at, used_at, revoked_at FROM refresh_tokens WHERE token_hash = %s FOR UPDATE",
        (security.hash_refresh_token(raw),),
    ).fetchone()
    if token is None:
        return _refresh_denied()

    if token["used_at"] is not None:
        # An already-exchanged token came back: it was copied. Log this user out everywhere.
        revoke_all_refresh_tokens(db, token["user_id"], now)
        auditlog.write(
            db, actor_id=token["user_id"], actor_role=None, action="REFRESH_REUSE_DETECTED",
            entity_type="user", entity_id=token["user_id"],
        )
        db.commit()
        return _refresh_denied()

    if token["revoked_at"] is not None or token["expires_at"] <= now:
        return _refresh_denied()

    user = db.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s", (token["user_id"],)).fetchone()
    if user is None or not user["is_active"]:
        revoke_all_refresh_tokens(db, token["user_id"], now)
        db.commit()
        return _refresh_denied()

    db.execute("UPDATE refresh_tokens SET used_at = %s WHERE id = %s", (now, token["id"]))
    body = _issue_session(db, user, response, now)
    db.commit()
    return body


# ------------------------------------------------------------------ logout
@router.post("/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    """Works with the cookie alone, so it still works after the access token expired."""
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        token = db.execute(
            "SELECT id, user_id, revoked_at FROM refresh_tokens WHERE token_hash = %s FOR UPDATE",
            (security.hash_refresh_token(raw),),
        ).fetchone()
        if token is not None and token["revoked_at"] is None:
            db.execute("UPDATE refresh_tokens SET revoked_at = %s WHERE id = %s", (clock.utcnow(), token["id"]))
            auditlog.write(
                db, actor_id=token["user_id"], actor_role=None, action="LOGOUT",
                entity_type="user", entity_id=token["user_id"],
            )
            db.commit()
    _clear_cookie(response)
    return {"status": "ok"}


# ------------------------------------------------------------------ change password
class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    response: Response,
    user: CurrentUser = Depends(current_user_any),
    db=Depends(get_db),
):
    now = clock.utcnow()
    row = db.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s FOR UPDATE", (user.id,)).fetchone()

    if row["locked_until"] is not None and row["locked_until"] > now:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    if not security.verify_password(body.current_password, row["password_hash"]):
        _register_failure(db, row, now, "wrong_current_password")
        db.commit()
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")
    try:
        security.validate_new_password(body.new_password, email=row["email"])
    except security.PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    updated = db.execute(
        f"""
        UPDATE users
        SET password_hash = %s, password_changed_at = %s, must_change_password = false,
            failed_login_count = 0, locked_until = NULL
        WHERE id = %s
        RETURNING {_USER_COLUMNS}
        """,
        (security.hash_password(body.new_password), now, user.id),
    ).fetchone()
    revoke_all_refresh_tokens(db, user.id, now)  # every other device must log in again
    auditlog.write(
        db, actor_id=user.id, actor_role=user.role, action="PASSWORD_CHANGED",
        entity_type="user", entity_id=user.id,
    )
    session = _issue_session(db, updated, response, now)  # this device stays logged in
    db.commit()
    return session


# ------------------------------------------------------------------ me
@router.get("/me")
def me(user: CurrentUser = Depends(current_user_any)):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "department_id": user.department_id,
        "must_change_password": user.must_change_password,
    }
