"""
Flags, extensions and waivers (S5). The decisions themselves live in app/core/rules.py.

Who: DEAN (everywhere) and HOD (own department, current semester for extensions) may grant extensions
and waivers. FACULTY may read their own flags but grant nothing. Everything is logged.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import errors
from pydantic import AwareDatetime, Field, field_validator

from app.api.deps import current_user, get_db
from app.api.master import Strict
from app.core import auditlog, clock, rules, score_store
from app.core.scope import DEAN, CurrentUser, can_grant_exception, course_file_filter, forbidden, not_found, require_role

router = APIRouter(tags=["rules"])
MIN_REASON = 10


class ReasonIn(Strict):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def long_enough(cls, v):
        v = v.strip()
        if len(v) < MIN_REASON:
            raise ValueError(f"a reason of at least {MIN_REASON} characters is required")
        return v


class ExtensionIn(ReasonIn):
    new_due_at: AwareDatetime


class BulkWaiveIn(ReasonIn):
    template_id: uuid.UUID


def _scoped_submission(db, submission_id, user):
    scope_sql, params = course_file_filter(user)
    return db.execute(
        f"""SELECT sub.id, sub.course_file_id, cf.semester_id, sem.is_current AS semester_is_current,
                   t.is_active AS template_active, dl.due_at,
                   (SELECT max(e.new_due_at) FROM exceptions e WHERE e.submission_id = sub.id AND e.kind = 'EXTENSION') AS ext_due
            FROM submissions sub JOIN course_files cf ON cf.id = sub.course_file_id
            JOIN semesters sem ON sem.id = cf.semester_id JOIN checklist_templates t ON t.id = sub.template_id
            LEFT JOIN checklist_deadlines dl ON dl.semester_id = cf.semester_id AND dl.template_id = sub.template_id
            WHERE sub.id = %s AND ({scope_sql}) FOR UPDATE OF sub""", (submission_id, *params)).fetchone()


def _waive(db, flag: dict, user: CurrentUser, reason: str, now: datetime, *, automatic: bool = False) -> dict:
    exc = db.execute(
        """INSERT INTO exceptions (course_file_id, submission_id, kind, flag_id, reason, granted_by, granted_at)
           VALUES (%s, %s, 'WAIVER', %s, %s, %s, %s) RETURNING *""",
        (flag["course_file_id"], flag["submission_id"], flag["id"], reason, user.id, now)).fetchone()
    db.execute("UPDATE flags SET status = 'WAIVED' WHERE id = %s AND status = 'OPEN'", (flag["id"],))
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action="flag.waive", entity_type="flag", entity_id=flag["id"],
                   payload={"kind": flag["kind"], "submission_id": str(flag["submission_id"]), "reason": reason,
                            "exception_id": str(exc["id"]), "automatic": automatic})
    return exc


# ---------------------------------------------------------------- extension
@router.post("/submissions/{submission_id}/extensions", status_code=201)
def grant_extension(submission_id: uuid.UUID, body: ExtensionIn,
                    user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    now = clock.utcnow()
    ctx = _scoped_submission(db, submission_id, user)
    if ctx is None:
        raise not_found()
    if not can_grant_exception(user):
        raise forbidden()
    if user.role != DEAN and not ctx["semester_is_current"]:
        raise HTTPException(409, "This semester is closed. Only the Dean can change it.")
    if not ctx["template_active"]:
        raise HTTPException(409, "This checklist item is switched off.")
    current_due = rules.effective_due(ctx["due_at"], ctx["ext_due"])
    if current_due is None:
        raise HTTPException(422, "This item has no deadline, so there is nothing to extend.")
    if body.new_due_at <= current_due:
        raise HTTPException(422, f"The new date must be after the current deadline ({rules.human_time(current_due)}).")

    exc = db.execute(
        """INSERT INTO exceptions (course_file_id, submission_id, kind, new_due_at, reason, granted_by, granted_at)
           VALUES (%s, %s, 'EXTENSION', %s, %s, %s, %s) RETURNING *""",
        (ctx["course_file_id"], submission_id, body.new_due_at, body.reason, user.id, now)).fetchone()
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action="extension.grant", entity_type="submission",
                   entity_id=submission_id, payload={"exception_id": str(exc["id"]), "old_due_at": current_due.isoformat(),
                                                     "new_due_at": body.new_due_at.isoformat(), "reason": body.reason})

    # An extension that covers the delivery also sets the lateness flag aside (with its own waiver row).
    waived_late = None
    late = db.execute("SELECT * FROM flags WHERE submission_id = %s AND kind = 'LATE' AND status = 'OPEN'", (submission_id,)).fetchone()
    first = db.execute("SELECT min(uploaded_at) AS at FROM submission_versions WHERE submission_id = %s", (submission_id,)).fetchone()["at"]
    if late is not None and first is not None and first <= body.new_due_at:
        _waive(db, late, user, f"Covered by the extension granted to {rules.human_time(body.new_due_at)}: {body.reason}", now, automatic=True)
        waived_late = late["id"]
    changes = rules.evaluate_submission(db, submission_id, now=now, trigger="extension", by_user=user.id)
    db.commit()
    return {"exception": exc, "late_flag_waived": waived_late, "changes": changes}


# ---------------------------------------------------------------- waiver
@router.post("/flags/{flag_id}/waive")
def waive_flag(flag_id: uuid.UUID, body: ReasonIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    flag = db.execute(
        f"""SELECT f.* FROM flags f JOIN course_files cf ON cf.id = f.course_file_id
            WHERE f.id = %s AND ({scope_sql}) FOR UPDATE OF f""", (flag_id, *params)).fetchone()
    if flag is None:
        raise not_found()
    if not can_grant_exception(user):
        raise forbidden()
    if flag["status"] != "OPEN":
        raise HTTPException(409, f"This flag is already {flag['status']}.")
    if user.role != DEAN:
        sem = db.execute("SELECT s.is_current FROM course_files cf JOIN semesters s ON s.id = cf.semester_id WHERE cf.id = %s",
                         (flag["course_file_id"],)).fetchone()
        if not sem["is_current"]:
            raise HTTPException(409, "This semester is closed. Only the Dean can change it.")
    now = clock.utcnow()
    exc = _waive(db, flag, user, body.reason, now)
    score_store.refresh_course_files(db, [flag["course_file_id"]], trigger="waiver", now=now)
    db.commit()
    return {"flag_id": flag_id, "status": "WAIVED", "exception": exc}


@router.post("/semesters/{semester_id}/waive-late")
def waive_all_late(semester_id: uuid.UUID, body: BulkWaiveIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Dean only: set aside every open lateness flag of one checklist item in one semester, with one reason."""
    require_role(user, DEAN)
    if db.execute("SELECT 1 FROM semesters WHERE id = %s", (semester_id,)).fetchone() is None:
        raise not_found()
    if db.execute("SELECT 1 FROM checklist_templates WHERE id = %s", (body.template_id,)).fetchone() is None:
        raise HTTPException(422, "Unknown checklist template.")
    flags = db.execute(
        """SELECT f.* FROM flags f JOIN submissions sub ON sub.id = f.submission_id JOIN course_files cf ON cf.id = f.course_file_id
           WHERE cf.semester_id = %s AND sub.template_id = %s AND f.kind = 'LATE' AND f.status = 'OPEN'
           ORDER BY f.id FOR UPDATE OF f""", (semester_id, body.template_id)).fetchall()
    now = clock.utcnow()
    for flag in flags:
        _waive(db, flag, user, body.reason, now)
    score_store.refresh_course_files(db, {f["course_file_id"] for f in flags}, trigger="waiver", now=now)
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action="flags.waive_late_bulk", entity_type="semester",
                   entity_id=semester_id, payload={"template_id": str(body.template_id), "count": len(flags), "reason": body.reason})
    db.commit()
    return {"waived": len(flags)}


# ---------------------------------------------------------------- read
_FLAG_SELECT = """
    SELECT f.id, f.course_file_id, f.submission_id, f.kind, f.status, f.reason, f.detail,
           f.raised_by_version_id, f.raised_at, f.cleared_by_version_id, f.cleared_at,
           t.code AS template_code, t.title AS template_title
    FROM flags f
    JOIN course_files cf ON cf.id = f.course_file_id
    LEFT JOIN submissions sub ON sub.id = f.submission_id
    LEFT JOIN checklist_templates t ON t.id = sub.template_id
"""


def _with_exceptions(db, flags: list[dict]) -> list[dict]:
    ids = [f["id"] for f in flags]
    rows = db.execute(
        """SELECT e.id, e.flag_id, e.kind, e.reason, e.granted_at, e.granted_by, u.full_name AS granted_by_name
           FROM exceptions e JOIN users u ON u.id = e.granted_by WHERE e.flag_id = ANY(%s) ORDER BY e.granted_at""", (ids,)).fetchall()
    for f in flags:
        f["exceptions"] = [r for r in rows if r["flag_id"] == f["id"]]
    return flags


@router.get("/course-files/{course_file_id}/flags")
def list_flags(course_file_id: uuid.UUID, status: str | None = Query(default=None, pattern="^(OPEN|CLEARED|WAIVED)$"),
               user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    if db.execute(f"SELECT 1 FROM course_files cf WHERE cf.id = %s AND ({scope_sql})", (course_file_id, *params)).fetchone() is None:
        raise not_found()
    where, args = "f.course_file_id = %s", [course_file_id]
    if status:
        where, args = where + " AND f.status = %s", args + [status]
    flags = db.execute(f"{_FLAG_SELECT} WHERE {where} ORDER BY f.raised_at, f.id", args).fetchall()
    return _with_exceptions(db, flags)


@router.get("/flags")
def list_all_flags(
    status: str | None = Query(default=None, pattern="^(OPEN|CLEARED|WAIVED)$"),
    kind: str | None = Query(default=None, pattern="^(LATE|MISSING|INCOMPLETE|FORMAT|CONTENT|MISMATCH|ANOMALY)$"),
    semester_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    course_file_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(current_user),
    db=Depends(get_db),
):
    """Flags across every course file the caller may see (dashboards). Defaults to the current semester."""
    scope_sql, params = course_file_filter(user)
    if semester_id is None:
        cur = db.execute("SELECT id FROM semesters WHERE is_current").fetchone()
        if cur is None:
            return {"semester_id": None, "total": 0, "limit": limit, "offset": offset, "flags": []}
        semester_id = cur["id"]
    elif db.execute("SELECT 1 FROM semesters WHERE id = %s", (semester_id,)).fetchone() is None:
        raise not_found()
    where, args = [f"({scope_sql})", "cf.semester_id = %s"], [*params, semester_id]
    for column, value in (("f.status", status), ("f.kind", kind), ("cf.department_id", department_id),
                          ("f.course_file_id", course_file_id)):
        if value is not None:
            where.append(f"{column} = %s")
            args.append(value)
    cond = " AND ".join(where)
    total = db.execute(f"SELECT count(*) AS n FROM flags f JOIN course_files cf ON cf.id = f.course_file_id WHERE {cond}",
                       args).fetchone()["n"]
    flags = db.execute(
        f"""SELECT f.id, f.course_file_id, f.submission_id, f.kind, f.status, f.reason, f.detail,
                   f.raised_at, f.cleared_at, t.code AS template_code, t.title AS template_title,
                   cf.semester_id, cf.department_id, d.code AS department_code,
                   s.code AS subject_code, s.name AS subject_name, cf.division,
                   cf.faculty_id, u.full_name AS faculty_name
            FROM flags f
            JOIN course_files cf ON cf.id = f.course_file_id
            JOIN subjects s ON s.id = cf.subject_id
            JOIN users u ON u.id = cf.faculty_id
            JOIN departments d ON d.id = cf.department_id
            LEFT JOIN submissions sub ON sub.id = f.submission_id
            LEFT JOIN checklist_templates t ON t.id = sub.template_id
            WHERE {cond}
            ORDER BY f.raised_at DESC, f.id
            LIMIT %s OFFSET %s""", (*args, limit, offset)).fetchall()
    return {"semester_id": semester_id, "total": total, "limit": limit, "offset": offset,
            "flags": _with_exceptions(db, flags)}


@router.get("/flags/{flag_id}")
def get_flag(flag_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    flags = db.execute(f"{_FLAG_SELECT} WHERE f.id = %s AND ({scope_sql})", (flag_id, *params)).fetchall()
    if not flags:
        raise not_found()
    return _with_exceptions(db, flags)[0]


# ---------------------------------------------------------------- manual evaluation
@router.post("/rules/evaluate")
def evaluate_now(semester_id: uuid.UUID | None = None, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Dean only. Same check the API runs by itself every few minutes. Safe to press any number of times."""
    require_role(user, DEAN)
    if semester_id is not None and db.execute("SELECT 1 FROM semesters WHERE id = %s", (semester_id,)).fetchone() is None:
        raise not_found()
    db.commit()
    result = rules.sweep(db, now=clock.utcnow(), semester_id=semester_id, trigger="manual", by_user=user.id, by_role=user.role)
    if result is None:
        raise HTTPException(409, "A check is already running. Try again in a minute.")
    return result
