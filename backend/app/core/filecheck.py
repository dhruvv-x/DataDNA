"""
File checks for uploads (S4). Two separate stages, on purpose:

  1. check_type()       Is this really the kind of file its name says, and is that kind allowed?
                        NO  -> the upload is rejected outright and nothing is stored.
  2. check_structure()  Is a file of the right kind actually usable (opens, not empty, not cut off)?
                        NO  -> the file IS stored as a version with validation_status FORMAT_FAILED,
                               and a FORMAT flag is raised, so the failure is visible and on record.

Only fixed, cheap checks. Free-form content understanding is not attempted here (S9, S18).
"""
import csv
import io
import re
import zipfile
from pathlib import Path

SUPPORTED_EXTENSIONS = ("pdf", "docx", "doc", "xlsx", "xls", "pptx", "csv", "txt", "png", "jpg", "jpeg")

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # old Office files, and password-protected new ones
_ZIP = b"PK\x03\x04"
_PNG = b"\x89PNG\r\n\x1a\n"
_OOXML_MEMBER = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
MAX_UNZIPPED_BYTES = 500 * 1024 * 1024               # guards against zip bombs
_TEXT_SAMPLE = 8192


class Rejected(Exception):
    """Upload must be refused and nothing stored. status is the HTTP code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def clean_filename(name: str | None) -> str:
    """Display name only. It is never used as a path on disk."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:200]


def extension_of(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext


def _head(path: Path, n: int) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(n)


def _tail(path: Path, n: int) -> bytes:
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(max(0, size - n))
        return fh.read()


def check_type(filename: str, allowed_extensions: list[str], path: Path, size: int) -> str:
    """Returns the lower-case extension, or raises Rejected."""
    if not filename:
        raise Rejected(422, "no_filename", "The uploaded file has no name.")
    ext = extension_of(filename)
    if not ext:
        raise Rejected(415, "no_extension", "The file name has no extension, so its type cannot be checked.")
    if ext not in SUPPORTED_EXTENSIONS or ext not in allowed_extensions:
        raise Rejected(415, "extension_not_allowed",
                       f".{ext} files are not allowed for this item. Allowed: {', '.join(allowed_extensions)}.")
    if size == 0:
        raise Rejected(422, "empty_file", "The file is empty (0 bytes).")

    head = _head(path, _TEXT_SAMPLE)
    ok = True
    if ext == "pdf":
        ok = head.startswith(b"%PDF-")
    elif ext in _OOXML_MEMBER:
        ok = head.startswith(_ZIP) or head.startswith(_OLE)   # OLE = password protected, see check_structure
    elif ext in ("doc", "xls"):
        ok = head.startswith(_OLE)
    elif ext == "png":
        ok = head.startswith(_PNG)
    elif ext in ("jpg", "jpeg"):
        ok = head.startswith(b"\xff\xd8\xff")
    elif ext in ("csv", "txt"):
        ok = b"\x00" not in head and not head.startswith((b"MZ", b"\x7fELF", b"%PDF-", _ZIP, _OLE))
    if not ok:
        raise Rejected(415, "content_mismatch", f"The file content is not a real .{ext} file.")
    return ext


def _decode_text(raw: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def check_structure(ext: str, path: Path) -> str | None:
    """Returns None when the file is usable, otherwise a short human readable reason."""
    try:
        return _check_structure(ext, path)
    except Exception as exc:  # a parser blowing up on a broken file IS the answer
        return f"The file could not be read ({type(exc).__name__})."


def _check_structure(ext: str, path: Path) -> str | None:
    head = _head(path, 8)
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return "The PDF is password protected. Upload an unprotected copy."
        if len(reader.pages) == 0:
            return "The PDF has no pages."
        return None

    if ext in _OOXML_MEMBER:
        if head.startswith(_OLE):
            return "The file is password protected or in an old format. Upload an unprotected .%s." % ext
        if not zipfile.is_zipfile(path):
            return "The file is damaged (not a valid Office file)."
        with zipfile.ZipFile(path) as zf:
            if zf.testzip() is not None:
                return "The file is damaged (corrupt data inside)."
            if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
                return "The file expands to an unreasonable size."
            if _OOXML_MEMBER[ext] not in zf.namelist():
                return f"The file is not a real .{ext} document (main part is missing)."
        if ext == "xlsx":
            from openpyxl import load_workbook

            # Open as a file object: the temp file has no extension and openpyxl refuses such paths.
            with open(path, "rb") as fh:
                wb = load_workbook(fh, read_only=True)
                try:
                    if not wb.sheetnames:
                        return "The workbook has no sheets."
                finally:
                    wb.close()
        return None

    if ext in ("doc", "xls"):
        return None  # old binary formats: the signature check is all we can do cheaply

    if ext in ("csv", "txt"):
        raw = path.read_bytes()
        text = _decode_text(raw)
        if text is None:
            return "The text is not readable (unknown character encoding)."
        if not text.strip():
            return "The file has no content."
        if ext == "csv":
            rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
            if not rows:
                return "The CSV has no rows."
        return None

    if ext == "png":
        return None if _tail(path, 12).endswith(b"IEND\xaeB`\x82") else "The PNG image is cut off or damaged."

    if ext in ("jpg", "jpeg"):
        return None if _tail(path, 64).rstrip(b"\x00").endswith(b"\xff\xd9") else "The JPEG image is cut off or damaged."

    return None
