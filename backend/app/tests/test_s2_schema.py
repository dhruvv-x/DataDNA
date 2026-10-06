"""
S2: the PostgreSQL schema enforces the rules itself.
Every test runs in a transaction that is rolled back, so tests never see each other's data.
"""
import hashlib
import shutil
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg import errors

from app.core import migrate as migrate_module
from app.core.migrate import MigrationError, migrate
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401  (pytest fixtures)

NOW = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)

TABLES = {
    "departments", "users", "semesters", "subjects", "course_files",
    "checklist_templates", "checklist_deadlines", "submissions", "submission_versions",
    "flags", "exceptions", "queries", "query_steps", "score_weights", "audit_log",
}


# ----------------------------------------------------------------------------
# small helpers to create rows
# ----------------------------------------------------------------------------
def q1(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def uid() -> str:
    return uuid.uuid4().hex[:8]


def sha(text: str = "x") -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def mk_dept(conn, code=None):
    code = code or "D" + uid()
    return q1(conn, "INSERT INTO departments (code, name) VALUES (%s, %s) RETURNING id",
              (code, "Dept " + code))["id"]


def mk_user(conn, dept, role="FACULTY", email=None, active=True):
    dept_id = None if role == "DEAN" else dept
    return q1(conn,
              "INSERT INTO users (email, password_hash, full_name, role, department_id, is_active) "
              "VALUES (%s, 'hash', 'Test User', %s, %s, %s) RETURNING id",
              (email or f"u{uid()}@ppsu.test", role, dept_id, active))["id"]


def mk_sem(conn, year="2025-26", term="ODD", current=False):
    return q1(conn,
              "INSERT INTO semesters (academic_year, term, start_date, end_date, is_current) "
              "VALUES (%s, %s, '2025-07-01', '2025-12-01', %s) RETURNING id",
              (year, term, current))["id"]


def mk_subject(conn, dept, code=None, stype="THEORY"):
    return q1(conn,
              "INSERT INTO subjects (code, name, department_id, subject_type) "
              "VALUES (%s, 'Subject', %s, %s) RETURNING id",
              (code or "S" + uid(), dept, stype))["id"]


def mk_course_file(conn, dept=None, division=None, faculty=None, subject=None, sem=None):
    dept = dept or mk_dept(conn)
    return q1(conn,
              "INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id, division) "
              "VALUES (%s, %s, %s, %s, %s) RETURNING id",
              (subject or mk_subject(conn, dept), sem or mk_sem(conn, year=f"20{20 + int(uid()[:2], 16) % 70}-27"),
               faculty or mk_user(conn, dept), dept, division))["id"]


def mk_template(conn, code=None):
    return q1(conn, "INSERT INTO checklist_templates (code, title) VALUES (%s, 'Item') RETURNING id",
              (code or "T" + uid(),))["id"]


def mk_submission(conn, cf=None, tpl=None):
    return q1(conn, "INSERT INTO submissions (course_file_id, template_id) VALUES (%s, %s) RETURNING id",
              (cf or mk_course_file(conn), tpl or mk_template(conn)))["id"]


def mk_version(conn, submission, user, n=1, digest=None):
    return q1(conn,
              "INSERT INTO submission_versions (submission_id, version_no, storage_key, original_filename, "
              "size_bytes, sha256, uploaded_by, uploaded_by_role) VALUES (%s, %s, 'k/' || %s, 'f.pdf', 100, %s, %s, 'FACULTY') RETURNING id",
              (submission, n, uid(), digest or sha(uid()), user))["id"]


def mk_flag(conn, cf, submission=None, kind="FORMAT", status="OPEN", **extra):
    cleared_at = NOW if status == "CLEARED" else None
    return q1(conn,
              "INSERT INTO flags (course_file_id, submission_id, kind, status, reason, cleared_at) "
              "VALUES (%s, %s, %s, %s, 'because', %s) RETURNING id",
              (cf, submission, kind, status, cleared_at))["id"]


def rejects(conn, exc, sql, params=()):
    """The statement must fail with `exc`; the failed statement is rolled back (savepoint)."""
    with pytest.raises(exc):
        with conn.transaction():
            conn.execute(sql, params)


def world(conn):
    """A department with a faculty, a course file, a submission and the ids to reuse."""
    dept = mk_dept(conn)
    faculty = mk_user(conn, dept)
    sem = mk_sem(conn)
    subj = mk_subject(conn, dept)
    cf = mk_course_file(conn, dept=dept, faculty=faculty, subject=subj, sem=sem)
    sub = mk_submission(conn, cf=cf)
    return dict(dept=dept, faculty=faculty, sem=sem, subj=subj, cf=cf, sub=sub)


# ----------------------------------------------------------------------------
# migrations
# ----------------------------------------------------------------------------
def test_all_15_tables_exist(pg):
    rows = pg.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()
    names = {r["table_name"] for r in rows}
    assert TABLES <= names


def test_migration_is_recorded(pg):
    row = q1(pg, "SELECT version, checksum FROM schema_migrations WHERE version = '0001_core'")
    assert row is not None and len(row["checksum"]) == 64


def test_running_migrate_again_applies_nothing(pg_url):
    assert migrate(pg_url) == []


def test_editing_an_applied_migration_is_detected(pg_url, tmp_path):
    # Use a temp copy of the real migrations folder, pointing at the test database whose
    # schema_migrations table already knows 0001_core.
    shutil.copytree(migrate_module.MIGRATIONS_DIR, tmp_path / "m")
    target = tmp_path / "m" / "0001_core.sql"
    target.write_text(target.read_text() + "\n-- sneaky edit\n")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        migrate(pg_url, tmp_path / "m")


def test_missing_applied_migration_file_is_detected(pg_url, tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(MigrationError, match="missing from disk"):
        migrate(pg_url, tmp_path / "empty")


def test_failed_migration_rolls_back_completely(pg_url, tmp_path):
    folder = tmp_path / "m"
    shutil.copytree(migrate_module.MIGRATIONS_DIR, folder)
    (folder / "0099_broken.sql").write_text(
        "CREATE TABLE half_made (id int);\nSELECT 1/0;\n")
    with pytest.raises(psycopg.Error):
        migrate(pg_url, folder)
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT to_regclass('public.half_made')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version='0099_broken'").fetchone()[0] == 0


def test_seed_weights_are_35_35_20_10(pg):
    row = q1(pg, "SELECT * FROM score_weights ORDER BY id LIMIT 1")
    assert (row["completeness"], row["timeliness"], row["format"], row["content"]) == (35, 35, 20, 10)


# ----------------------------------------------------------------------------
# users and departments
# ----------------------------------------------------------------------------
def test_invalid_role_rejected(pg):
    d = mk_dept(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO users (email,password_hash,full_name,role,department_id) VALUES ('a@x.com','h','n','ADMIN',%s)", (d,))


def test_dean_must_have_no_department(pg):
    d = mk_dept(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO users (email,password_hash,full_name,role,department_id) VALUES ('d@x.com','h','n','DEAN',%s)", (d,))
    assert mk_user(pg, d, role="DEAN")  # no department: allowed


def test_faculty_and_hod_must_have_department(pg):
    for role in ("FACULTY", "HOD"):
        rejects(pg, errors.CheckViolation,
                "INSERT INTO users (email,password_hash,full_name,role) VALUES (%s,'h','n',%s)", (f"{role}@x.com", role))


def test_email_must_be_lowercase(pg):
    d = mk_dept(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO users (email,password_hash,full_name,role,department_id) VALUES ('Mixed@X.com','h','n','FACULTY',%s)", (d,))


def test_duplicate_email_rejected(pg):
    d = mk_dept(pg)
    mk_user(pg, d, email="same@ppsu.test")
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO users (email,password_hash,full_name,role,department_id) VALUES ('same@ppsu.test','h','n','FACULTY',%s)", (d,))


def test_only_one_active_hod_per_department(pg):
    d1, d2 = mk_dept(pg), mk_dept(pg)
    mk_user(pg, d1, role="HOD")
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO users (email,password_hash,full_name,role,department_id) VALUES ('h2@x.com','h','n','HOD',%s)", (d1,))
    mk_user(pg, d1, role="HOD", active=False)   # an inactive old HOD is fine
    mk_user(pg, d2, role="HOD")                 # other department is fine


def test_user_with_course_file_cannot_be_deleted(pg):
    w = world(pg)
    rejects(pg, errors.ForeignKeyViolation, "DELETE FROM users WHERE id = %s", (w["faculty"],))


# ----------------------------------------------------------------------------
# semesters, subjects, course files
# ----------------------------------------------------------------------------
def test_only_one_current_semester(pg):
    mk_sem(pg, "2030-31", "ODD", current=True)
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO semesters (academic_year,term,start_date,end_date,is_current) "
            "VALUES ('2031-32','ODD','2031-07-01','2031-12-01',true)")
    mk_sem(pg, "2031-32", "EVEN", current=False)


def test_bad_academic_year_format_rejected(pg):
    rejects(pg, errors.CheckViolation,
            "INSERT INTO semesters (academic_year,term,start_date,end_date) VALUES ('2025','ODD','2025-07-01','2025-12-01')")


def test_semester_end_must_be_after_start(pg):
    rejects(pg, errors.CheckViolation,
            "INSERT INTO semesters (academic_year,term,start_date,end_date) VALUES ('2040-41','ODD','2040-12-01','2040-07-01')")


def test_duplicate_semester_rejected(pg):
    mk_sem(pg, "2032-33", "ODD")
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO semesters (academic_year,term,start_date,end_date) VALUES ('2032-33','ODD','2032-07-01','2032-12-01')")


def test_bad_subject_type_rejected(pg):
    d = mk_dept(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO subjects (code,name,department_id,subject_type) VALUES ('X1','n',%s,'OTHER')", (d,))


def test_duplicate_course_file_rejected_even_without_division(pg):
    w = world(pg)
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO course_files (subject_id,semester_id,faculty_id,department_id) VALUES (%s,%s,%s,%s)",
            (w["subj"], w["sem"], w["faculty"], w["dept"]))


def test_same_subject_different_division_allowed(pg):
    w = world(pg)
    pg.execute("INSERT INTO course_files (subject_id,semester_id,faculty_id,department_id,division) "
               "VALUES (%s,%s,%s,%s,'A')", (w["subj"], w["sem"], w["faculty"], w["dept"]))
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO course_files (subject_id,semester_id,faculty_id,department_id,division) "
            "VALUES (%s,%s,%s,%s,'A')", (w["subj"], w["sem"], w["faculty"], w["dept"]))


# ----------------------------------------------------------------------------
# checklist and submissions
# ----------------------------------------------------------------------------
def test_deadline_unique_per_semester_and_item(pg):
    sem, tpl = mk_sem(pg, "2033-34"), mk_template(pg)
    pg.execute("INSERT INTO checklist_deadlines VALUES (%s,%s,%s)", (sem, tpl, NOW))
    rejects(pg, errors.UniqueViolation, "INSERT INTO checklist_deadlines VALUES (%s,%s,%s)", (sem, tpl, NOW))


def test_one_submission_row_per_course_file_and_item(pg):
    w = world(pg)
    tpl = q1(pg, "SELECT template_id FROM submissions WHERE id=%s", (w["sub"],))["template_id"]
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO submissions (course_file_id, template_id) VALUES (%s,%s)", (w["cf"], tpl))


def test_new_submission_has_no_current_version(pg):
    w = world(pg)
    assert q1(pg, "SELECT current_version_id FROM submissions WHERE id=%s", (w["sub"],))["current_version_id"] is None


def test_current_version_can_point_to_own_version(pg):
    w = world(pg)
    v = mk_version(pg, w["sub"], w["faculty"])
    pg.execute("UPDATE submissions SET current_version_id=%s WHERE id=%s", (v, w["sub"]))


def test_current_version_of_another_submission_rejected(pg):
    w = world(pg)
    other = mk_submission(pg, cf=w["cf"])
    v_other = mk_version(pg, other, w["faculty"])
    rejects(pg, errors.ForeignKeyViolation,
            "UPDATE submissions SET current_version_id=%s WHERE id=%s", (v_other, w["sub"]))


def test_version_number_unique_per_submission(pg):
    w = world(pg)
    mk_version(pg, w["sub"], w["faculty"], n=1)
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO submission_versions (submission_id,version_no,storage_key,original_filename,size_bytes,sha256,uploaded_by,uploaded_by_role) "
            "VALUES (%s,1,'k','f',1,%s,%s,'FACULTY')", (w["sub"], sha("z"), w["faculty"]))
    mk_version(pg, w["sub"], w["faculty"], n=2)


@pytest.mark.parametrize("bad", ["abc", "G" * 64, sha("a").upper(), "a" * 63])
def test_sha256_must_be_64_lowercase_hex(pg, bad):
    w = world(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO submission_versions (submission_id,version_no,storage_key,original_filename,size_bytes,sha256,uploaded_by,uploaded_by_role) "
            "VALUES (%s,1,'k','f',1,%s,%s,'FACULTY')", (w["sub"], bad, w["faculty"]))


def test_empty_file_size_rejected(pg):
    w = world(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO submission_versions (submission_id,version_no,storage_key,original_filename,size_bytes,sha256,uploaded_by,uploaded_by_role) "
            "VALUES (%s,1,'k','f',0,%s,%s,'FACULTY')", (w["sub"], sha("q"), w["faculty"]))


def test_versions_cannot_be_updated_or_deleted(pg):
    w = world(pg)
    v = mk_version(pg, w["sub"], w["faculty"])
    rejects(pg, errors.RestrictViolation, "UPDATE submission_versions SET sha256=%s WHERE id=%s", (sha("evil"), v))
    rejects(pg, errors.RestrictViolation, "DELETE FROM submission_versions WHERE id=%s", (v,))
    assert q1(pg, "SELECT count(*) AS n FROM submission_versions WHERE id=%s", (v,))["n"] == 1


# ----------------------------------------------------------------------------
# flags
# ----------------------------------------------------------------------------
def test_late_flag_can_never_be_cleared(pg):
    w = world(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO flags (course_file_id,submission_id,kind,status,reason,cleared_at) "
            "VALUES (%s,%s,'LATE','CLEARED','late',now())", (w["cf"], w["sub"]))
    f = mk_flag(pg, w["cf"], w["sub"], kind="LATE")
    rejects(pg, errors.CheckViolation,
            "UPDATE flags SET status='CLEARED', cleared_at=now() WHERE id=%s", (f,))


def test_late_flag_can_be_waived(pg):
    w = world(pg)
    f = mk_flag(pg, w["cf"], w["sub"], kind="LATE")
    pg.execute("INSERT INTO exceptions (course_file_id, submission_id, kind, flag_id, reason, granted_by) "
               "VALUES (%s,%s,'WAIVER',%s,'approved by the dean after review',%s)", (w["cf"], w["sub"], f, w["faculty"]))
    pg.execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (f,))
    assert q1(pg, "SELECT status FROM flags WHERE id=%s", (f,))["status"] == "WAIVED"


def test_format_flag_can_be_cleared_with_a_time(pg):
    w = world(pg)
    f = mk_flag(pg, w["cf"], w["sub"], kind="FORMAT")
    rejects(pg, errors.CheckViolation, "UPDATE flags SET status='CLEARED' WHERE id=%s", (f,))
    pg.execute("UPDATE flags SET status='CLEARED', cleared_at=now() WHERE id=%s", (f,))


def test_cleared_with_reopened_duplicates_follow_open_rule(pg):
    w = world(pg)
    f1 = mk_flag(pg, w["cf"], w["sub"], kind="FORMAT")
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO flags (course_file_id,submission_id,kind,reason) VALUES (%s,%s,'FORMAT','again')",
            (w["cf"], w["sub"]))
    pg.execute("UPDATE flags SET status='CLEARED', cleared_at=now() WHERE id=%s", (f1,))
    mk_flag(pg, w["cf"], w["sub"], kind="FORMAT")  # a new one is fine once the old one is cleared


def test_mismatch_flags_can_repeat(pg):
    w = world(pg)
    mk_flag(pg, w["cf"], w["sub"], kind="MISMATCH")
    mk_flag(pg, w["cf"], w["sub"], kind="MISMATCH")


def test_unknown_flag_kind_rejected(pg):
    w = world(pg)
    rejects(pg, errors.CheckViolation,
            "INSERT INTO flags (course_file_id,kind,reason) VALUES (%s,'WEIRD','r')", (w["cf"],))


def test_flag_submission_must_belong_to_same_course_file(pg):
    w = world(pg)
    other_cf = mk_course_file(pg)
    rejects(pg, errors.ForeignKeyViolation,
            "INSERT INTO flags (course_file_id,submission_id,kind,reason) VALUES (%s,%s,'FORMAT','r')",
            (other_cf, w["sub"]))


def test_flag_version_must_belong_to_flag_submission(pg):
    w = world(pg)
    other_sub = mk_submission(pg, cf=w["cf"])
    v_other = mk_version(pg, other_sub, w["faculty"])
    rejects(pg, errors.ForeignKeyViolation,
            "INSERT INTO flags (course_file_id,submission_id,kind,reason,raised_by_version_id) "
            "VALUES (%s,%s,'FORMAT','r',%s)", (w["cf"], w["sub"], v_other))


def test_flag_version_without_submission_rejected(pg):
    w = world(pg)
    v = mk_version(pg, w["sub"], w["faculty"])
    rejects(pg, errors.CheckViolation,
            "INSERT INTO flags (course_file_id,kind,reason,raised_by_version_id) VALUES (%s,'FORMAT','r',%s)",
            (w["cf"], v))


# ----------------------------------------------------------------------------
# exceptions
# ----------------------------------------------------------------------------
def test_extension_needs_new_due_date_and_submission(pg):
    w = world(pg)
    dean = mk_user(pg, w["dept"], role="DEAN")
    rejects(pg, errors.CheckViolation,
            "INSERT INTO exceptions (course_file_id,submission_id,kind,reason,granted_by) "
            "VALUES (%s,%s,'EXTENSION','family emergency',%s)", (w["cf"], w["sub"], dean))
    pg.execute("INSERT INTO exceptions (course_file_id,submission_id,kind,new_due_at,reason,granted_by) "
               "VALUES (%s,%s,'EXTENSION',%s,'family emergency',%s)", (w["cf"], w["sub"], NOW + timedelta(days=5), dean))


def test_waiver_needs_a_flag_and_no_new_date(pg):
    w = world(pg)
    dean = mk_user(pg, w["dept"], role="DEAN")
    f = mk_flag(pg, w["cf"], w["sub"], kind="LATE")
    rejects(pg, errors.CheckViolation,
            "INSERT INTO exceptions (course_file_id,kind,reason,granted_by) "
            "VALUES (%s,'WAIVER','portal was down',%s)", (w["cf"], dean))
    rejects(pg, errors.CheckViolation,
            "INSERT INTO exceptions (course_file_id,kind,flag_id,new_due_at,reason,granted_by) "
            "VALUES (%s,'WAIVER',%s,%s,'portal was down',%s)", (w["cf"], f, NOW, dean))
    pg.execute("INSERT INTO exceptions (course_file_id,kind,flag_id,reason,granted_by) "
               "VALUES (%s,'WAIVER',%s,'portal was down',%s)", (w["cf"], f, dean))


@pytest.mark.parametrize("reason", ["", "   ", "short"])
def test_exception_reason_must_be_meaningful(pg, reason):
    w = world(pg)
    dean = mk_user(pg, w["dept"], role="DEAN")
    f = mk_flag(pg, w["cf"], w["sub"], kind="LATE")
    rejects(pg, errors.CheckViolation,
            "INSERT INTO exceptions (course_file_id,kind,flag_id,reason,granted_by) VALUES (%s,'WAIVER',%s,%s,%s)",
            (w["cf"], f, reason, dean))


# ----------------------------------------------------------------------------
# queries
# ----------------------------------------------------------------------------
def test_only_one_open_query_per_flag(pg):
    w = world(pg)
    f = mk_flag(pg, w["cf"], w["sub"], kind="FORMAT")
    pg.execute("INSERT INTO queries (flag_id, raised_by) VALUES (%s,%s)", (f, w["faculty"]))
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO queries (flag_id, raised_by) VALUES (%s,%s)", (f, w["faculty"]))


def test_resolved_query_needs_resolved_time_and_allows_a_new_one(pg):
    w = world(pg)
    f = mk_flag(pg, w["cf"], w["sub"], kind="FORMAT")
    qid = q1(pg, "INSERT INTO queries (flag_id, raised_by) VALUES (%s,%s) RETURNING id", (f, w["faculty"]))["id"]
    rejects(pg, errors.CheckViolation, "UPDATE queries SET status='RESOLVED_UPHELD' WHERE id=%s", (qid,))
    pg.execute("UPDATE queries SET status='RESOLVED_UPHELD', resolved_at=now() WHERE id=%s", (qid,))
    pg.execute("INSERT INTO queries (flag_id, raised_by) VALUES (%s,%s)", (f, w["faculty"]))


def test_query_level_and_step_action_are_checked(pg):
    w = world(pg)
    f = mk_flag(pg, w["cf"], w["sub"], kind="FORMAT")
    rejects(pg, errors.CheckViolation,
            "INSERT INTO queries (flag_id, raised_by, current_level) VALUES (%s,%s,'PRINCIPAL')", (f, w["faculty"]))
    qid = q1(pg, "INSERT INTO queries (flag_id, raised_by) VALUES (%s,%s) RETURNING id", (f, w["faculty"]))["id"]
    rejects(pg, errors.CheckViolation,
            "INSERT INTO query_steps (query_id, actor_id, action, message) VALUES (%s,%s,'SHOUT','hi')", (qid, w["faculty"]))
    pg.execute("INSERT INTO query_steps (query_id, actor_id, action, message) VALUES (%s,%s,'RAISE','please check')",
               (qid, w["faculty"]))


# ----------------------------------------------------------------------------
# score weights and audit log
# ----------------------------------------------------------------------------
def test_weights_must_sum_to_100(pg):
    rejects(pg, errors.CheckViolation,
            "INSERT INTO score_weights (completeness,timeliness,format,content,reason) VALUES (40,35,20,10,'bad')")
    pg.execute("INSERT INTO score_weights (completeness,timeliness,format,content,reason) VALUES (40,30,20,10,'after audit')")


def test_weights_are_append_only_and_latest_row_is_current(pg):
    pg.execute("INSERT INTO score_weights (completeness,timeliness,format,content,reason) VALUES (40,30,20,10,'after audit')")
    latest = q1(pg, "SELECT completeness FROM score_weights ORDER BY id DESC LIMIT 1")
    assert latest["completeness"] == 40
    rejects(pg, errors.RestrictViolation, "UPDATE score_weights SET completeness=50")
    rejects(pg, errors.RestrictViolation, "DELETE FROM score_weights")


def test_audit_log_accepts_inserts_but_never_changes(pg):
    pg.execute("INSERT INTO audit_log (action, entity_type, entity_id, payload) "
               "VALUES ('UPLOAD','submission','abc','{\"k\": 1}')")
    rejects(pg, errors.RestrictViolation, "UPDATE audit_log SET action='HIDDEN'")
    rejects(pg, errors.RestrictViolation, "DELETE FROM audit_log")
    assert q1(pg, "SELECT count(*) AS n FROM audit_log")["n"] == 1


def test_audit_log_ids_increase(pg):
    pg.execute("INSERT INTO audit_log (action, entity_type) VALUES ('A','x')")
    pg.execute("INSERT INTO audit_log (action, entity_type) VALUES ('B','x')")
    ids = [r["id"] for r in pg.execute("SELECT id FROM audit_log ORDER BY id").fetchall()]
    assert ids == sorted(ids) and len(set(ids)) == 2
