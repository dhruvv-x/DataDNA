"""Course files (S3 read, S4 create + checklist view). Create is DEAN only; reading is scoped by role."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import errors
from pydantic import Field, field_validator

from app.api.master import Strict

from app.api.deps import current_user, get_db
from app.core import auditlog, clock, score_store
from app.core.scope import DEAN, FACULTY, CurrentUser, course_file_filter, not_found, require_role
from app.core.submission_rows import create_for_course_file

router = APIRouter(prefix="/course-files", tags=["course-files"])

_SELECT = """
    SELECT cf.id, cf.subject_id, s.code AS subject_code, s.name AS subject_name,
           cf.semester_id, sem.academic_year, sem.term, sem.is_current,
           cf.faculty_id, u.full_name AS faculty_name,
           cf.department_id, d.code AS department_code,
           cf.division, cf.created_at
    FROM course_files cf
    JOIN subjects s    ON s.id = cf.subject_id
    JOIN semesters sem ON sem.id = cf.semester_id
    JOIN users u       ON u.id = cf.faculty_id
    JOIN departments d ON d.id = cf.department_id
"""


@router.get("")
def list_course_files(
    semester_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(current_user),
    db=Depends(get_db),
):
    scope_sql, params = course_file_filter(user)
    where, args = [f"({scope_sql})"], list(params)
    for column, value in (("cf.semester_id", semester_id), ("cf.faculty_id", faculty_id), ("cf.department_id", department_id)):
        if value is not None:
            where.append(f"{column} = %s")
            args.append(value)
    return db.execute(
        f"""{_SELECT} WHERE {' AND '.join(where)}
            ORDER BY sem.start_date DESC, s.code, cf.division NULLS FIRST, u.full_name, cf.id
            LIMIT %s OFFSET %s""",
        (*args, limit, offset),
    ).fetchall()


@router.get("/{course_file_id}")
def get_course_file(course_file_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    row = db.execute(f"{_SELECT} WHERE cf.id = %s AND ({scope_sql})", (course_file_id, *params)).fetchone()
    if row is None:
        raise not_found()  # outside your scope looks exactly like "does not exist"
    return row


# ---------------------------------------------------------------- create (DEAN only)
class CourseFileIn(Strict):
    subject_id: uuid.UUID
    semester_id: uuid.UUID
    faculty_id: uuid.UUID
    division: str | None = Field(default=None, max_length=40)

    @field_validator("division")
    @classmethod
    def clean_division(cls, v):
        v = (v or "").strip()
        return v or None


class CourseFileBulkIn(Strict):
    items: list[CourseFileIn] = Field(min_length=1, max_length=500)


def _create_one(db, item: CourseFileIn) -> dict:
    """Checks the three links make sense, creates the course file and ALL its checklist rows."""
    faculty = db.execute("SELECT id, role, department_id, is_active FROM users WHERE id = %s",
                         (item.faculty_id,)).fetchone()
    if faculty is None or faculty["role"] != FACULTY:
        raise HTTPException(422, "faculty_id must be an existing FACULTY user.")
    if not faculty["is_active"]:
        raise HTTPException(422, "This faculty account is switched off.")
    subject = db.execute("SELECT id, department_id, is_active FROM subjects WHERE id = %s", (item.subject_id,)).fetchone()
    if subject is None:
        raise HTTPException(422, "Unknown subject.")
    if not subject["is_active"]:
        raise HTTPException(422, "This subject is switched off.")
    if subject["department_id"] != faculty["department_id"]:
        raise HTTPException(422, "The subject and the faculty belong to different departments.")
    if db.execute("SELECT 1 FROM semesters WHERE id = %s", (item.semester_id,)).fetchone() is None:
        raise HTTPException(422, "Unknown semester.")
    try:
        row = db.execute(
            """INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id, division)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (item.subject_id, item.semester_id, item.faculty_id, faculty["department_id"], item.division),
        ).fetchone()
    except errors.UniqueViolation:
        raise HTTPException(409, "This faculty already has a course file for this subject, semester and division.")
    return {"id": row["id"], "submission_rows": create_for_course_file(db, row["id"])}


def _audit_created(db, user, created: dict, item: CourseFileIn):
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action="course_file.create",
                   entity_type="course_file", entity_id=created["id"],
                   payload={"subject_id": str(item.subject_id), "semester_id": str(item.semester_id),
                            "faculty_id": str(item.faculty_id), "division": item.division,
                            "submission_rows": created["submission_rows"]})


@router.post("", status_code=201)
def create_course_file(body: CourseFileIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    created = _create_one(db, body)
    _audit_created(db, user, created, body)
    score_store.refresh_course_files(db, [created["id"]], trigger="course_file_created", now=clock.utcnow())
    db.commit()
    scope_sql, params = course_file_filter(user)
    return db.execute(f"{_SELECT} WHERE cf.id = %s AND ({scope_sql})", (created["id"], *params)).fetchone() | {
        "submission_rows": created["submission_rows"]}


@router.post("/bulk", status_code=201)
def create_course_files_bulk(body: CourseFileBulkIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """All or nothing: if any item is wrong, nothing is created and the message names the item."""
    require_role(user, DEAN)
    out = []
    for index, item in enumerate(body.items):
        try:
            created = _create_one(db, item)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, f"Item {index + 1}: {exc.detail}")
        _audit_created(db, user, created, item)
        out.append({"id": created["id"], "submission_rows": created["submission_rows"]})
    score_store.refresh_course_files(db, [o["id"] for o in out], trigger="course_file_created", now=clock.utcnow())
    db.commit()
    return {"created": len(out), "course_files": out}


# ---------------------------------------------------------------- checklist of one course file
@router.get("/{course_file_id}/submissions")
def checklist(course_file_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    if db.execute(f"SELECT 1 FROM course_files cf WHERE cf.id = %s AND ({scope_sql})", (course_file_id, *params)).fetchone() is None:
        raise not_found()
    return db.execute(
        """
        SELECT sub.id AS submission_id, t.id AS template_id, t.code, t.title, t.sort_order,
               t.is_active AS template_active, t.allowed_extensions, t.max_size_mb,
               dl.due_at,
               (SELECT max(e.new_due_at) FROM exceptions e WHERE e.submission_id = sub.id AND e.kind = 'EXTENSION') AS extended_to,
               GREATEST(dl.due_at, (SELECT max(e.new_due_at) FROM exceptions e WHERE e.submission_id = sub.id AND e.kind = 'EXTENSION')) AS effective_due_at,
               v.id AS current_version_id, v.version_no, v.validation_status, v.uploaded_at,
               v.uploaded_by, ub.full_name AS uploaded_by_name, v.uploaded_by_role, v.on_behalf_reason,
               v.sha256, v.size_bytes, v.original_filename,
               (SELECT count(*) FROM submission_versions x WHERE x.submission_id = sub.id) AS version_count,
               COALESCE((SELECT array_agg(DISTINCT f.kind ORDER BY f.kind) FROM flags f
                          WHERE f.submission_id = sub.id AND f.status = 'OPEN'), '{}') AS open_flags
        FROM submissions sub
        JOIN course_files cf ON cf.id = sub.course_file_id
        JOIN checklist_templates t ON t.id = sub.template_id
        LEFT JOIN checklist_deadlines dl ON dl.semester_id = cf.semester_id AND dl.template_id = t.id
        LEFT JOIN submission_versions v ON v.id = sub.current_version_id
        LEFT JOIN users ub ON ub.id = v.uploaded_by
        WHERE cf.id = %s
        ORDER BY t.sort_order, t.code
        """,
        (course_file_id,),
    ).fetchall()
