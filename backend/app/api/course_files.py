"""Read-only course file endpoints, scoped by role (S3). Uploads come in S4."""
import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import current_user, get_db
from app.core.scope import CurrentUser, course_file_filter, not_found

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
