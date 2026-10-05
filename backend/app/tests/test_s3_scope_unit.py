"""S3: the scope helpers on their own (no database, no HTTP)."""
import uuid

import pytest
from fastapi import HTTPException

from app.core import scope
from app.core.scope import CurrentUser

DEP_X, DEP_Y = uuid.uuid4(), uuid.uuid4()


def user(role, dep=None):
    return CurrentUser(id=uuid.uuid4(), email=f"{role}@x.edu", full_name=role, role=role, department_id=dep)


FAC, HOD, DEAN = user("FACULTY", DEP_X), user("HOD", DEP_X), user("DEAN")


def test_course_file_filter_per_role():
    assert scope.course_file_filter(DEAN) == ("TRUE", ())
    assert scope.course_file_filter(HOD) == ("cf.department_id = %s", (DEP_X,))
    assert scope.course_file_filter(FAC) == ("cf.faculty_id = %s", (FAC.id,))


def test_course_file_filter_uses_given_alias():
    assert scope.course_file_filter(FAC, "c")[0] == "c.faculty_id = %s"


def test_unknown_role_sees_nothing():
    assert scope.course_file_filter(user("ADMIN"))[0] == "FALSE"
    assert scope.user_filter(user("ADMIN"))[0] == "FALSE"


def test_user_filter_per_role():
    assert scope.user_filter(DEAN) == ("TRUE", ())
    assert scope.user_filter(HOD) == ("u.department_id = %s", (DEP_X,))
    assert scope.user_filter(FAC) == ("u.id = %s", (FAC.id,))


@pytest.mark.parametrize("actor,role,dep,allowed", [
    (DEAN, "HOD", DEP_X, True),
    (DEAN, "FACULTY", DEP_Y, True),
    (DEAN, "DEAN", DEP_X, False),
    (HOD, "FACULTY", DEP_X, True),
    (HOD, "FACULTY", DEP_Y, False),
    (HOD, "HOD", DEP_X, False),
    (HOD, "DEAN", DEP_X, False),
    (FAC, "FACULTY", DEP_X, False),
    (FAC, "HOD", DEP_X, False),
])
def test_can_create_user_matrix(actor, role, dep, allowed):
    assert scope.can_create_user(actor, role, dep) is allowed


@pytest.mark.parametrize("actor,target_role,target_dep,allowed", [
    (DEAN, "FACULTY", DEP_Y, True),
    (DEAN, "HOD", DEP_Y, True),
    (HOD, "FACULTY", DEP_X, True),
    (HOD, "FACULTY", DEP_Y, False),
    (HOD, "HOD", DEP_X, False),
    (HOD, "DEAN", None, False),
    (FAC, "FACULTY", DEP_X, False),
])
def test_can_manage_user_matrix(actor, target_role, target_dep, allowed):
    assert scope.can_manage_user(actor, {"role": target_role, "department_id": target_dep}) is allowed


def test_require_role_passes_and_blocks():
    scope.require_role(DEAN, "DEAN", "HOD")
    with pytest.raises(HTTPException) as exc:
        scope.require_role(FAC, "DEAN", "HOD")
    assert exc.value.status_code == 403


def test_not_found_and_forbidden_codes():
    assert scope.not_found().status_code == 404
    assert scope.forbidden().status_code == 403
