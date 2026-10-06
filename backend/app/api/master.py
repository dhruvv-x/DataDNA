"""
Master data (S4): departments, semesters, subjects, checklist templates, deadlines.
Anyone logged in may READ (limited by scope.py). Only the DEAN may change anything.
Nothing is ever hard-deleted; things are switched off with is_active.
"""
import re
import uuid
from contextlib import contextmanager
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg import errors
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.deps import current_user, get_db
from app.core import auditlog
from app.core.filecheck import SUPPORTED_EXTENSIONS
from app.core.scope import DEAN, CurrentUser, department_filter, not_found, require_role, subject_filter
from app.core.submission_rows import backfill_submissions

router = APIRouter(tags=["master-data"])

_NAME = Field(min_length=1, max_length=120)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelt or forbidden field is an error, not silently ignored


@contextmanager
def db_rules():
    """Turn database rule violations into clear 4xx answers instead of a 500."""
    try:
        yield
    except errors.UniqueViolation:
        raise HTTPException(409, "This already exists.")
    except errors.CheckViolation:
        raise HTTPException(422, "A value is not allowed (check dates, sizes and lengths).")
    except errors.ForeignKeyViolation:
        raise HTTPException(409, "A referenced record does not exist, or is still in use.")


def _stripped(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


def _audit(db, user, action, entity_type, entity_id, payload=None):
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action=action,
                   entity_type=entity_type, entity_id=entity_id, payload=payload or {})


# ============================================================ departments
class DepartmentIn(Strict):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,20}$")
    name: str = _NAME
    v_n = field_validator("name")(_stripped)


class DepartmentPatch(Strict):
    name: str = _NAME
    v_n = field_validator("name")(_stripped)


@router.post("/departments", status_code=201)
def create_department(body: DepartmentIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    with db_rules():
        row = db.execute("INSERT INTO departments (code, name) VALUES (%s, %s) RETURNING *",
                         (body.code.upper(), body.name)).fetchone()
    _audit(db, user, "department.create", "department", row["id"], {"code": row["code"], "name": row["name"]})
    db.commit()
    return row


@router.get("/departments")
def list_departments(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    where, params = department_filter(user)
    return db.execute(f"SELECT d.* FROM departments d WHERE {where} ORDER BY d.code", params).fetchall()


@router.patch("/departments/{department_id}")
def rename_department(department_id: uuid.UUID, body: DepartmentPatch,
                      user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    old = db.execute("SELECT * FROM departments WHERE id = %s FOR UPDATE", (department_id,)).fetchone()
    if old is None:
        raise not_found()
    with db_rules():
        row = db.execute("UPDATE departments SET name = %s WHERE id = %s RETURNING *",
                         (body.name, department_id)).fetchone()
    _audit(db, user, "department.update", "department", department_id, {"old_name": old["name"], "new_name": body.name})
    db.commit()
    return row


# ============================================================ semesters
class SemesterIn(Strict):
    academic_year: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    term: Literal["ODD", "EVEN"]
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def v_check(self):
        first, second = int(self.academic_year[:4]), int(self.academic_year[5:])
        if (first + 1) % 100 != second:
            raise ValueError("academic_year must look like 2026-27")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class SemesterDates(Strict):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def v_check(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


@router.post("/semesters", status_code=201)
def create_semester(body: SemesterIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    with db_rules():
        row = db.execute(
            "INSERT INTO semesters (academic_year, term, start_date, end_date) VALUES (%s, %s, %s, %s) RETURNING *",
            (body.academic_year, body.term, body.start_date, body.end_date)).fetchone()
    _audit(db, user, "semester.create", "semester", row["id"], {"academic_year": row["academic_year"], "term": row["term"]})
    db.commit()
    return row


@router.get("/semesters")
def list_semesters(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    return db.execute("SELECT * FROM semesters ORDER BY start_date DESC").fetchall()


@router.patch("/semesters/{semester_id}")
def change_semester_dates(semester_id: uuid.UUID, body: SemesterDates,
                          user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    old = db.execute("SELECT * FROM semesters WHERE id = %s FOR UPDATE", (semester_id,)).fetchone()
    if old is None:
        raise not_found()
    with db_rules():
        row = db.execute("UPDATE semesters SET start_date = %s, end_date = %s WHERE id = %s RETURNING *",
                         (body.start_date, body.end_date, semester_id)).fetchone()
    _audit(db, user, "semester.update", "semester", semester_id,
           {"old": [str(old["start_date"]), str(old["end_date"])], "new": [str(body.start_date), str(body.end_date)]})
    db.commit()
    return row


@router.post("/semesters/{semester_id}/make-current")
def make_current(semester_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """Exactly one semester is current. Older ones become history (no score drag, no faculty uploads)."""
    require_role(user, DEAN)
    target = db.execute("SELECT * FROM semesters WHERE id = %s FOR UPDATE", (semester_id,)).fetchone()
    if target is None:
        raise not_found()
    previous = db.execute("SELECT id FROM semesters WHERE is_current").fetchone()
    with db_rules():
        db.execute("UPDATE semesters SET is_current = false WHERE is_current")
        row = db.execute("UPDATE semesters SET is_current = true WHERE id = %s RETURNING *", (semester_id,)).fetchone()
    _audit(db, user, "semester.make_current", "semester", semester_id,
           {"previous_current": str(previous["id"]) if previous else None})
    db.commit()
    return row


# ============================================================ subjects
class SubjectIn(Strict):
    code: str = Field(min_length=1, max_length=30)
    name: str = _NAME
    department_id: uuid.UUID
    subject_type: Literal["THEORY", "LAB", "THEORY_LAB"]
    v_c = field_validator("code")(_stripped)
    v_n = field_validator("name")(_stripped)


class SubjectPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    subject_type: Literal["THEORY", "LAB", "THEORY_LAB"] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def v_n(cls, v):
        return None if v is None else _stripped(v)


@router.post("/subjects", status_code=201)
def create_subject(body: SubjectIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    with db_rules():
        row = db.execute(
            "INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s, %s, %s, %s) RETURNING *",
            (body.code.upper(), body.name, body.department_id, body.subject_type)).fetchone()
    _audit(db, user, "subject.create", "subject", row["id"], {"code": row["code"], "department_id": str(row["department_id"])})
    db.commit()
    return row


@router.get("/subjects")
def list_subjects(department_id: uuid.UUID | None = None, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    where, params = subject_filter(user)
    args = list(params)
    clause = f"({where})"
    if department_id is not None:
        clause += " AND s.department_id = %s"
        args.append(department_id)
    return db.execute(f"SELECT s.* FROM subjects s WHERE {clause} ORDER BY s.code", args).fetchall()


@router.patch("/subjects/{subject_id}")
def update_subject(subject_id: uuid.UUID, body: SubjectPatch,
                   user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    old = db.execute("SELECT * FROM subjects WHERE id = %s FOR UPDATE", (subject_id,)).fetchone()
    if old is None:
        raise not_found()
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "Nothing to change.")
    if "subject_type" in changes and changes["subject_type"] != old["subject_type"]:
        used = db.execute("SELECT 1 FROM course_files WHERE subject_id = %s LIMIT 1", (subject_id,)).fetchone()
        if used:
            raise HTTPException(409, "The subject type cannot change once course files exist for it.")
    sets = ", ".join(f"{k} = %s" for k in changes)
    with db_rules():
        row = db.execute(f"UPDATE subjects SET {sets} WHERE id = %s RETURNING *", (*changes.values(), subject_id)).fetchone()
    _audit(db, user, "subject.update", "subject", subject_id,
           {"old": {k: old[k] for k in changes}, "new": changes})
    db.commit()
    return row


# ============================================================ checklist templates
def _clean_extensions(values: list[str]) -> list[str]:
    out = []
    for v in values:
        ext = v.strip().lower().lstrip(".")
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"'{v}' is not a supported file type. Supported: {', '.join(SUPPORTED_EXTENSIONS)}")
        if ext not in out:
            out.append(ext)
    if not out:
        raise ValueError("at least one allowed file type is required")
    return out


class TemplateIn(Strict):
    code: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,40}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    applies_to: Literal["THEORY", "LAB", "BOTH"] = "BOTH"
    allowed_extensions: list[str] = Field(min_length=1, max_length=12)
    max_size_mb: int = Field(default=10, ge=1, le=500)
    sort_order: int = Field(default=0, ge=0, le=10000)
    v_t = field_validator("title")(_stripped)
    v_e = field_validator("allowed_extensions")(_clean_extensions)


class TemplatePatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    allowed_extensions: list[str] | None = Field(default=None, min_length=1, max_length=12)
    max_size_mb: int | None = Field(default=None, ge=1, le=500)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def v_t(cls, v):
        return None if v is None else _stripped(v)

    @field_validator("allowed_extensions")
    @classmethod
    def v_e(cls, v):
        return None if v is None else _clean_extensions(v)


@router.post("/checklist-templates", status_code=201)
def create_template(body: TemplateIn, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    with db_rules():
        row = db.execute(
            """INSERT INTO checklist_templates
                 (code, title, description, applies_to, allowed_extensions, max_size_mb, sort_order)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (body.code.upper(), body.title, body.description, body.applies_to,
             body.allowed_extensions, body.max_size_mb, body.sort_order)).fetchone()
    created = backfill_submissions(db, template_id=row["id"])
    _audit(db, user, "template.create", "checklist_template", row["id"],
           {"code": row["code"], "applies_to": row["applies_to"], "submission_rows_added": created})
    db.commit()
    return {**row, "submission_rows_added": created}


@router.get("/checklist-templates")
def list_templates(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    return db.execute("SELECT * FROM checklist_templates ORDER BY sort_order, code").fetchall()


@router.patch("/checklist-templates/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplatePatch,
                    user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    require_role(user, DEAN)
    old = db.execute("SELECT * FROM checklist_templates WHERE id = %s FOR UPDATE", (template_id,)).fetchone()
    if old is None:
        raise not_found()
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "Nothing to change.")
    sets = ", ".join(f"{k} = %s" for k in changes)
    with db_rules():
        row = db.execute(f"UPDATE checklist_templates SET {sets} WHERE id = %s RETURNING *",
                         (*changes.values(), template_id)).fetchone()
    added = backfill_submissions(db, template_id=template_id) if changes.get("is_active") else 0
    _audit(db, user, "template.update", "checklist_template", template_id,
           {"old": {k: old[k] for k in changes}, "new": changes, "submission_rows_added": added})
    db.commit()
    return {**row, "submission_rows_added": added}


# ============================================================ deadlines
class DeadlineItem(Strict):
    template_id: uuid.UUID
    due_at: AwareDatetime  # must carry a time zone, e.g. 2026-09-30T17:00:00+05:30


class DeadlinesIn(Strict):
    items: list[DeadlineItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def v_unique(self):
        ids = [i.template_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("the same template appears twice")
        return self


@router.put("/semesters/{semester_id}/deadlines")
def set_deadlines(semester_id: uuid.UUID, body: DeadlinesIn,
                  user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    """All-or-nothing. A moved deadline never erases a lateness flag that already exists (waiver needed, S5)."""
    require_role(user, DEAN)
    if db.execute("SELECT 1 FROM semesters WHERE id = %s", (semester_id,)).fetchone() is None:
        raise not_found()
    changes = []
    with db_rules():
        for item in body.items:
            if db.execute("SELECT 1 FROM checklist_templates WHERE id = %s", (item.template_id,)).fetchone() is None:
                raise HTTPException(422, f"Unknown checklist template {item.template_id}.")
            old = db.execute("SELECT due_at FROM checklist_deadlines WHERE semester_id = %s AND template_id = %s",
                             (semester_id, item.template_id)).fetchone()
            db.execute(
                """INSERT INTO checklist_deadlines (semester_id, template_id, due_at) VALUES (%s, %s, %s)
                   ON CONFLICT (semester_id, template_id) DO UPDATE SET due_at = EXCLUDED.due_at""",
                (semester_id, item.template_id, item.due_at))
            changes.append({"template_id": str(item.template_id),
                            "old": old["due_at"].isoformat() if old else None, "new": item.due_at.isoformat()})
    _audit(db, user, "deadlines.set", "semester", semester_id, {"changes": changes})
    db.commit()
    return get_deadlines(semester_id, user, db)


@router.get("/semesters/{semester_id}/deadlines")
def get_deadlines(semester_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    if db.execute("SELECT 1 FROM semesters WHERE id = %s", (semester_id,)).fetchone() is None:
        raise not_found()
    return db.execute(
        """SELECT dl.semester_id, dl.template_id, t.code AS template_code, t.title, dl.due_at
           FROM checklist_deadlines dl JOIN checklist_templates t ON t.id = dl.template_id
           WHERE dl.semester_id = %s ORDER BY t.sort_order, t.code""", (semester_id,)).fetchall()
