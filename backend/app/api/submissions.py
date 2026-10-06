"""
Upload, version history and download of checklist files (S4).

Who: FACULTY (own course file, current semester only) and DEAN (any, but a reason is compulsory and the
fact that the Dean uploaded stays on the version forever). HOD only views.

Two kinds of bad upload:
  * wrong type / too big / empty / fake content  -> refused, nothing stored (HTTP 413, 415, 422)
  * right type but unreadable (corrupt, password protected, cut off) -> stored as a version with
    validation_status FORMAT_FAILED, a FORMAT flag is raised, and the answer says so clearly.
Every version is kept forever. A later valid upload clears the FORMAT flag. It never touches LATE flags.
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb

from app.api.deps import current_user, get_db
from app.core import auditlog, clock, filecheck, rules, settings, storage
from app.core.scope import DEAN, CurrentUser, can_upload, course_file_filter, forbidden, not_found

router = APIRouter(tags=["submissions"])
MB = 1024 * 1024
MIN_REASON = 10


def _visible_submission(db, submission_id, user, lock: bool = False):
    scope_sql, params = course_file_filter(user)
    return db.execute(
        f"""
        SELECT sub.id, sub.course_file_id, sub.current_version_id, cf.faculty_id,
               sem.is_current AS semester_is_current,
               t.code AS template_code, t.allowed_extensions, t.max_size_mb, t.is_active AS template_active
        FROM submissions sub
        JOIN course_files cf ON cf.id = sub.course_file_id
        JOIN semesters sem ON sem.id = cf.semester_id
        JOIN checklist_templates t ON t.id = sub.template_id
        WHERE sub.id = %s AND ({scope_sql})
        {"FOR UPDATE OF sub" if lock else ""}
        """,
        (submission_id, *params),
    ).fetchone()


def _refuse(db, user, submission_id, status: int, code: str, message: str, extra: dict | None = None):
    """Refuse an upload: log it (and commit the log), store nothing."""
    auditlog.write(db, actor_id=user.id, actor_role=user.role, action="submission.upload_rejected",
                   entity_type="submission", entity_id=submission_id, payload={"code": code, **(extra or {})})
    db.commit()
    raise HTTPException(status, {"code": code, "message": message})


@router.post("/submissions/{submission_id}/versions", status_code=201)
def upload_version(
    submission_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    reason: str | None = Form(default=None),
    user: CurrentUser = Depends(current_user),
    db=Depends(get_db),
):
    received_at = clock.utcnow()  # when the complete file reached the server; used for lateness in S5
    ctx = _visible_submission(db, submission_id, user)
    if ctx is None:
        raise not_found()
    if not can_upload(user):
        raise forbidden()
    if user.role != DEAN and not ctx["semester_is_current"]:
        raise HTTPException(409, "This semester is closed. Only the Dean can upload to it.")
    if not ctx["template_active"]:
        raise HTTPException(409, "This checklist item is switched off.")

    on_behalf_reason = None
    if user.role == DEAN:
        on_behalf_reason = (reason or "").strip()
        if len(on_behalf_reason) < MIN_REASON:
            raise HTTPException(422, f"A reason of at least {MIN_REASON} characters is required when the Dean uploads.")

    limit = min(ctx["max_size_mb"], settings.max_upload_mb()) * MB
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + MB:
        _refuse(db, user, submission_id, 413, "too_large",
                f"The file is larger than the {limit // MB} MB limit.", {"declared_bytes": int(declared)})

    try:
        tmp, size, sha256 = storage.receive(file.file, limit)
    except storage.TooLarge:
        _refuse(db, user, submission_id, 413, "too_large", f"The file is larger than the {limit // MB} MB limit.")

    placed_key = None
    try:
        filename = filecheck.clean_filename(file.filename)
        try:
            ext = filecheck.check_type(filename, ctx["allowed_extensions"], tmp, size)
        except filecheck.Rejected as exc:
            _refuse(db, user, submission_id, exc.status, exc.code, exc.message,
                    {"extension": filecheck.extension_of(filename), "size_bytes": size})
        problem = filecheck.check_structure(ext, tmp)

        # One upload at a time per submission, so version numbers never clash.
        locked = _visible_submission(db, submission_id, user, lock=True)
        current_sha = None
        if locked["current_version_id"] is not None:
            current_sha = db.execute("SELECT sha256 FROM submission_versions WHERE id = %s",
                                     (locked["current_version_id"],)).fetchone()["sha256"]
        if current_sha == sha256:
            _refuse(db, user, submission_id, 409, "same_file",
                    "This is exactly the same file as the current version. Nothing was changed.", {"sha256": sha256})
        version_no = db.execute("SELECT COALESCE(MAX(version_no), 0) + 1 AS n FROM submission_versions WHERE submission_id = %s",
                                (submission_id,)).fetchone()["n"]

        placed_key = storage.place(tmp, ctx["course_file_id"], submission_id, version_no, sha256, ext)
        status = "FORMAT_FAILED" if problem else "OK"
        detail = {"problem": problem} if problem else {}
        version = db.execute(
            """
            INSERT INTO submission_versions
              (submission_id, version_no, storage_key, original_filename, content_type, size_bytes, sha256,
               uploaded_by, uploaded_by_role, on_behalf_reason, uploaded_at, validation_status, validation_detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, version_no, sha256, size_bytes, original_filename, validation_status,
                      validation_detail, uploaded_by, uploaded_by_role, on_behalf_reason, uploaded_at
            """,
            (submission_id, version_no, placed_key, filename, (file.content_type or None), size, sha256,
             user.id, user.role, on_behalf_reason, received_at, status, Jsonb(detail)),
        ).fetchone()
        db.execute("UPDATE submissions SET current_version_id = %s WHERE id = %s", (version["id"], submission_id))

        changes = rules.evaluate_submission(
            db, submission_id, now=received_at, trigger="upload", by_user=user.id,
            new_version={"id": version["id"], "version_no": version_no, "uploaded_at": received_at,
                         "validation_status": status, "problem": problem})
        raised = [c["kind"] for c in changes if c["action"] == "raise"]
        cleared = [c["kind"] for c in changes if c["action"] == "clear"]
        flag_raised = "FORMAT" in raised
        flags_cleared = sum(1 for k in cleared if k == "FORMAT")

        auditlog.write(db, actor_id=user.id, actor_role=user.role, action="submission.upload",
                       entity_type="submission", entity_id=submission_id,
                       payload={"version_id": str(version["id"]), "version_no": version_no, "sha256": sha256,
                                "size_bytes": size, "extension": ext, "validation_status": status,
                                "on_behalf_reason": on_behalf_reason, "flags_raised": raised,
                                "flags_cleared": cleared})
        db.commit()
    except BaseException:
        storage.remove(placed_key)
        storage.discard(tmp)
        raise

    return {
        **version,
        "submission_id": submission_id,
        "is_current": True,
        "format_flag_raised": flag_raised,
        "format_flags_cleared": flags_cleared,
        "flags_raised": raised,
        "flags_cleared": cleared,
        "late": "LATE" in raised,
        "message": (("Saved, but the file has a problem: " + problem) if problem else "Saved. The file passed the format checks.")
                   + (" Note: it arrived after the deadline, so a lateness flag was recorded." if "LATE" in raised else ""),
    }


@router.get("/submissions/{submission_id}/versions")
def list_versions(submission_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    ctx = _visible_submission(db, submission_id, user)
    if ctx is None:
        raise not_found()
    return db.execute(
        """
        SELECT v.id, v.version_no, v.original_filename, v.size_bytes, v.sha256, v.validation_status,
               v.validation_detail, v.uploaded_at, v.uploaded_by, u.full_name AS uploaded_by_name,
               v.uploaded_by_role, v.on_behalf_reason, (v.id = %s) AS is_current
        FROM submission_versions v JOIN users u ON u.id = v.uploaded_by
        WHERE v.submission_id = %s ORDER BY v.version_no DESC
        """,
        (ctx["current_version_id"], submission_id),
    ).fetchall()


@router.get("/submission-versions/{version_id}/download")
def download_version(version_id: uuid.UUID, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    scope_sql, params = course_file_filter(user)
    row = db.execute(
        f"""
        SELECT v.id, v.submission_id, v.version_no, v.storage_key, v.original_filename, v.sha256
        FROM submission_versions v
        JOIN submissions sub ON sub.id = v.submission_id
        JOIN course_files cf ON cf.id = sub.course_file_id
        WHERE v.id = %s AND ({scope_sql})
        """,
        (version_id, *params),
    ).fetchone()
    if row is None:
        raise not_found()

    def audit(action: str, extra: dict | None = None):
        auditlog.write(db, actor_id=user.id, actor_role=user.role, action=action, entity_type="submission_version",
                       entity_id=version_id, payload={"submission_id": str(row["submission_id"]),
                                                      "version_no": row["version_no"], **(extra or {})})
        db.commit()

    path = storage.resolve(row["storage_key"])
    if not path.is_file():
        audit("version.download_failed", {"reason": "file_missing"})
        raise HTTPException(500, "The stored file is missing on the server. Tell the administrator; do not re-upload yet.")
    if storage.sha256_of(path) != row["sha256"]:
        audit("version.download_failed", {"reason": "hash_mismatch"})
        raise HTTPException(500, "The stored file no longer matches its recorded SHA-256. It may have been changed. Tell the administrator.")
    audit("version.download")
    return FileResponse(
        path, media_type="application/octet-stream", filename=row["original_filename"], content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "X-File-SHA256": row["sha256"]},
    )
