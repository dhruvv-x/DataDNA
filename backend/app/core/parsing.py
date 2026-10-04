"""
File parsing for DataDNA uploads.
Converts raw uploaded bytes (CSV or JSON) into an ordered list[dict].
Untrusted input: never assume well-formed data. Anything odd raises ParseError
so the upload fails visibly (HTTP 422) instead of being stored in a damaged form.
"""

import csv
import io
import json


class ParseError(Exception):
    """Raised when uploaded file content cannot be parsed into records."""
    pass


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


def _decode(raw_bytes: bytes) -> str:
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise ParseError(f"File exceeds max size of {MAX_FILE_SIZE_BYTES} bytes")
    try:
        # utf-8-sig drops the BOM that Excel adds, so the first header stays clean.
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ParseError(f"File is not valid UTF-8: {e}")


def _validate_header(header: list) -> list:
    header = [h.strip() for h in header]
    if any(h == "" for h in header):
        raise ParseError("CSV file has missing or malformed column headers")
    seen = set()
    for h in header:
        if h in seen:
            raise ParseError(f"CSV file has a duplicate column header: '{h}'")
        seen.add(h)
    return header


def parse_csv(raw_bytes: bytes) -> list:
    """
    Strict CSV parsing.
    - Header cells must be non-empty and unique (whitespace is stripped).
    - A row with MORE values than the header is rejected (the extra values
      would otherwise be lost or crash later).
    - A row with FEWER values is allowed; missing cells become None.
    - Completely blank lines are skipped.
    """
    text = _decode(raw_bytes)
    reader = csv.reader(io.StringIO(text))

    header = None
    records = []
    try:
        for row in reader:
            if header is None:
                if not row:
                    continue
                header = _validate_header(row)
                continue

            if not row or (len(row) == 1 and not row[0].strip()):
                continue

            if len(row) > len(header):
                raise ParseError(
                    f"Row at line {reader.line_num} has {len(row)} values "
                    f"but the header has {len(header)} columns"
                )
            padded = row + [None] * (len(header) - len(row))
            records.append(dict(zip(header, padded)))
    except csv.Error as e:
        raise ParseError(f"Malformed CSV near line {reader.line_num}: {e}")

    if header is None:
        raise ParseError("CSV file is empty")
    if not records:
        raise ParseError("CSV file contains no records")

    return records


def parse_json(raw_bytes: bytes) -> list:
    text = _decode(raw_bytes)

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
    Returns ordered list[dict], ready for versioning.
    """
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        return parse_csv(raw_bytes)
    elif lower.endswith(".json"):
        return parse_json(raw_bytes)
    else:
        raise ParseError(f"Unsupported file type: {filename}. Only .csv and .json are supported.")
