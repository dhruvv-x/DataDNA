"""Builders for the S4 tests: real small files of each type, and checklist set-up."""
import io
import struct
import zipfile
import zlib

from openpyxl import Workbook
from pypdf import PdfWriter

from app.tests.api_fixtures import as_user, uid


def make_pdf(pages: int = 1, password: str | None = None) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_xlsx(cell: str = "x") -> bytes:
    wb = Workbook()
    wb.active["A1"] = cell
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def make_docx(text: str = "hello") -> bytes:
    return _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": f"<doc>{text}</doc>".encode()})


def make_pptx() -> bytes:
    return _zip({"[Content_Types].xml": b"<Types/>", "ppt/presentation.xml": b"<p/>"})


def make_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


def make_jpg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 30 + b"\xff\xd9"


CSV = b"name,marks\nAsha,10\nRavi,12\n"
FAKE_EXE = b"MZ\x90\x00" + b"\x00" * 200
TRUNCATED_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog"


def make_template(conn, code=None, exts=("pdf",), max_mb=10, applies_to="BOTH", active=True, sort=0) -> dict:
    return conn.execute(
        """INSERT INTO checklist_templates (code, title, applies_to, allowed_extensions, max_size_mb, is_active, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (code or f"T{uid()}", "Item " + uid(), applies_to, list(exts), max_mb, active, sort),
    ).fetchone()


def make_submission(conn, course_file, template) -> dict:
    return conn.execute(
        "INSERT INTO submissions (course_file_id, template_id) VALUES (%s, %s) RETURNING *",
        (course_file["id"], template["id"]),
    ).fetchone()


def set_current(conn, semester, current=True):
    conn.execute("UPDATE semesters SET is_current = false WHERE is_current")
    conn.execute("UPDATE semesters SET is_current = %s WHERE id = %s", (current, semester["id"]))


def upload(client, who, submission, name, data, reason=None, content_type="application/octet-stream"):
    sid = submission["id"] if isinstance(submission, dict) else submission
    return client.post(
        f"/submissions/{sid}/versions",
        headers=as_user(client, who),
        files={"file": (name, data, content_type)},
        data={"reason": reason} if reason is not None else None,
    )


def stored_files(storage_root) -> list:
    """Every real file under the storage folder, and nothing left behind in its temp area."""
    from pathlib import Path

    root = Path(storage_root)
    return sorted(p for p in root.rglob("*") if p.is_file())
