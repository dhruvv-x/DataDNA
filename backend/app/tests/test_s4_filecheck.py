"""S4: the two file check stages, without any database."""
import pytest

from app.core import filecheck
from app.core.filecheck import Rejected, check_structure, check_type, clean_filename
from app.tests.s4_helpers import (CSV, FAKE_EXE, TRUNCATED_PDF, _zip, make_docx, make_jpg, make_pdf, make_png,
                                  make_pptx, make_xlsx)

ALL = list(filecheck.SUPPORTED_EXTENSIONS)


def f(tmp_path, data: bytes, name="x"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def type_of(tmp_path, filename, data, allowed=None):
    return check_type(filename, allowed or ALL, f(tmp_path, data), len(data))


def reject_code(tmp_path, filename, data, allowed=None):
    with pytest.raises(Rejected) as e:
        type_of(tmp_path, filename, data, allowed)
    return e.value.status, e.value.code


# ------------------------------------------------------------ stage 1: type
@pytest.mark.parametrize("name,data", [
    ("a.pdf", make_pdf()), ("a.docx", make_docx()), ("a.xlsx", make_xlsx()), ("a.pptx", make_pptx()),
    ("a.csv", CSV), ("a.txt", b"hello"), ("a.png", make_png()), ("a.jpg", make_jpg()), ("a.jpeg", make_jpg()),
    ("a.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 20), ("a.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 20),
    ("UPPER.PDF", make_pdf()),
])
def test_real_files_pass_the_type_check(tmp_path, name, data):
    assert type_of(tmp_path, name, data) == name.rsplit(".", 1)[1].lower()


@pytest.mark.parametrize("name,data", [
    ("a.pdf", FAKE_EXE), ("a.pdf", b"just text"), ("a.docx", b"%PDF-1.4 x"), ("a.xlsx", FAKE_EXE),
    ("a.png", make_jpg()), ("a.jpg", make_png()), ("a.doc", make_pdf()),
    ("a.csv", FAKE_EXE), ("a.csv", make_pdf()), ("a.csv", make_xlsx()), ("a.txt", b"abc\x00def"),
])
def test_fake_content_is_rejected_and_never_stored(tmp_path, name, data):
    assert reject_code(tmp_path, name, data) == (415, "content_mismatch")


def test_extension_must_be_allowed_for_this_item(tmp_path):
    assert reject_code(tmp_path, "a.docx", make_docx(), allowed=["pdf"]) == (415, "extension_not_allowed")


@pytest.mark.parametrize("name", ["virus.exe", "script.sh", "page.html", "a.zip", "a.PDF.exe"])
def test_unsupported_extensions_are_rejected_even_if_listed_nowhere(tmp_path, name):
    assert reject_code(tmp_path, name, b"data")[1] == "extension_not_allowed"


def test_no_extension_and_no_name_are_rejected(tmp_path):
    assert reject_code(tmp_path, "README", b"x") == (415, "no_extension")
    assert reject_code(tmp_path, "", b"x") == (422, "no_filename")


def test_empty_file_is_rejected(tmp_path):
    p = f(tmp_path, b"")
    with pytest.raises(Rejected) as e:
        check_type("a.pdf", ALL, p, 0)
    assert (e.value.status, e.value.code) == (422, "empty_file")


def test_password_protected_office_file_passes_type_check_but_fails_structure(tmp_path):
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 50
    assert type_of(tmp_path, "a.docx", ole) == "docx"
    assert "password" in check_structure("docx", f(tmp_path, ole))


# ------------------------------------------------------------ stage 2: structure
@pytest.mark.parametrize("ext,data", [
    ("pdf", make_pdf(3)), ("docx", make_docx()), ("xlsx", make_xlsx()), ("pptx", make_pptx()),
    ("csv", CSV), ("csv", "नाम,अंक\nआशा,10\n".encode("utf-8")), ("csv", b"\xef\xbb\xbfa,b\n1,2\n"),
    ("csv", "a,b\n\xe9,2\n".encode("cp1252")), ("txt", b"some notes"), ("png", make_png()), ("jpg", make_jpg()),
    ("doc", b"\xd0\xcf\x11\xe0" + b"0" * 20),
])
def test_good_files_have_no_structure_problem(tmp_path, ext, data):
    assert check_structure(ext, f(tmp_path, data)) is None


def test_truncated_pdf_is_a_format_problem(tmp_path):
    assert check_structure("pdf", f(tmp_path, TRUNCATED_PDF))


def test_password_protected_pdf_is_a_format_problem(tmp_path):
    assert "password" in check_structure("pdf", f(tmp_path, make_pdf(password="secret")))


def test_pdf_with_no_pages_is_a_format_problem(tmp_path):
    assert "no pages" in check_structure("pdf", f(tmp_path, make_pdf(pages=0)))


def test_broken_zip_is_a_format_problem(tmp_path):
    assert check_structure("docx", f(tmp_path, b"PK\x03\x04" + b"garbage" * 20))


def test_office_file_of_the_wrong_kind_is_a_format_problem(tmp_path):
    assert "main part is missing" in check_structure("xlsx", f(tmp_path, make_docx()))
    assert "main part is missing" in check_structure("docx", f(tmp_path, make_xlsx()))


def test_xlsx_that_openpyxl_cannot_open_is_a_format_problem(tmp_path):
    bad = _zip({"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<not-a-workbook"})
    assert check_structure("xlsx", f(tmp_path, bad))


@pytest.mark.parametrize("ext,data", [("csv", b"  \n\n ,, \n"), ("csv", b"   "), ("txt", b"\n\n  \n"),
                                      ("csv", b"a,b\n\x81\x8d\n")])
def test_empty_or_unreadable_text_is_a_format_problem(tmp_path, ext, data):
    assert check_structure(ext, f(tmp_path, data))


def test_cut_off_images_are_a_format_problem(tmp_path):
    assert check_structure("png", f(tmp_path, make_png()[:-8]))
    assert check_structure("jpg", f(tmp_path, make_jpg()[:-2]))


def test_a_parser_crash_is_reported_not_raised(tmp_path, monkeypatch):
    import pypdf

    def boom(*a, **k):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(pypdf, "PdfReader", boom)
    assert "could not be read" in check_structure("pdf", f(tmp_path, make_pdf()))


def test_extension_less_temp_file_still_opens_as_xlsx(tmp_path):
    """Regression: uploads are checked from a temp file whose name has no extension."""
    p = tmp_path / "up_abc123"
    p.write_bytes(make_xlsx())
    assert check_structure("xlsx", p) is None


# ------------------------------------------------------------ names
@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"), ("C:\\Users\\x\\report.pdf", "report.pdf"), ("a/b/c.pdf", "c.pdf"),
    ("ok.pdf", "ok.pdf"), ("bad\x00name\n.pdf", "badname.pdf"), (None, ""),
])
def test_clean_filename_never_keeps_a_path(raw, expected):
    assert clean_filename(raw) == expected


def test_clean_filename_is_length_limited():
    assert len(clean_filename("a" * 500 + ".pdf")) == 200
