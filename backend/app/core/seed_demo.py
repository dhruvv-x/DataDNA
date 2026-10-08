"""
Demo data for a fresh database (S7b). Fills the dashboards so you can click through every screen.

Run:   cd ~/datadna/backend && source venv/bin/activate
       python -m app.core.seed_demo

What it makes: 2 departments (IT, CS), the current semester, 8 subjects, 19 PLACEHOLDER checklist items
(the real PPSU list is still open), deadlines (a few already passed, so you see MISSING flags), 2 HODs,
4 faculty and 8 course files. It prints the login emails and passwords ONCE. The demo users do not have
to change their password (it is demo data).

Safety: refuses when APP_ENV=production, refuses when the demo departments already exist, and never
touches existing rows. Everything it creates is written to the audit log by the system, not by a person.
"""
import os
import sys
from datetime import date, datetime, time, timedelta, timezone

import psycopg

from app.core import auditlog, clock, rules, score_store, security
from app.core.pg import connect
from app.core.submission_rows import create_for_course_file

IST = timezone(timedelta(hours=5, minutes=30))
EMAIL_DOMAIN = "demo.ppsu.example"
DEPARTMENTS = [("IT", "Information Technology"), ("CS", "Computer Science")]

# (code, name, department, type)
SUBJECTS = [
    ("IT101", "Data Structures", "IT", "THEORY"),
    ("IT102", "Database Systems", "IT", "THEORY_LAB"),
    ("IT103", "Web Programming Lab", "IT", "LAB"),
    ("IT104", "Computer Networks", "IT", "THEORY"),
    ("CS101", "Operating Systems", "CS", "THEORY"),
    ("CS102", "Algorithms", "CS", "THEORY"),
    ("CS103", "Programming Lab", "CS", "LAB"),
    ("CS104", "Machine Learning", "CS", "THEORY_LAB"),
]

# (code, title, applies_to, extensions, max_mb). PLACEHOLDERS: replace with the real list from IQAC.
TEMPLATES = [
    ("D01", "Course syllabus", "BOTH", ["pdf", "docx"], 10),
    ("D02", "Course outcomes (COs)", "BOTH", ["pdf", "docx"], 10),
    ("D03", "Teaching plan", "BOTH", ["pdf", "docx", "xlsx"], 10),
    ("D04", "Time table", "BOTH", ["pdf", "xlsx"], 5),
    ("D05", "Student list", "BOTH", ["xlsx", "csv"], 5),
    ("D06", "Lecture notes", "THEORY", ["pdf", "pptx"], 50),
    ("D07", "Lab manual", "LAB", ["pdf", "docx"], 20),
    ("D08", "Assignment 1", "BOTH", ["pdf", "docx"], 10),
    ("D09", "Assignment 2", "BOTH", ["pdf", "docx"], 10),
    ("D10", "Internal test 1 paper", "BOTH", ["pdf", "docx"], 10),
    ("D11", "Internal test 1 marks", "BOTH", ["xlsx", "csv"], 5),
    ("D12", "Internal test 2 paper", "BOTH", ["pdf", "docx"], 10),
    ("D13", "Internal test 2 marks", "BOTH", ["xlsx", "csv"], 5),
    ("D14", "Attendance record", "BOTH", ["xlsx", "pdf"], 10),
    ("D15", "Sample answer sheets", "THEORY", ["pdf"], 50),
    ("D16", "Lab journal samples", "LAB", ["pdf"], 50),
    ("D17", "Course feedback summary", "BOTH", ["pdf", "xlsx"], 10),
    ("D18", "Result analysis", "BOTH", ["pdf", "xlsx"], 10),
    ("D19", "CO attainment sheet", "BOTH", ["xlsx"], 5),
]

# days from today for each template's deadline: first three already passed, so flags show up at once
DEADLINE_DAYS = [-40, -30, -20, 3, 7, 10, 14, 20, 25, 30, 35, 45, 50, 55, 60, 70, 80, 90, 100]

HODS = [("hod.it", "Dr. Meera Joshi", "IT"), ("hod.cs", "Dr. Rakesh Patel", "CS")]
FACULTY = [
    ("asha.shah", "Asha Shah", "IT", ["IT101", "IT102"]),
    ("kiran.desai", "Kiran Desai", "IT", ["IT103", "IT104"]),
    ("nisha.mehta", "Nisha Mehta", "CS", ["CS101", "CS102"]),
    ("vivek.rana", "Vivek Rana", "CS", ["CS103", "CS104"]),
]


class DemoError(Exception):
    pass


def semester_dates(today: date) -> tuple[str, date, date]:
    year = today.year if today.month >= 7 else today.year - 1
    return f"{year}-{(year + 1) % 100:02d}", date(year, 7, 1), date(year + 1, 1, 15)


def _audit(conn, action, entity_type, entity_id, payload=None):
    auditlog.write(conn, actor_id=None, actor_role="SYSTEM", action=action, entity_type=entity_type,
                   entity_id=entity_id, payload={"via": "seed_demo", **(payload or {})})


def seed_demo(conn, *, now: datetime | None = None) -> dict:
    """Creates the demo data. The caller commits. Returns {"logins": [(email, password, role)], ...}."""
    if os.environ.get("APP_ENV", "").strip().lower() == "production":
        raise DemoError("seed_demo refuses to run when APP_ENV=production.")
    now = now or clock.utcnow()
    codes = [c for c, _ in DEPARTMENTS]
    if conn.execute("SELECT 1 FROM departments WHERE code = ANY(%s)", (codes,)).fetchone():
        raise DemoError("Departments IT or CS already exist, so this database already has data. Nothing was changed.")
    if conn.execute("SELECT 1 FROM semesters WHERE is_current").fetchone():
        raise DemoError("A current semester already exists. Nothing was changed.")

    dept = {}
    for code, name in DEPARTMENTS:
        row = conn.execute("INSERT INTO departments (code, name) VALUES (%s, %s) RETURNING id", (code, name)).fetchone()
        dept[code] = row["id"]
        _audit(conn, "department.create", "department", row["id"], {"code": code})

    year, start, end = semester_dates(now.astimezone(IST).date())
    sem = conn.execute(
        "INSERT INTO semesters (academic_year, term, start_date, end_date) VALUES (%s, 'ODD', %s, %s) RETURNING id",
        (year, start, end)).fetchone()["id"]
    _audit(conn, "semester.create", "semester", sem, {"academic_year": year, "term": "ODD"})

    subject = {}
    for code, name, dep, kind in SUBJECTS:
        row = conn.execute(
            "INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s, %s, %s, %s) RETURNING id",
            (code, name, dept[dep], kind)).fetchone()
        subject[code] = row["id"]
        _audit(conn, "subject.create", "subject", row["id"], {"code": code})

    template = []
    for order, (code, title, applies, exts, mb) in enumerate(TEMPLATES, start=1):
        row = conn.execute(
            """INSERT INTO checklist_templates (code, title, description, applies_to, allowed_extensions, max_size_mb, sort_order)
               VALUES (%s, %s, 'Demo item. Replace with the real list.', %s, %s, %s, %s) RETURNING id""",
            (code, title, applies, exts, mb, order)).fetchone()
        template.append(row["id"])
        _audit(conn, "template.create", "checklist_template", row["id"], {"code": code})

    today_ist = now.astimezone(IST).date()
    for tid, days in zip(template, DEADLINE_DAYS):
        due = datetime.combine(today_ist + timedelta(days=days), time(17, 0), tzinfo=IST)
        conn.execute("INSERT INTO checklist_deadlines (semester_id, template_id, due_at) VALUES (%s, %s, %s)", (sem, tid, due))
    _audit(conn, "deadlines.set", "semester", sem, {"count": len(template)})

    logins = []

    def make_user(local, name, role, dep):
        email = f"{local}@{EMAIL_DOMAIN}"
        password = security.generate_temporary_password()
        row = conn.execute(
            """INSERT INTO users (email, password_hash, full_name, role, department_id, must_change_password)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING id""",
            (email, security.hash_password(password), name, role, dept[dep])).fetchone()
        _audit(conn, "USER_CREATED", "user", row["id"], {"role": role})
        logins.append((email, password, role))
        return row["id"]

    for local, name, dep in HODS:
        make_user(local, name, "HOD", dep)
    faculty_id = {}
    for local, name, dep, _subjects in FACULTY:
        faculty_id[local] = make_user(local, name, "FACULTY", dep)

    # The semester becomes current exactly like make-current does it (weights, then flags for passed deadlines).
    conn.execute("UPDATE semesters SET is_current = true WHERE id = %s", (sem,))
    score_store.ensure_semester_weights(conn, sem, set_by=None, reason="Weights in force when the demo semester became current")

    course_files = []
    for local, _name, dep, subs in FACULTY:
        for code in subs:
            cf = conn.execute(
                "INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id) VALUES (%s, %s, %s, %s) RETURNING id",
                (subject[code], sem, faculty_id[local], dept[dep])).fetchone()["id"]
            rows = create_for_course_file(conn, cf)
            _audit(conn, "course_file.create", "course_file", cf, {"subject": code, "submission_rows": rows})
            course_files.append(cf)

    counts = rules.evaluate_many(conn, rules.submissions_of(conn, sem), now=now, trigger="semester_open", refresh_scores=False)
    score_store.refresh_semester(conn, sem, trigger="semester_open", now=now)
    return {"logins": logins, "semester_id": sem, "course_files": len(course_files), "rules": counts}


def main(argv=None, connect_fn=connect) -> int:
    try:
        conn = connect_fn()
    except psycopg.Error as exc:
        print(f"ERROR: cannot reach PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        result = seed_demo(conn)
        conn.commit()
    except DemoError as exc:
        conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        conn.rollback()
        print(f"ERROR: database problem (did you run python -m app.core.migrate?): {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Demo data created: 2 departments, 8 subjects, 19 items, {result['course_files']} course files.")
    print(f"Deadline check: {result['rules']['raised']} flags raised for deadlines that already passed.")
    print("\nLogin (note the passwords now, they are not shown again):")
    for email, password, role in result["logins"]:
        print(f"  {role:8} {email:34} {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
