"""
Trust score (S6), database side: load the facts, compute with app.core.scoring, keep the history.

Rules this file enforces
  * The score is a function of the FLAGS (plus which checklist items exist). One source of truth.
  * CURRENT semester: always computed live. Snapshots are written only when the result CHANGED.
  * CLOSED semester: the score of record is its latest snapshot, scored with the weights it was closed with.
    Bulk changes (deadline edit, template switch, sweeps) never rewrite closed history.
    Single actions (a Dean upload, a waiver, an extension) add a new snapshot, the old ones stay.
  * Snapshots are append-only. The history of a course file is its list of snapshots.
"""
import uuid
from datetime import datetime

from psycopg.types.json import Jsonb

from app.core import scoring, settings

# Triggers that touch many items at once. They must not rewrite a closed semester.
BULK_TRIGGERS = frozenset({"sweep", "schedule", "manual", "cli", "deadline_change", "template_change"})

_ITEMS_SQL = """
    SELECT cf.id AS course_file_id, sub.id AS submission_id, t.code, t.title, t.sort_order,
           (nv.validation_status IS NOT NULL) AS has_file,
           (nv.validation_status = 'OK') AS newest_ok,
           CASE WHEN dl.due_at IS NULL THEN NULL
                ELSE GREATEST(dl.due_at, COALESCE(ext.due, dl.due_at)) END AS due_at
    FROM course_files cf
    JOIN submissions sub ON sub.course_file_id = cf.id
    JOIN checklist_templates t ON t.id = sub.template_id AND t.is_active
    LEFT JOIN checklist_deadlines dl ON dl.semester_id = cf.semester_id AND dl.template_id = sub.template_id
    LEFT JOIN LATERAL (SELECT max(e.new_due_at) AS due FROM exceptions e
                       WHERE e.submission_id = sub.id AND e.kind = 'EXTENSION') ext ON true
    LEFT JOIN LATERAL (SELECT v.validation_status FROM submission_versions v
                       WHERE v.submission_id = sub.id ORDER BY v.version_no DESC LIMIT 1) nv ON true
    WHERE cf.id = ANY(%s)
    ORDER BY cf.id, t.sort_order, t.code, sub.id
"""
_FLAGS_SQL = """
    SELECT id, course_file_id, submission_id, kind, status, reason
    FROM flags
    WHERE course_file_id = ANY(%s) AND submission_id IS NOT NULL AND kind = ANY(%s)
    ORDER BY raised_at, id
"""


# ---------------------------------------------------------------- weights
def latest_weights(db) -> dict:
    return db.execute("SELECT * FROM score_weights ORDER BY id DESC LIMIT 1").fetchone()


def weights_by_id(db, weights_id: int) -> dict:
    return db.execute("SELECT * FROM score_weights WHERE id = %s", (weights_id,)).fetchone()


def semester_weights(db, semester_id) -> dict:
    """Weights a semester is scored with. A semester never made current yet follows the latest weights."""
    row = db.execute(
        """SELECT w.* FROM semester_weights sw JOIN score_weights w ON w.id = sw.weights_id
           WHERE sw.semester_id = %s ORDER BY sw.id DESC LIMIT 1""", (semester_id,)).fetchone()
    return row if row is not None else latest_weights(db)


def ensure_semester_weights(db, semester_id, *, set_by=None, reason: str) -> bool:
    """Give a semester its weights if it has none yet (done when it becomes current). Returns True if added."""
    if db.execute("SELECT 1 FROM semester_weights WHERE semester_id = %s LIMIT 1", (semester_id,)).fetchone():
        return False
    db.execute("INSERT INTO semester_weights (semester_id, weights_id, reason, set_by) VALUES (%s, %s, %s, %s)",
               (semester_id, latest_weights(db)["id"], reason, set_by))
    return True


# ---------------------------------------------------------------- loading
def load_items(db, course_file_ids: list, now: datetime) -> dict:
    """{course_file_id: [item dict for scoring.score_item]}"""
    ids = list(course_file_ids)
    if not ids:
        return {}
    rows = db.execute(_ITEMS_SQL, (ids,)).fetchall()
    flags = db.execute(_FLAGS_SQL, (ids, list(scoring.SCORED_KINDS))).fetchall()
    by_sub: dict = {}
    for f in flags:
        by_sub.setdefault(f["submission_id"], []).append(f)
    out: dict = {cf: [] for cf in ids}
    for r in rows:
        out[r["course_file_id"]].append({
            "submission_id": r["submission_id"], "code": r["code"], "title": r["title"],
            "sort_order": r["sort_order"], "has_file": bool(r["has_file"]), "newest_ok": r["newest_ok"],
            "due_at": r["due_at"], "due_passed": r["due_at"] is not None and r["due_at"] < now,
            "flags": by_sub.get(r["submission_id"], []),
        })
    return out


def _course_file_rows(db, course_file_ids: list) -> list[dict]:
    return db.execute(
        """SELECT cf.id, cf.semester_id, s.is_current FROM course_files cf
           JOIN semesters s ON s.id = cf.semester_id WHERE cf.id = ANY(%s) ORDER BY cf.id""",
        (list(course_file_ids),)).fetchall()


def latest_snapshots(db, course_file_ids: list) -> dict:
    rows = db.execute(
        """SELECT DISTINCT ON (course_file_id) id, course_file_id, semester_id, weights_id, content_active,
                  fingerprint, is_final, trigger, created_at, breakdown
           FROM score_snapshots WHERE course_file_id = ANY(%s)
           ORDER BY course_file_id, id DESC""", (list(course_file_ids),)).fetchall()
    return {r["course_file_id"]: r for r in rows}


def _params(db, cf: dict, snap: dict | None, cache: dict) -> tuple[dict, bool]:
    """(weights row, content_active) used for this course file."""
    if cf["is_current"] or snap is None:
        key = cf["semester_id"]
        if key not in cache:
            cache[key] = semester_weights(db, key)
        return cache[key], settings.content_scoring_enabled()
    return weights_by_id(db, snap["weights_id"]), snap["content_active"]


# ---------------------------------------------------------------- live computation
def compute_many(db, course_file_ids: list, now: datetime, *, snapshots: dict | None = None) -> dict:
    """{course_file_id: result dict} computed now. Closed semesters use the weights of their latest snapshot."""
    rows = _course_file_rows(db, course_file_ids)
    snaps = snapshots if snapshots is not None else latest_snapshots(db, [r["id"] for r in rows])
    items = load_items(db, [r["id"] for r in rows], now)
    cache: dict = {}
    out = {}
    for cf in rows:
        weights, content_active = _params(db, cf, snaps.get(cf["id"]), cache)
        out[cf["id"]] = scoring.compute(items[cf["id"]], weights, content_active)
    return out


# ---------------------------------------------------------------- snapshots
def _insert_snapshot(db, cf: dict, result: dict, trigger: str, *, final: bool) -> int:
    parts = result["parts"]
    scored = result["status"] == scoring.SCORED
    row = db.execute(
        """INSERT INTO score_snapshots
             (course_file_id, semester_id, weights_id, content_active, status, total,
              completeness_pts, timeliness_pts, format_pts, content_pts,
              eff_completeness, eff_timeliness, eff_format, eff_content,
              items_total, items_pending, breakdown, fingerprint, trigger, is_final)
           VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s,%s) RETURNING id""",
        (cf["id"], cf["semester_id"], result["weights"]["id"], result["content_active"], result["status"],
         result["total"],
         *(parts[p]["points"] if scored else None for p in scoring.PARTS),
         *(parts[p]["effective_weight"] for p in scoring.PARTS),
         result["items_total"], result["items_pending"], Jsonb(result), result["fingerprint"], trigger, final),
    ).fetchone()
    return row["id"]


def _lock(db, course_file_ids: list) -> None:
    """One writer per course file at a time (sorted order, so two callers cannot deadlock)."""
    for cf_id in sorted(str(i) for i in course_file_ids):
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("score:" + cf_id,))


def refresh_course_files(db, course_file_ids, *, trigger: str, now: datetime, force_final: bool = False) -> dict:
    """
    Recompute and write a snapshot for every course file whose result changed (or always, for force_final).
    The caller commits. Returns {"written": n, "unchanged": n, "skipped": n}.
    """
    ids = sorted(set(course_file_ids), key=str)
    counts = {"written": 0, "unchanged": 0, "skipped": 0}
    if not ids:
        return counts
    _lock(db, ids)
    rows = _course_file_rows(db, ids)
    snaps = latest_snapshots(db, ids)
    items = load_items(db, ids, now)
    cache: dict = {}
    for cf in rows:
        snap = snaps.get(cf["id"])
        if not cf["is_current"] and trigger in BULK_TRIGGERS and not force_final and snap is not None:
            counts["skipped"] += 1  # closed history is not rewritten by bulk changes
            continue
        weights, content_active = _params(db, cf, snap, cache)
        result = scoring.compute(items[cf["id"]], weights, content_active)
        if snap is not None and snap["fingerprint"] == result["fingerprint"] and (not force_final or snap["is_final"]):
            counts["unchanged"] += 1
            continue
        _insert_snapshot(db, cf, result, trigger, final=force_final)
        counts["written"] += 1
    return counts


def refresh_semester(db, semester_id, *, trigger: str, now: datetime, force_final: bool = False) -> dict:
    ids = [r["id"] for r in db.execute("SELECT id FROM course_files WHERE semester_id = %s ORDER BY id",
                                       (semester_id,)).fetchall()]
    return refresh_course_files(db, ids, trigger=trigger, now=now, force_final=force_final)


def refresh_for_submissions(db, submission_ids, *, trigger: str, now: datetime) -> dict:
    ids = list(submission_ids)
    if not ids:
        return {"written": 0, "unchanged": 0, "skipped": 0}
    cfs = [r["course_file_id"] for r in db.execute(
        "SELECT DISTINCT course_file_id FROM submissions WHERE id = ANY(%s)", (ids,)).fetchall()]
    return refresh_course_files(db, cfs, trigger=trigger, now=now)


def finalize_semester(db, semester_id, *, now: datetime) -> dict:
    """Closing a semester: write the final snapshot of every course file in it."""
    return refresh_semester(db, semester_id, trigger="semester_close", now=now, force_final=True)


# ---------------------------------------------------------------- reading
def view_of_snapshot(snap: dict) -> dict:
    """Snapshot row -> the same shape the live score has."""
    return {**snap["breakdown"], "source": "snapshot", "snapshot_id": snap["id"], "is_final": snap["is_final"],
            "trigger": snap["trigger"], "as_of": snap["created_at"]}


def score_views(db, course_files: list[dict], now: datetime) -> dict:
    """
    {course_file_id: view}. course_files rows need id and is_current.
    Current semester: live. Closed: latest snapshot, or a live (unfrozen) computation if none exists yet.
    """
    ids = [c["id"] for c in course_files]
    snaps = latest_snapshots(db, ids)
    need_live = [c["id"] for c in course_files if c["is_current"] or c["id"] not in snaps]
    live = compute_many(db, need_live, now, snapshots=snaps) if need_live else {}
    out = {}
    for c in course_files:
        if c["is_current"]:
            out[c["id"]] = {**live[c["id"]], "source": "live", "snapshot_id": None, "is_final": False,
                            "trigger": None, "as_of": now}
        elif c["id"] in snaps:
            out[c["id"]] = view_of_snapshot(snaps[c["id"]])
        else:
            out[c["id"]] = {**live[c["id"]], "source": "live_unfrozen", "snapshot_id": None, "is_final": False,
                            "trigger": None, "as_of": now}
    return out
