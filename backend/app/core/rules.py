"""
The rule engine (S5). It turns FACTS (deadline, extensions, uploaded versions) into FLAGS.
It never produces a score. The score (S6) reads these flags.

The rules, in plain words
-------------------------
Effective deadline = the checklist deadline, or the latest extension if one was granted.
No deadline for the item = no timing rules at all (nothing can be late or missing).

EVENT flags, judged once, at upload time, against the deadline in force at that moment:
  LATE    the FIRST file of an item arrived after the effective deadline. One per item for life.
          It never clears. Only a waiver (with reason) can set it aside. Later deadline changes,
          later uploads and sweeps never create it, move it or remove it.
  FORMAT  an uploaded file has the right type but is unusable. Clears when the newest file is valid.
          Clearing works at any time, also after the deadline. It never touches LATE.

STATE flags, true or false right now, re-checked by every evaluation (only in the CURRENT semester):
  MISSING     deadline passed and no file at all. Clears when a file arrives (the item is then LATE).
  INCOMPLETE  deadline passed, files exist, but the newest one is unusable. Clears when it is valid.
  These clear on their own when the reason is gone (file arrives, deadline moved forward, item
  switched off). A waived MISSING/INCOMPLETE is never raised again for that item.

Evaluation is idempotent: running it twice in a row changes nothing the second time.
decide() is a pure function (no database), so every boundary can be unit tested exactly.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from app.core import auditlog, score_store

IST = timezone(timedelta(hours=5, minutes=30))
STATE_KINDS = ("MISSING", "INCOMPLETE")
RULE_KINDS = ("LATE", "MISSING", "INCOMPLETE", "FORMAT")
SWEEP_LOCK_KEY = 727_005


# ------------------------------------------------------------------ plain-language helpers
def human_time(moment: datetime) -> str:
    return moment.astimezone(IST).strftime("%d %b %Y %H:%M") + " IST"


def human_delta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    parts = []
    for name, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    return " ".join(parts[:2])


def effective_due(due_at, ext_due):
    """Latest of the checklist deadline and any granted extension. None when the item has no deadline."""
    if due_at is None:
        return None
    return max(due_at, ext_due) if ext_due is not None else due_at


# ------------------------------------------------------------------ the pure decision
@dataclass
class Plan:
    raise_: list = field(default_factory=list)   # dicts: kind, reason, detail, version_id
    clear: list = field(default_factory=list)    # dicts: flag_id, kind, version_id, why


def decide(*, due_at, ext_due, template_active: bool, semester_is_current: bool,
           versions: list[dict], flags: list[dict], now: datetime, new_version: dict | None = None) -> Plan:
    """
    versions: [{id, version_no, uploaded_at, validation_status}], any order
    flags:    [{id, kind, status}] of kinds LATE/MISSING/INCOMPLETE/FORMAT, every status
    new_version: the version that was just uploaded (event rules fire only for it), else None
    """
    plan = Plan()
    versions = sorted(versions, key=lambda v: v["version_no"])
    current = versions[-1] if versions else None
    current_ok = current is not None and current["validation_status"] == "OK"
    due = effective_due(due_at, ext_due)
    due_passed = due is not None and now > due
    open_of = lambda kind: [f for f in flags if f["kind"] == kind and f["status"] == "OPEN"]       # noqa: E731
    ever = lambda kind: [f for f in flags if f["kind"] == kind]                                      # noqa: E731
    waived = lambda kind: [f for f in flags if f["kind"] == kind and f["status"] == "WAIVED"]       # noqa: E731

    # ---- event rules (upload time only)
    if new_version is not None:
        if (new_version["version_no"] == 1 and due is not None and new_version["uploaded_at"] > due
                and not ever("LATE")):
            late_by = (new_version["uploaded_at"] - due).total_seconds()
            plan.raise_.append({
                "kind": "LATE", "version_id": new_version["id"],
                "reason": f"Delivered {human_delta(late_by)} after the deadline ({human_time(due)}).",
                "detail": {"due_at": due_at.isoformat(), "effective_due_at": due.isoformat(),
                           "delivered_at": new_version["uploaded_at"].isoformat(),
                           "late_by_seconds": int(late_by), "version_no": new_version["version_no"]},
            })
        if new_version["validation_status"] == "FORMAT_FAILED" and not open_of("FORMAT"):
            plan.raise_.append({
                "kind": "FORMAT", "version_id": new_version["id"],
                "reason": new_version.get("problem") or "The file could not be read.",
                "detail": {"version_no": new_version["version_no"]},
            })

    # ---- state rules (only while the semester is current and the item is switched on)
    if semester_is_current and template_active and due_passed:
        if current is None and not open_of("MISSING") and not waived("MISSING"):
            plan.raise_.append({
                "kind": "MISSING", "version_id": None,
                "reason": f"Nothing was submitted by the deadline ({human_time(due)}).",
                "detail": {"due_at": due_at.isoformat(), "effective_due_at": due.isoformat()},
            })
        if current is not None and not current_ok and not open_of("INCOMPLETE") and not waived("INCOMPLETE"):
            plan.raise_.append({
                "kind": "INCOMPLETE", "version_id": current["id"],
                "reason": f"The deadline ({human_time(due)}) has passed and the newest file is not usable.",
                "detail": {"due_at": due_at.isoformat(), "effective_due_at": due.isoformat(),
                           "version_no": current["version_no"]},
            })

    # ---- clearing (always allowed, also in closed semesters). LATE is never cleared here.
    for f in open_of("MISSING"):
        if current is not None:
            plan.clear.append({"flag_id": f["id"], "kind": "MISSING", "version_id": versions[0]["id"], "why": "a file arrived"})
        elif not template_active:
            plan.clear.append({"flag_id": f["id"], "kind": "MISSING", "version_id": None, "why": "the item was switched off"})
        elif not due_passed:
            plan.clear.append({"flag_id": f["id"], "kind": "MISSING", "version_id": None, "why": "the deadline is no longer in the past"})
    for f in open_of("INCOMPLETE"):
        if current_ok:
            plan.clear.append({"flag_id": f["id"], "kind": "INCOMPLETE", "version_id": current["id"], "why": "a valid file arrived"})
        elif not template_active:
            plan.clear.append({"flag_id": f["id"], "kind": "INCOMPLETE", "version_id": None, "why": "the item was switched off"})
        elif not due_passed:
            plan.clear.append({"flag_id": f["id"], "kind": "INCOMPLETE", "version_id": None, "why": "the deadline is no longer in the past"})
        elif current is None:
            plan.clear.append({"flag_id": f["id"], "kind": "INCOMPLETE", "version_id": None, "why": "no file exists"})
    if current_ok:
        for f in open_of("FORMAT"):
            plan.clear.append({"flag_id": f["id"], "kind": "FORMAT", "version_id": current["id"], "why": "a valid file arrived"})
    return plan


# ------------------------------------------------------------------ database side
_FACTS = """
    SELECT sub.id, sub.course_file_id, cf.semester_id, sem.is_current AS semester_is_current,
           t.is_active AS template_active, dl.due_at,
           (SELECT max(e.new_due_at) FROM exceptions e WHERE e.submission_id = sub.id AND e.kind = 'EXTENSION') AS ext_due
    FROM submissions sub
    JOIN course_files cf ON cf.id = sub.course_file_id
    JOIN semesters sem ON sem.id = cf.semester_id
    JOIN checklist_templates t ON t.id = sub.template_id
    LEFT JOIN checklist_deadlines dl ON dl.semester_id = cf.semester_id AND dl.template_id = sub.template_id
    WHERE sub.id = %s
    FOR UPDATE OF sub
"""


def _log(db, action: str, flag_id, payload: dict, trigger: str, by_user=None):
    auditlog.write(db, actor_id=None, actor_role="SYSTEM", action=action, entity_type="flag", entity_id=flag_id,
                   payload={**payload, "trigger": trigger, **({"by_user": str(by_user)} if by_user else {})})


def evaluate_submission(db, submission_id: uuid.UUID, *, now: datetime, trigger: str,
                        new_version: dict | None = None, by_user=None, refresh_scores: bool = True) -> list[dict]:
    """
    Apply decide() to one submission. Takes the submission row lock first. Returns what changed.
    Afterwards the trust score of its course file is refreshed (S6), unless the caller does that itself.
    """
    facts = db.execute(_FACTS, (submission_id,)).fetchone()
    if facts is None:
        return []
    versions = db.execute(
        "SELECT id, version_no, uploaded_at, validation_status FROM submission_versions WHERE submission_id = %s",
        (submission_id,)).fetchall()
    flags = db.execute(
        "SELECT id, kind, status FROM flags WHERE submission_id = %s AND kind = ANY(%s)",
        (submission_id, list(RULE_KINDS))).fetchall()
    plan = decide(due_at=facts["due_at"], ext_due=facts["ext_due"], template_active=facts["template_active"],
                  semester_is_current=facts["semester_is_current"], versions=versions, flags=flags,
                  now=now, new_version=new_version)

    changes = []
    for item in plan.clear:
        done = db.execute(
            """UPDATE flags SET status = 'CLEARED', cleared_at = %s, cleared_by_version_id = %s
               WHERE id = %s AND status = 'OPEN' AND kind <> 'LATE' RETURNING id""",
            (now, item["version_id"], item["flag_id"])).fetchone()
        if done:
            _log(db, "flag.clear", item["flag_id"], {"kind": item["kind"], "submission_id": str(submission_id), "why": item["why"]}, trigger, by_user)
            changes.append({"action": "clear", "kind": item["kind"], "flag_id": item["flag_id"]})
    for item in plan.raise_:
        row = db.execute(
            """INSERT INTO flags (course_file_id, submission_id, kind, reason, detail, raised_by_version_id, raised_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id""",
            (facts["course_file_id"], submission_id, item["kind"], item["reason"], Jsonb(item["detail"]),
             item["version_id"], now)).fetchone()
        if row:
            _log(db, "flag.raise", row["id"], {"kind": item["kind"], "submission_id": str(submission_id), "reason": item["reason"]}, trigger, by_user)
            changes.append({"action": "raise", "kind": item["kind"], "flag_id": row["id"]})
    if refresh_scores:
        score_store.refresh_for_submissions(db, [submission_id], trigger=trigger, now=now)
    return changes


def evaluate_many(db, submission_ids, *, now: datetime, trigger: str, by_user=None, refresh_scores: bool = True) -> dict:
    counts = {"checked": 0, "raised": 0, "cleared": 0}
    ids = list(submission_ids)
    for sid in ids:
        changes = evaluate_submission(db, sid, now=now, trigger=trigger, by_user=by_user, refresh_scores=False)
        counts["checked"] += 1
        counts["raised"] += sum(1 for c in changes if c["action"] == "raise")
        counts["cleared"] += sum(1 for c in changes if c["action"] == "clear")
    if refresh_scores:  # once per course file, not once per item
        score_store.refresh_for_submissions(db, ids, trigger=trigger, now=now)
    return counts


def submissions_of(db, semester_id, template_ids=None) -> list[uuid.UUID]:
    if template_ids is None:
        rows = db.execute("SELECT sub.id FROM submissions sub JOIN course_files cf ON cf.id = sub.course_file_id "
                          "WHERE cf.semester_id = %s ORDER BY sub.id", (semester_id,)).fetchall()
    else:
        rows = db.execute("SELECT sub.id FROM submissions sub JOIN course_files cf ON cf.id = sub.course_file_id "
                          "WHERE cf.semester_id = %s AND sub.template_id = ANY(%s) ORDER BY sub.id",
                          (semester_id, list(template_ids))).fetchall()
    return [r["id"] for r in rows]


def sweep(db, *, now: datetime, semester_id=None, trigger: str = "sweep", by_user=None, by_role=None) -> dict | None:
    """
    Re-check deadlines of the current semester (or one given semester). Each item is its own small
    transaction, so a sweep never blocks uploads for long. Returns None if another sweep is running.
    """
    got = db.execute("SELECT pg_try_advisory_lock(%s) AS ok", (SWEEP_LOCK_KEY,)).fetchone()["ok"]
    if not got:
        db.commit()
        return None
    try:
        if semester_id is None:
            rows = db.execute("SELECT id FROM semesters WHERE is_current").fetchall()
            semester_ids = [r["id"] for r in rows]
        else:
            semester_ids = [semester_id]
        db.commit()
        total = {"checked": 0, "raised": 0, "cleared": 0}
        for sem in semester_ids:
            candidates = db.execute(
                """
                SELECT sub.id FROM submissions sub
                JOIN course_files cf ON cf.id = sub.course_file_id
                LEFT JOIN checklist_deadlines dl ON dl.semester_id = cf.semester_id AND dl.template_id = sub.template_id
                WHERE cf.semester_id = %s
                  AND (dl.due_at < %s
                       OR EXISTS (SELECT 1 FROM flags f WHERE f.submission_id = sub.id
                                  AND f.status = 'OPEN' AND f.kind IN ('MISSING', 'INCOMPLETE')))
                ORDER BY sub.id
                """, (sem, now)).fetchall()
            db.commit()
            for row in candidates:
                counts = evaluate_many(db, [row["id"]], now=now, trigger=trigger, by_user=by_user, refresh_scores=False)
                db.commit()
                for k in total:
                    total[k] += counts[k]
            # Safety net: bring every score of this semester up to date once per sweep (writes only on change).
            score_store.refresh_semester(db, sem, trigger=trigger, now=now)
            db.commit()
        auditlog.write(db, actor_id=by_user, actor_role=by_role or "SYSTEM", action="rules.sweep",
                       entity_type="rules", entity_id=None, payload={**total, "trigger": trigger,
                                                                   "semesters": [str(s) for s in semester_ids]})
        db.commit()
        return total
    finally:
        db.rollback()  # a failed statement leaves the transaction unusable; the lock must still be released
        db.execute("SELECT pg_advisory_unlock(%s)", (SWEEP_LOCK_KEY,))
        db.commit()
