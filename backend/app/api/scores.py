"""
Trust score endpoints (S6). The maths lives in app/core/scoring.py, the history in app/core/score_store.py.

Reads: every role, limited by app/core/scope.py (faculty own files, HOD own department, Dean all).
Weights are readable by everyone (a faculty member can see how the score is built). Only the Dean changes them.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator, model_validator

from app.api.deps import current_user, get_db
from app.api.master import Strict
from app.core import auditlog, clock, score_store, scoring, settings
from app.core.scope import DEAN, CurrentUser, course_file_filter, not_found, require_role

router = APIRouter(tags=["scores"])
MIN_REASON = 10

_CF_SELECT = """
    SELECT cf.id, cf.semester_id, sem.is_current, sem.academic_year, sem.term,
           cf.subject_id, s.code AS subject_code, s.name AS subject_name,
           cf.faculty_id, u.full_name AS faculty_name,
           cf.department_id, d.code AS department_code, cf.division
    FROM course_files cf
    JOIN subjects s    ON s.id = cf.subject_id
    JOIN semesters sem ON sem.id = cf.semester_id
    JOIN users u       ON u.id = cf.faculty_id
    JOIN departments d ON d.id = cf.department_id
"""


def _one_course_file(db, course_file_id, user) -> dict:
    scope_sql, params = course_file_filter(user)
    cf = db.execute(f"{_CF_SELECT} WHERE cf.id = %s AND ({scope_sql})", (course_file_id, *params)).fetchone()
    if cf is None:
        raise not_found()
    return cf


def _header(cf: dict) -> dict:
    return {k: cf[k] for k in ("semester_id", "academic_year", "term", "subject_id", "subject_code",
                               "subject_name", "faculty_id", "faculty_name", "department_id", "department_code",
                               "division")} | {"course_file_id": cf["id"], "semester_is_current": cf["is_current"]}


# ---------------------------------------------------------------- one course file
@router.get("/course-files/{course_file_id}/score")
def get_score(course_file_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Current semester: computed live. Closed semester: the frozen score of record (latest snapshot)."""
    cf = _one_course_file(db, course_file_id, user)
    view = score_store.score_views(db, [cf], clock.utcnow())[cf["id"]]
    return {**_header(cf), **view}


@router.get("/course-files/{course_file_id}/score/history")
def get_score_history(course_file_id: uuid.UUID, limit: int = Query(default=50, ge=1, le=500),
                      user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Every time the score changed, newest first. Without the long breakdown (see /score-snapshots/{id})."""
    cf = _one_course_file(db, course_file_id, user)
    rows = db.execute(
        """SELECT id, created_at, trigger, is_final, status, total, completeness_pts, timeliness_pts, format_pts,
                  content_pts, weights_id, content_active, items_total, items_pending
           FROM score_snapshots WHERE course_file_id = %s ORDER BY id DESC LIMIT %s""",
        (cf["id"], limit)).fetchall()
    return {**_header(cf), "snapshots": rows}


@router.get("/score-snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: int, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    snap = db.execute(
        f"""SELECT sn.* FROM score_snapshots sn JOIN course_files cf ON cf.id = sn.course_file_id
            WHERE sn.id = %s AND ({scope_sql})""", (snapshot_id, *params)).fetchone()
    if snap is None:
        raise not_found()
    return score_store.view_of_snapshot(snap) | {"course_file_id": snap["course_file_id"],
                                                 "semester_id": snap["semester_id"]}


# ---------------------------------------------------------------- lists for dashboards
@router.get("/scores")
def list_scores(semester_id: uuid.UUID | None = None, department_id: uuid.UUID | None = None,
                subject_id: uuid.UUID | None = None, limit: int = Query(default=200, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """One line per course file (no item detail). Defaults to the current semester."""
    scope_sql, params = course_file_filter(user)
    if semester_id is None:
        cur = db.execute("SELECT id FROM semesters WHERE is_current").fetchone()
        if cur is None:
            return {"semester_id": None, "total": 0, "scores": []}
        semester_id = cur["id"]
    elif db.execute("SELECT 1 FROM semesters WHERE id = %s", (semester_id,)).fetchone() is None:
        raise not_found()
    where, args = ["cf.semester_id = %s"], [semester_id]
    if department_id is not None:
        where.append("cf.department_id = %s")
        args.append(department_id)
    if subject_id is not None:
        where.append("cf.subject_id = %s")
        args.append(subject_id)
    cond = f"({scope_sql}) AND " + " AND ".join(where)
    count = db.execute(f"SELECT count(*) AS n FROM course_files cf WHERE {cond}", (*params, *args)).fetchone()["n"]
    rows = db.execute(f"{_CF_SELECT} WHERE {cond} ORDER BY d.code, s.code, u.full_name, cf.division, cf.id "
                      f"LIMIT %s OFFSET %s", (*params, *args, limit, offset)).fetchall()
    views = score_store.score_views(db, rows, clock.utcnow())
    out = []
    for cf in rows:
        v = views[cf["id"]]
        out.append({
            "course_file_id": cf["id"], "subject_code": cf["subject_code"], "subject_name": cf["subject_name"],
            "faculty_id": cf["faculty_id"], "faculty_name": cf["faculty_name"], "department_id": cf["department_id"],
            "department_code": cf["department_code"], "division": cf["division"],
            "source": v["source"], "is_final": v["is_final"], "as_of": v["as_of"], "status": v["status"],
            "total": v["total"],
            "parts": {p: v["parts"][p]["points"] for p in scoring.PARTS},
            "items_total": v["items_total"], "items_pending": v["items_pending"],
            "open_problems": sum(1 for i in v["items"] if i["state"] not in ("OK", "PENDING", "WAIVED")),
        })
    return {"semester_id": semester_id, "total": count, "limit": limit, "offset": offset, "scores": out}


# ---------------------------------------------------------------- weights
_W_SELECT = """
    SELECT w.id, w.completeness, w.timeliness, w.format, w.content, w.reason, w.set_by,
           u.full_name AS set_by_name, w.created_at
    FROM score_weights w LEFT JOIN users u ON u.id = w.set_by
"""


class WeightsIn(Strict):
    completeness: int = Field(ge=0, le=100)
    timeliness: int = Field(ge=0, le=100)
    format: int = Field(ge=0, le=100)
    content: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=2000)
    # False (default): the new weights apply to semesters that become current from now on.
    # True: also re-score the CURRENT semester with them now (goalposts move mid-semester, so say why).
    apply_now: bool = False

    @field_validator("reason")
    @classmethod
    def long_enough(cls, v):
        v = v.strip()
        if len(v) < MIN_REASON:
            raise ValueError(f"a reason of at least {MIN_REASON} characters is required")
        return v

    @model_validator(mode="after")
    def v_sum(self):
        if self.completeness + self.timeliness + self.format + self.content != 100:
            raise ValueError("the four weights must add up to exactly 100")
        if self.completeness + self.timeliness + self.format < 50:
            raise ValueError("Completeness, Timeliness and Format together must be at least 50 "
                             "(Content may carry at most half of the score)")
        return self


def _weights_view(db, current_sem: dict | None) -> dict:
    latest = db.execute(f"{_W_SELECT} ORDER BY w.id DESC LIMIT 1").fetchone()
    in_force = None
    if current_sem is not None:
        sw = score_store.semester_weights(db, current_sem["id"])
        in_force = db.execute(f"{_W_SELECT} WHERE w.id = %s", (sw["id"],)).fetchone()
    return {"latest": latest, "current_semester": ({"semester_id": current_sem["id"], "weights": in_force}
                                                   if current_sem else None),
            "content_scoring_enabled": settings.content_scoring_enabled()}


@router.get("/score-weights")
def get_weights(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    cur = db.execute("SELECT id FROM semesters WHERE is_current").fetchone()
    view = _weights_view(db, cur)
    base = view["current_semester"]["weights"] if view["current_semester"] else view["latest"]
    eff = scoring.effective_weights(base, settings.content_scoring_enabled())
    view["effective_for_current_semester"] = {p: float(v) for p, v in eff.items()}
    return view


@router.get("/score-weights/history")
def weights_history(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    weights = db.execute(f"{_W_SELECT} ORDER BY w.id DESC").fetchall()
    assigned = db.execute(
        """SELECT sw.id, sw.semester_id, sem.academic_year, sem.term, sw.weights_id, sw.reason, sw.set_by,
                  sw.created_at
           FROM semester_weights sw JOIN semesters sem ON sem.id = sw.semester_id
           ORDER BY sw.id DESC""").fetchall()
    return {"weights": weights, "semester_assignments": assigned}


@router.post("/score-weights", status_code=201)
def set_weights(body: WeightsIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Dean only. Appends a new row (old rows stay forever). Needs a reason. Always audited."""
    require_role(user, DEAN)
    old = score_store.latest_weights(db)
    new_vals = {p: getattr(body, p) for p in scoring.PARTS}
    if all(old[p] == new_vals[p] for p in scoring.PARTS):
        raise HTTPException(409, "These are already the current weights.")
    cur = db.execute("SELECT id FROM semesters WHERE is_current FOR UPDATE").fetchone()
    if body.apply_now and cur is None:
        raise HTTPException(409, "There is no current semester to apply the weights to.")
    now = clock.utcnow()
    row = db.execute(
        """INSERT INTO score_weights (completeness, timeliness, format, content, set_by, reason)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (*new_vals.values(), user.id, body.reason)).fetchone()
    rescored = None
    if body.apply_now:
        db.execute("INSERT INTO semester_weights (semester_id, weights_id, reason, set_by) VALUES (%s, %s, %s, %s)",
                   (cur["id"], row["id"], body.reason, user.id))
        rescored = score_store.refresh_semester(db, cur["id"], trigger="weights_change", now=now)
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action="score_weights.set",
                   entity_type="score_weights", entity_id=row["id"],
                   payload={"old": {p: old[p] for p in scoring.PARTS}, "new": new_vals, "reason": body.reason,
                            "apply_now": body.apply_now, "rescored": rescored})
    db.commit()
    view = _weights_view(db, cur)
    return {**view, "applied_to_current_semester": body.apply_now,
            "message": ("Saved. The current semester was re-scored with these weights."
                        if body.apply_now else
                        "Saved. The current semester keeps its weights. These apply to semesters made current from now on.")}
