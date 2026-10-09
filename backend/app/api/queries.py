"""
Query / dispute workflow (S8): a faculty member disputes a flag, the HOD looks first, the Dean decides last.

Story of one query
  RAISE     faculty owner of the course file, on an OPEN flag, current semester. Starts at the HOD.
            (A HOD who owns the course file cannot review their own query, so it starts at the Dean.)
  REPLY     the author, and whoever may decide at the current level.
  ESCALATE  the HOD hands it to the Dean ("I cannot resolve this").
  RESOLVE   UPHELD (flag stays) or OVERTURNED (flag is waived, full credit, score is recomputed).
            HOD decides at the HOD level. The Dean may decide at any level (at the HOD level this is
            marked as an override, for example when the HOD is away). Nobody decides their own query.
  APPEAL    after a HOD "upheld" the author may go to the Dean once, within APPEAL_DAYS.
            A Dean decision is final.

Rules of thumb
  * One query per flag for the life of the flag. An open query does not change the score; only an
    overturn does (through a normal waiver row).
  * Every action writes a query_steps row (never changed) and an audit_log row, in ONE transaction.
  * Visibility comes from scope.py only (404 when out of scope), permission checks give 403.
  * The server tells the UI what the caller may do ("can"), so the UI never guesses.
"""
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import errors
from pydantic import Field, field_validator

from app.api.deps import current_user, get_db
from app.api.master import Strict
from app.api.rules import _waive  # the same waiver code the Dean and HOD use, so a waiver always looks the same
from app.core import auditlog, clock, score_store
from app.core.scope import DEAN, FACULTY, HOD, CurrentUser, course_file_filter, forbidden, not_found

router = APIRouter(tags=["queries"])

APPEAL_DAYS = 7
MIN_MESSAGE = 10
MIN_REPLY = 3


def _clean(minimum: int):
    def check(v: str) -> str:
        v = v.strip()
        if len(v) < minimum:
            raise ValueError(f"a message of at least {minimum} characters is required")
        return v
    return check


class MessageIn(Strict):
    message: str = Field(min_length=1, max_length=2000)
    _v = field_validator("message")(_clean(MIN_MESSAGE))


class ReplyIn(Strict):
    message: str = Field(min_length=1, max_length=2000)
    _v = field_validator("message")(_clean(MIN_REPLY))


class ResolveIn(Strict):
    outcome: Literal["UPHELD", "OVERTURNED"]
    message: str = Field(min_length=1, max_length=2000)
    _v = field_validator("message")(_clean(MIN_MESSAGE))


# ---------------------------------------------------------------- loading
_COLUMNS = """
    q.id, q.flag_id, q.raised_by, rb.full_name AS raised_by_name, rb.role AS raised_by_role,
           q.current_level, q.status, q.appealed, q.created_at, q.resolved_at, q.resolved_by,
           q.resolved_level, q.exception_id, q.last_activity_at,
           f.kind AS flag_kind, f.status AS flag_status, f.reason AS flag_reason,
           t.code AS template_code, t.title AS template_title,
           cf.id AS course_file_id, cf.semester_id, sem.is_current AS semester_is_current,
           cf.department_id, d.code AS department_code, cf.division,
           cf.faculty_id, fu.full_name AS faculty_name,
           s.code AS subject_code, s.name AS subject_name"""
_FROM = """
    FROM queries q
    JOIN flags f ON f.id = q.flag_id
    JOIN course_files cf ON cf.id = f.course_file_id
    JOIN semesters sem ON sem.id = cf.semester_id
    JOIN subjects s ON s.id = cf.subject_id
    JOIN departments d ON d.id = cf.department_id
    JOIN users fu ON fu.id = cf.faculty_id
    JOIN users rb ON rb.id = q.raised_by
    LEFT JOIN submissions sub ON sub.id = f.submission_id
    LEFT JOIN checklist_templates t ON t.id = sub.template_id
"""
_SELECT = f"SELECT {_COLUMNS} {_FROM}"


def _load(db, query_id, user: CurrentUser, *, lock: bool = False):
    scope_sql, params = course_file_filter(user)
    row = db.execute(
        f"{_SELECT} WHERE q.id = %s AND ({scope_sql}) {'FOR UPDATE OF q' if lock else ''}",
        (query_id, *params),
    ).fetchone()
    if row is None:
        raise not_found()
    return row


def appeal_open(q: dict, now: datetime) -> bool:
    """True while the author may still take a HOD 'upheld' to the Dean (once, inside APPEAL_DAYS)."""
    return (
        q["status"] == "RESOLVED_UPHELD"
        and q["resolved_level"] == "HOD"
        and not q["appealed"]
        and q["resolved_at"] is not None
        and now <= q["resolved_at"] + timedelta(days=APPEAL_DAYS)
    )


def abilities(user: CurrentUser, q: dict, now: datetime) -> dict:
    """What this user may do with this query right now. The one place these rules live."""
    is_author = q["raised_by"] == user.id
    is_open = q["status"] == "OPEN"
    hod_may = (user.role == HOD and not is_author and q["current_level"] == "HOD"
               and user.department_id == q["department_id"])
    dean_may = user.role == DEAN and not is_author
    decide = is_open and (hod_may or dean_may)
    return {
        "reply": is_open and (is_author or hod_may or dean_may),
        "escalate": is_open and hod_may,
        "resolve": decide,
        "appeal": is_author and appeal_open(q, now),
        "override": decide and dean_may and q["current_level"] == "HOD",
    }


def _steps(db, query_id) -> list[dict]:
    return db.execute(
        """SELECT st.id, st.action, st.level, st.actor_id, u.full_name AS actor_name, st.actor_role,
                  st.override, st.outcome, st.message, st.created_at
           FROM query_steps st JOIN users u ON u.id = st.actor_id
           WHERE st.query_id = %s ORDER BY st.seq""", (query_id,)).fetchall()


def _detail(db, query_id, user: CurrentUser, now: datetime) -> dict:
    q = _load(db, query_id, user)
    return {**q, "steps": _steps(db, query_id), "can": abilities(user, q, now)}


def _add_step(db, q: dict, user: CurrentUser, action: str, message: str, now: datetime, *,
              outcome: str | None = None, override: bool = False) -> dict:
    """One history row plus one audit row. The query's own level at the time is stored with the step."""
    step = db.execute(
        """INSERT INTO query_steps (query_id, actor_id, actor_role, action, level, message, outcome, override, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (q["id"], user.id, user.role, action, q["current_level"], message, outcome, override, now)).fetchone()
    # The text stays in query_steps only. The audit log gets the facts and a pointer (less personal data in a log
    # that can never be edited).
    auditlog.write(
        db, actor_id=user.id, actor_role=user.role, action=f"query.{action.lower()}", entity_type="query",
        entity_id=q["id"],
        payload={"flag_id": str(q["flag_id"]), "step_id": str(step["id"]), "level": q["current_level"],
                 "override": override, **({"outcome": outcome} if outcome else {})})
    db.execute("UPDATE queries SET last_activity_at = %s WHERE id = %s", (now, q["id"]))
    return step


# ---------------------------------------------------------------- raise
@router.post("/flags/{flag_id}/queries", status_code=201)
def raise_query(flag_id: uuid.UUID, body: MessageIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    flag = db.execute(
        f"""SELECT f.id, f.status, f.kind, cf.faculty_id, sem.is_current AS semester_is_current
            FROM flags f JOIN course_files cf ON cf.id = f.course_file_id
            JOIN semesters sem ON sem.id = cf.semester_id
            WHERE f.id = %s AND ({scope_sql}) FOR UPDATE OF f""", (flag_id, *params)).fetchone()
    if flag is None:
        raise not_found()
    # Only the owner of the course file argues about its flags. HOD and Dean can see the flag, but not raise.
    if user.role == DEAN or flag["faculty_id"] != user.id:
        raise forbidden()
    if flag["status"] != "OPEN":
        raise HTTPException(409, f"This flag is already {flag['status']}, so there is nothing to dispute.")
    if not flag["semester_is_current"]:
        raise HTTPException(409, "This semester is closed. Queries can only be raised in the current semester.")
    if db.execute("SELECT 1 FROM queries WHERE flag_id = %s", (flag_id,)).fetchone() is not None:
        raise HTTPException(409, "This flag already has a query.")

    now = clock.utcnow()
    # A HOD who owns the course file cannot review their own query: it starts at the Dean.
    level = "DEAN" if user.role == HOD else "HOD"
    try:
        q = db.execute(
            """INSERT INTO queries (flag_id, raised_by, current_level, created_at, last_activity_at)
               VALUES (%s, %s, %s, %s, %s) RETURNING id, flag_id, current_level""",
            (flag_id, user.id, level, now, now)).fetchone()
    except errors.UniqueViolation:
        raise HTTPException(409, "This flag already has a query.")
    _add_step(db, q, user, "RAISE", body.message, now)
    db.commit()
    return _detail(db, q["id"], user, now)


# ---------------------------------------------------------------- reads
def _waiting_sql(user: CurrentUser) -> tuple[str, tuple]:
    """
    Queries where the ball is in THIS user's court (scope is applied separately). The last step tells:
      author   : open, and somebody else acted last (an answer is waiting for them)
      HOD      : open, at the HOD level, not their own, and the author acted last
      DEAN     : open, at the Dean level, and the Dean did not act last (escalation, appeal, author's reply)
    """
    as_author = "(q.status = 'OPEN' AND q.raised_by = %s AND ls.last_actor_id <> %s)"
    if user.role == DEAN:
        return "(q.status = 'OPEN' AND q.current_level = 'DEAN' AND ls.last_actor_role <> 'DEAN')", ()
    if user.role == HOD:
        as_hod = ("(q.status = 'OPEN' AND q.current_level = 'HOD' AND q.raised_by <> %s "
                  "AND ls.last_actor_id = q.raised_by)")
        return f"({as_hod} OR {as_author})", (user.id, user.id, user.id)
    return as_author, (user.id, user.id)


_LAST_STEP = """LEFT JOIN LATERAL (
        SELECT st.actor_id AS last_actor_id, st.actor_role AS last_actor_role, st.action AS last_action
        FROM query_steps st WHERE st.query_id = q.id ORDER BY st.seq DESC LIMIT 1) ls ON TRUE"""


@router.get("/queries/count")
def count_queries(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Small numbers for the menu badge: how many queries wait for me, how many are open in my scope."""
    scope_sql, params = course_file_filter(user)
    waiting_sql, waiting_params = _waiting_sql(user)
    row = db.execute(
        f"""SELECT count(*) FILTER (WHERE {waiting_sql}) AS waiting_for_me,
                   count(*) FILTER (WHERE q.status = 'OPEN') AS open
            FROM queries q JOIN flags f ON f.id = q.flag_id JOIN course_files cf ON cf.id = f.course_file_id
            {_LAST_STEP} WHERE ({scope_sql})""", (*waiting_params, *params)).fetchone()
    return {"waiting_for_me": row["waiting_for_me"], "open": row["open"]}


@router.get("/queries")
def list_queries(
    status: str | None = Query(default=None, pattern="^(OPEN|RESOLVED_UPHELD|RESOLVED_OVERTURNED)$"),
    level: str | None = Query(default=None, pattern="^(HOD|DEAN)$"),
    course_file_id: uuid.UUID | None = None,
    flag_id: uuid.UUID | None = None,
    waiting_for_me: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(current_user),
    db=Depends(get_db),
):
    now = clock.utcnow()
    scope_sql, params = course_file_filter(user)
    where, args = [f"({scope_sql})"], list(params)
    for column, value in (("q.status", status), ("q.current_level", level),
                          ("cf.id", course_file_id), ("q.flag_id", flag_id)):
        if value is not None:
            where.append(f"{column} = %s")
            args.append(value)
    if waiting_for_me:
        w_sql, w_params = _waiting_sql(user)
        where.append(w_sql)
        args.extend(w_params)
    cond = " AND ".join(where)
    total = db.execute(
        f"""SELECT count(*) AS n FROM queries q JOIN flags f ON f.id = q.flag_id
            JOIN course_files cf ON cf.id = f.course_file_id {_LAST_STEP} WHERE {cond}""", args).fetchone()["n"]
    rows = db.execute(
        f"""SELECT ls.last_actor_id, ls.last_actor_role, ls.last_action, {_COLUMNS} {_FROM} {_LAST_STEP}
            WHERE {cond}
            ORDER BY (q.status = 'OPEN') DESC, q.last_activity_at DESC, q.id
            LIMIT %s OFFSET %s""", (*args, limit, offset)).fetchall()
    for r in rows:
        r["can"] = abilities(user, r, now)
    return {"total": total, "limit": limit, "offset": offset, "queries": rows}


@router.get("/queries/{query_id}")
def get_query(query_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    return _detail(db, query_id, user, clock.utcnow())


# ---------------------------------------------------------------- actions
def _open_query_for(db, query_id, user: CurrentUser, need: str, now: datetime) -> dict:
    """Load + lock a query, check the caller may do `need`, and that it is still open."""
    q = _load(db, query_id, user, lock=True)
    if q["status"] != "OPEN":
        raise HTTPException(409, "This query is already decided.")
    if not abilities(user, q, now)[need]:
        raise forbidden()
    return q


@router.post("/queries/{query_id}/reply")
def reply(query_id: uuid.UUID, body: ReplyIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    now = clock.utcnow()
    q = _open_query_for(db, query_id, user, "reply", now)
    override = abilities(user, q, now)["override"]
    _add_step(db, q, user, "REPLY", body.message, now, override=override)
    db.commit()
    return _detail(db, query_id, user, now)


@router.post("/queries/{query_id}/escalate")
def escalate(query_id: uuid.UUID, body: MessageIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    now = clock.utcnow()
    q = _open_query_for(db, query_id, user, "escalate", now)
    _add_step(db, q, user, "ESCALATE", body.message, now)  # stored at the level it came from (HOD)
    db.execute("UPDATE queries SET current_level = 'DEAN' WHERE id = %s", (query_id,))
    db.commit()
    return _detail(db, query_id, user, now)


@router.post("/queries/{query_id}/resolve")
def resolve(query_id: uuid.UUID, body: ResolveIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    now = clock.utcnow()
    q = _open_query_for(db, query_id, user, "resolve", now)
    override = abilities(user, q, now)["override"]
    if body.outcome == "OVERTURNED" and user.role != DEAN and not q["semester_is_current"]:
        raise HTTPException(409, "This semester is closed. Only the Dean can overturn a flag. Escalate it to the Dean.")

    scope_sql, params = course_file_filter(user)
    flag = db.execute(
        f"""SELECT f.* FROM flags f JOIN course_files cf ON cf.id = f.course_file_id
            WHERE f.id = %s AND ({scope_sql}) FOR UPDATE OF f""", (q["flag_id"], *params)).fetchone()
    exception_id, flag_change = None, "none"
    if body.outcome == "OVERTURNED":
        if flag["status"] == "OPEN":
            exc = _waive(db, flag, user, f"Query overturned by the {user.role}: {body.message}", now)
            exception_id, flag_change = exc["id"], "waived"
            score_store.refresh_course_files(db, [flag["course_file_id"]], trigger="query", now=now)
        else:
            # Already waived or cleared by another route while the query was open: nothing left to change.
            flag_change = f"already {flag['status'].lower()}"
    _add_step(db, q, user, "RESOLVE", body.message, now, outcome=body.outcome, override=override)
    db.execute(
        """UPDATE queries SET status = %s, resolved_at = %s, resolved_by = %s, resolved_level = %s, exception_id = %s
           WHERE id = %s""",
        ("RESOLVED_UPHELD" if body.outcome == "UPHELD" else "RESOLVED_OVERTURNED", now, user.id,
         "DEAN" if user.role == DEAN else "HOD", exception_id, query_id))
    db.commit()
    return {**_detail(db, query_id, user, now), "flag_change": flag_change}


@router.post("/queries/{query_id}/appeal")
def appeal(query_id: uuid.UUID, body: MessageIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    now = clock.utcnow()
    q = _load(db, query_id, user, lock=True)
    if q["raised_by"] != user.id:
        raise forbidden()
    if q["status"] == "OPEN":
        raise HTTPException(409, "This query is still open, there is no decision to appeal.")
    if q["status"] == "RESOLVED_OVERTURNED" or q["resolved_level"] != "HOD":
        raise HTTPException(409, "Only a HOD decision that kept the flag can be appealed. This decision is final.")
    if q["appealed"]:
        raise HTTPException(409, "This query was already appealed once. The Dean's decision is final.")
    if not appeal_open(q, now):
        raise HTTPException(409, f"The appeal window of {APPEAL_DAYS} days has passed.")
    # Reopen first: a decided query accepts exactly this one change (the database guard checks it).
    db.execute(
        """UPDATE queries SET status = 'OPEN', current_level = 'DEAN', appealed = true,
                  resolved_at = NULL, resolved_by = NULL, resolved_level = NULL
           WHERE id = %s""", (query_id,))
    _add_step(db, q, user, "APPEAL", body.message, now)  # stored at the HOD level, where the decision was made
    db.commit()
    return _detail(db, query_id, user, now)
