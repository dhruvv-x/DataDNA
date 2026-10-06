"""
Creates the "up front" submission rows (S4). A row exists for every applicable checklist item of every
course file, so "missing" is a real row that the rule engine (S5) can see, not an absence.

THEORY subject  -> templates applying to THEORY or BOTH
LAB subject     -> templates applying to LAB or BOTH
THEORY_LAB      -> every active template
"""
import uuid

_APPLIES = """(t.applies_to = 'BOTH'
               OR (t.applies_to = 'THEORY' AND s.subject_type IN ('THEORY', 'THEORY_LAB'))
               OR (t.applies_to = 'LAB'    AND s.subject_type IN ('LAB', 'THEORY_LAB')))"""


def create_for_course_file(db, course_file_id: uuid.UUID) -> int:
    cur = db.execute(
        f"""
        INSERT INTO submissions (course_file_id, template_id)
        SELECT cf.id, t.id
        FROM course_files cf
        JOIN subjects s ON s.id = cf.subject_id
        CROSS JOIN checklist_templates t
        WHERE cf.id = %s AND t.is_active AND {_APPLIES}
        ON CONFLICT (course_file_id, template_id) DO NOTHING
        """,
        (course_file_id,),
    )
    return cur.rowcount


def backfill_submissions(db, *, template_id: uuid.UUID) -> int:
    """After a template is created or switched on again: add its rows to course files of semesters not yet over."""
    cur = db.execute(
        f"""
        INSERT INTO submissions (course_file_id, template_id)
        SELECT cf.id, t.id
        FROM course_files cf
        JOIN subjects s ON s.id = cf.subject_id
        JOIN semesters sem ON sem.id = cf.semester_id
        JOIN checklist_templates t ON t.id = %s
        WHERE t.is_active AND {_APPLIES} AND sem.end_date >= CURRENT_DATE
        ON CONFLICT (course_file_id, template_id) DO NOTHING
        """,
        (template_id,),
    )
    return cur.rowcount
