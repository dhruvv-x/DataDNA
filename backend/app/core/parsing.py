"""
File parsing for DataDNA uploads.
Converts raw uploaded bytes (CSV or JSON) into an ordered list[dict].
Untrusted input: never assume well-formed data.
"""

import csv
import io
import json


class ParseError(Exception):
    """Raised when uploaded file content cannot be parsed into records."""
    pass


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB — HACKATHON SIMPLIFICATION


def parse_csv(raw_bytes: bytes) -> list:
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise ParseError(f"File exceeds max size of {MAX_FILE_SIZE_BYTES} bytes")

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ParseError(f"File is not valid UTF-8: {e}")

    reader = csv.DictReader(io.StringIO(text))
    records = list(reader)

    if not records:
        raise ParseError("CSV file contains no records")

    if reader.fieldnames is None or any(f is None or f == "" for f in reader.fieldnames):
        raise ParseError("CSV file has missing or malformed column headers")

    return records


def parse_json(raw_bytes: bytes) -> list:
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise ParseError(f"File exceeds max size of {MAX_FILE_SIZE_BYTES} bytes")

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ParseError(f"File is not valid UTF-8: {e}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}")

    if not isinstance(data, list):
        raise ParseError("JSON file must contain a top-level array of records")

    if not data:
        raise ParseError("JSON file contains no records")

    if not all(isinstance(r, dict) for r in data):
        raise ParseError("Every item in the JSON array must be an object")

    return data


def parse_upload(filename: str, raw_bytes: bytes) -> list:
    """
    Dispatch based on file extension.
    Returns ordered list[dict], ready for versioning.create_version().
    """
    lower = filename.lower()
    if lower.endswith(".csv"):
        return parse_csv(raw_bytes)
    elif lower.endswith(".json"):
        return parse_json(raw_bytes)
    else:
        raise ParseError(f"Unsupported file type: {filename}. Only .csv and .json are supported.")
