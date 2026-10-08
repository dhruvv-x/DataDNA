"""Adds 1 HOD + 1 FACULTY (new EE department) to an already-seeded demo DB. Safe to re-run."""
import os
import sys

import psycopg

from app.core import clock, rules, score_store, security
from app.core.pg import connect
from app.core.seed_demo import EMAIL_DOMAIN, _audit
from app.core.submission_rows import create_for_course_file

DEPT = ("EE", "Electrical Engineering")
SUBJECT = ("EE101", "Basic Electrical Engineering", "THEORY")
HOD = ("hod.ee", "Dr. Anil Trivedi")
FACULTY = ("rohan.patel", "Rohan Patel")


def add_users(conn):
    if os.environ.get("APP_ENV", "").strip().lower() == "production":
        raise RuntimeError("Refusing to run when APP_ENV=production.")
    sem = conn.execute("SELECT id FROM semesters WHERE is_current").fetchone()
    if not sem:
        raise RuntimeError("No current semester. Run seed_demo first.")
    sem = sem["id"]

    row = conn.execute("SELECT id FROM departments WHERE code = %s", (DEPT[0],)).fetchone()
    if row:
        dept = row["id"]
    else:
        dept = conn.execute("INSERT INTO departments (code, name) VALUES (%s, %s) RETURNING id", DEPT).fetchone()["id"]
        _audit(conn, "department.create", "department", dept, {"code": DEPT[0]})

    row = conn.execute("SELECT id FROM subjects WHERE code = %s", (SUBJECT[0],)).fetchone()
    if row:
        subject = row["id"]
    else:
        subject = conn.execute(
            "INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s, %s, %s, %s) RETURNING id",
            (SUBJECT[0], SUBJECT[1], dept, SUBJECT[2])).fetchone()["id"]
        _audit(conn, "subject.create", "subject", subject, {"code": SUBJECT[0]})

    logins = []

    def user(local, name, role):
        email = f"{local}@{EMAIL_DOMAIN}"
        row = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if row:
            return row["id"]
        password = security.generate_temporary_password()
        uid = conn.execute(
            """INSERT INTO users (email, password_hash, full_name, role, department_id, must_change_password)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING id""",
            (email, security.hash_password(password), name, role, dept)).fetchone()["id"]
        _audit(conn, "USER_CREATED", "user", uid, {"role": role})
        logins.append((email, password, role))
        return uid

    user(HOD[0], HOD[1], "HOD")
    fid = user(FACULTY[0], FACULTY[1], "FACULTY")

    cf = conn.execute(
        "SELECT id FROM course_files WHERE subject_id = %s AND semester_id = %s AND faculty_id = %s",
        (subject, sem, fid)).fetchone()
    if not cf:
        cf = conn.execute(
            "INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (subject, sem, fid, dept)).fetchone()["id"]
        rows = create_for_course_file(conn, cf)
        _audit(conn, "course_file.create", "course_file", cf, {"subject": SUBJECT[0], "submission_rows": rows})
        now = clock.utcnow()
        rules.evaluate_many(conn, rules.submissions_of(conn, sem), now=now, trigger="semester_open", refresh_scores=False)
        score_store.refresh_semester(conn, sem, trigger="semester_open", now=now)
    return logins


def main() -> int:
    try:
        conn = connect()
    except psycopg.Error as exc:
        print(f"ERROR: cannot reach PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        logins = add_users(conn)
        conn.commit()
    except (RuntimeError, psycopg.Error) as exc:
        conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    if not logins:
        print("Nothing new to add, users already exist.")
    else:
        print("\nNew logins (note the passwords now, they are not shown again):")
        for email, password, role in logins:
            print(f"  {role:8} {email:34} {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
