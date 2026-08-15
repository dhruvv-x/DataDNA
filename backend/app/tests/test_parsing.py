import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from app.core.parsing import parse_csv, parse_json, parse_upload, ParseError


# --- CSV tests ---

def test_parse_csv_valid():
    raw = b"name,age\nAlice,30\nBob,25\n"
    records = parse_csv(raw)
    assert len(records) == 2
    assert records[0]["name"] == "Alice"
    assert records[1]["age"] == "25"


def test_parse_csv_empty_file_raises():
    with pytest.raises(ParseError):
        parse_csv(b"")


def test_parse_csv_headers_only_raises():
    with pytest.raises(ParseError):
        parse_csv(b"name,age\n")


def test_parse_csv_bad_encoding_raises():
    with pytest.raises(ParseError):
        parse_csv(b"\xff\xfe\x00\x01invalid")


# --- JSON tests ---

def test_parse_json_valid():
    raw = b'[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]'
    records = parse_json(raw)
    assert len(records) == 2
    assert records[0]["name"] == "Alice"


def test_parse_json_invalid_syntax_raises():
    with pytest.raises(ParseError):
        parse_json(b'{"name": "Alice",}')  # trailing comma, invalid JSON


def test_parse_json_not_a_list_raises():
    with pytest.raises(ParseError):
        parse_json(b'{"name": "Alice"}')  # top-level object, not array


def test_parse_json_empty_list_raises():
    with pytest.raises(ParseError):
        parse_json(b'[]')


def test_parse_json_non_object_items_raises():
    with pytest.raises(ParseError):
        parse_json(b'[1, 2, 3]')


# --- dispatch tests ---

def test_parse_upload_routes_csv():
    records = parse_upload("data.csv", b"name,age\nAlice,30\n")
    assert records[0]["name"] == "Alice"


def test_parse_upload_routes_json():
    records = parse_upload("data.json", b'[{"name": "Alice"}]')
    assert records[0]["name"] == "Alice"


def test_parse_upload_unsupported_extension_raises():
    with pytest.raises(ParseError):
        parse_upload("data.txt", b"some text")


def test_parse_upload_oversized_file_raises():
    huge = b"a" * (11 * 1024 * 1024)  # 11MB, over the 10MB limit
    with pytest.raises(ParseError):
        parse_csv(huge)
