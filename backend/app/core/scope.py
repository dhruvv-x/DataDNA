"""
Who may see and change what (S3). This is the ONLY place scope rules live.
Every endpoint from S4 onward must use these helpers instead of writing its own check.

Rules
  FACULTY  sees course files where course_files.faculty_id = their own id
  HOD      sees course files where course_files.department_id = their department
  DEAN     sees everything

Answer codes
  Not allowed to SEE the thing at all  -> 404 (we do not even confirm it exists)
  Can see it but not allowed the action -> 403
"""
import uuid
from dataclasses import dataclass

from fastapi import HTTPException

FACULTY = "FACULTY"
HOD = "HOD"
DEAN = "DEAN"


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    department_id: uuid.UUID | None
    must_change_password: bool = False


def forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="You do not have permission to do this.")


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def require_role(user: CurrentUser, *roles: str) -> None:
    if user.role not in roles:
        raise forbidden()


def course_file_filter(user: CurrentUser, alias: str = "cf") -> tuple[str, tuple]:
    """SQL fragment (with %s placeholders) limiting course_files rows to what this user may see."""
    if user.role == DEAN:
        return "TRUE", ()
    if user.role == HOD:
        return f"{alias}.department_id = %s", (user.department_id,)
    if user.role == FACULTY:
        return f"{alias}.faculty_id = %s", (user.id,)
    return "FALSE", ()


def user_filter(user: CurrentUser, alias: str = "u") -> tuple[str, tuple]:
    """SQL fragment limiting users rows to what this user may see."""
    if user.role == DEAN:
        return "TRUE", ()
    if user.role == HOD:
        return f"{alias}.department_id = %s", (user.department_id,)
    if user.role == FACULTY:
        return f"{alias}.id = %s", (user.id,)
    return "FALSE", ()


def can_create_user(actor: CurrentUser, role: str, department_id: uuid.UUID) -> bool:
    """Nobody creates a DEAN through the API. Dean creates HOD/FACULTY anywhere. HOD creates FACULTY in own department."""
    if role not in (HOD, FACULTY):
        return False
    if actor.role == DEAN:
        return True
    if actor.role == HOD:
        return role == FACULTY and department_id == actor.department_id
    return False


def can_manage_user(actor: CurrentUser, target: dict) -> bool:
    """Deactivate, reactivate, reset password. Call only for a target the actor can already see."""
    if actor.role == DEAN:
        return True
    if actor.role == HOD:
        return target["role"] == FACULTY and target["department_id"] == actor.department_id
    return False


def department_filter(user: CurrentUser, alias: str = "d") -> tuple[str, tuple]:
    """Departments: DEAN sees all, HOD and FACULTY only their own."""
    if user.role == DEAN:
        return "TRUE", ()
    if user.role in (HOD, FACULTY):
        return f"{alias}.id = %s", (user.department_id,)
    return "FALSE", ()


def subject_filter(user: CurrentUser, alias: str = "s") -> tuple[str, tuple]:
    """Subjects: DEAN sees all, HOD and FACULTY only their own department's."""
    if user.role == DEAN:
        return "TRUE", ()
    if user.role in (HOD, FACULTY):
        return f"{alias}.department_id = %s", (user.department_id,)
    return "FALSE", ()


def can_upload(user: CurrentUser) -> bool:
    """Only the owner (FACULTY) and the DEAN upload. HOD only views. Visibility is checked first, separately."""
    return user.role in (FACULTY, DEAN)
