"""S8: the permission table of a query as a pure function (no database). One rule per test."""
import uuid
from datetime import datetime, timedelta, timezone

from app.api.queries import APPEAL_DAYS, abilities, appeal_open
from app.core.scope import CurrentUser

NOW = datetime(2099, 10, 1, 12, 0, tzinfo=timezone.utc)
DEPT, OTHER = uuid.uuid4(), uuid.uuid4()


def person(role, dept=DEPT):
    return CurrentUser(id=uuid.uuid4(), email=f"{role}@x.edu", full_name=role, role=role, department_id=dept)


def query(author, level="HOD", status="OPEN", resolved_level=None, appealed=False, resolved_at=None):
    return {"raised_by": author.id, "current_level": level, "status": status, "department_id": DEPT,
            "resolved_level": resolved_level, "appealed": appealed, "resolved_at": resolved_at}


def test_nobody_decides_their_own_query_even_if_the_level_would_allow_it():
    hod = person("HOD")
    assert abilities(hod, query(hod, level="HOD"), NOW)["resolve"] is False       # level HOD, but it is theirs
    assert abilities(hod, query(hod, level="HOD"), NOW)["escalate"] is False
    dean = person("DEAN", None)
    assert abilities(dean, query(dean, level="DEAN"), NOW)["resolve"] is False


def test_hod_of_the_same_department_decides_at_the_hod_level_only():
    fac, hod = person("FACULTY"), person("HOD")
    assert abilities(hod, query(fac, "HOD"), NOW) == {
        "reply": True, "escalate": True, "resolve": True, "appeal": False, "override": False}
    assert abilities(hod, query(fac, "DEAN"), NOW) == {
        "reply": False, "escalate": False, "resolve": False, "appeal": False, "override": False}


def test_hod_of_another_department_can_do_nothing():
    fac, stranger = person("FACULTY"), person("HOD", OTHER)
    assert not any(abilities(stranger, query(fac, "HOD"), NOW).values())


def test_dean_decides_at_both_levels_and_override_only_at_the_hod_level():
    fac, dean = person("FACULTY"), person("DEAN", None)
    assert abilities(dean, query(fac, "HOD"), NOW)["override"] is True
    assert abilities(dean, query(fac, "DEAN"), NOW)["override"] is False
    assert abilities(dean, query(fac, "DEAN"), NOW)["resolve"] is True
    assert abilities(dean, query(fac, "HOD"), NOW)["escalate"] is False


def test_the_author_can_only_reply_while_open_and_nothing_once_decided():
    fac = person("FACULTY")
    assert abilities(fac, query(fac), NOW) == {
        "reply": True, "escalate": False, "resolve": False, "appeal": False, "override": False}
    assert not any(abilities(fac, query(fac, status="RESOLVED_OVERTURNED", resolved_level="HOD",
                                        resolved_at=NOW), NOW).values())


def test_a_decided_query_gives_nobody_anything_but_the_author_one_appeal():
    fac, hod, dean = person("FACULTY"), person("HOD"), person("DEAN", None)
    q = query(fac, status="RESOLVED_UPHELD", resolved_level="HOD", resolved_at=NOW - timedelta(days=1))
    assert abilities(fac, q, NOW)["appeal"] is True
    assert not any(abilities(hod, q, NOW).values()) and not any(abilities(dean, q, NOW).values())


def test_appeal_rules():
    base = dict(status="RESOLVED_UPHELD", resolved_level="HOD", appealed=False, resolved_at=NOW)
    assert appeal_open(base, NOW) is True
    assert appeal_open(base, NOW + timedelta(days=APPEAL_DAYS)) is True                # last moment
    assert appeal_open(base, NOW + timedelta(days=APPEAL_DAYS, seconds=1)) is False    # one second late
    assert appeal_open({**base, "appealed": True}, NOW) is False                       # only once
    assert appeal_open({**base, "resolved_level": "DEAN"}, NOW) is False               # Dean is final
    assert appeal_open({**base, "status": "RESOLVED_OVERTURNED"}, NOW) is False        # already won
    assert appeal_open({**base, "status": "OPEN"}, NOW) is False
