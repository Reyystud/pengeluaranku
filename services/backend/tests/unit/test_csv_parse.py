"""CSV cell and file parsing (PRD 7.2.3). Pure functions."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from app.core.csvparse import (
    CellError,
    CsvFileError,
    decode,
    detect_delimiter,
    parse_amount,
    parse_date,
    parse_type,
    read_table,
)
from app.services.imports import safe_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("25000", "25000"),
        ("25000.50", "25000.50"),
        ("25000.5", "25000.5"),
        ("Rp 25.000", "25000"),
        ("rp25.000", "25000"),
        ("IDR 1.500.000", "1500000"),
        ("Rp. 1.500.000", "1500000"),
        ("1.500", "1500"),
        ("25.00", "25.00"),
        (" 100 ", "100"),
    ],
)
def test_fr_02_06_amount_formats(raw: str, expected: str) -> None:
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw", ["-5000", "0", "0.00", "abc", "", "1,500", "1.5000", "12.34.567", "1.500.00", "Rp"]
)
def test_fr_02_06_amount_rejects(raw: str) -> None:
    with pytest.raises(CellError) as exc:
        parse_amount(raw)
    assert exc.value.code == "INVALID_AMOUNT"


def test_fr_02_06_negative_amount_hints_at_type() -> None:
    with pytest.raises(CellError) as exc:
        parse_amount("-5000")
    assert "type=expense" in exc.value.message


def test_fr_02_06_date_formats() -> None:
    assert parse_date("2026-11-01") == dt.date(2026, 11, 1)
    assert parse_date("2026-11-01 08:05") == dt.datetime(2026, 11, 1, 8, 5)
    assert parse_date("2026-11-01 08:05:09") == dt.datetime(2026, 11, 1, 8, 5, 9)
    assert parse_date("01/11/2026") == dt.date(2026, 11, 1)
    assert parse_date("13/11/2026 18:30") == dt.datetime(2026, 11, 13, 18, 30)
    assert not isinstance(parse_date("01/11/2026"), dt.datetime)


@pytest.mark.parametrize(
    "raw",
    ["11/13/2026", "2026/11/01", "2026-13-01", "31/02/2026", "1 Nov 2026", "", "2026-11-01T08:00"],
)
def test_fr_02_06_date_rejects_ambiguous_and_invalid(raw: str) -> None:
    with pytest.raises(CellError) as exc:
        parse_date(raw)
    assert exc.value.code == "INVALID_DATE"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("income", "income"),
        ("EXPENSE", "expense"),
        (" in ", "income"),
        ("credit", "income"),
        ("out", "expense"),
        ("debit", "expense"),
        ("transfer", "transfer"),
    ],
)
def test_fr_02_06_type_aliases(raw: str, expected: str) -> None:
    assert parse_type(raw) == expected


def test_fr_02_06_type_rejects() -> None:
    with pytest.raises(CellError) as exc:
        parse_type("refund")
    assert exc.value.code == "INVALID_TYPE"


def test_fr_02_10_decode_tolerates_bom_and_rejects_non_utf8() -> None:
    assert decode(b"\xef\xbb\xbfdate,amount") == "date,amount"
    with pytest.raises(CsvFileError) as exc:
        decode("café".encode("latin-1"))
    assert exc.value.code == "INVALID_ENCODING" and exc.value.status == 422


def test_fr_02_06_delimiter_detection() -> None:
    assert detect_delimiter("date;description;amount;type") == ";"
    assert detect_delimiter("date,description,amount,type") == ","
    assert detect_delimiter("date,description;x") == ","


def test_fr_02_06_read_table_headers_rows_and_numbers() -> None:
    text = (
        " Date ;DESCRIPTION;Amount;Type;Extra\r\n"
        "\r\n"
        "2026-11-01;Kopi;25000;expense;x\r\n"
        "   ;  ;  ;  \r\n"
        '2026-11-02;"Makan; siang";30000;expense\r\n'
    )
    table = read_table(text, max_rows=10)
    assert table.delimiter == ";"
    assert table.columns == ["date", "description", "amount", "type"]
    assert table.unknown_columns == ["extra"]
    assert [n for n, _ in table.rows] == [3, 5]  # header is row 1, blank lines are skipped
    assert table.rows[1][1]["description"] == "Makan; siang"
    assert table.rows[1][1].get("extra") is None  # short rows do not crash


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "EMPTY_FILE"),
        ("\n  \n", "EMPTY_FILE"),
        ("date,description,amount\n2026-11-01,x,1", "MISSING_COLUMNS"),
    ],
)
def test_fr_02_10_file_level_errors(text: str, code: str) -> None:
    with pytest.raises(CsvFileError) as exc:
        read_table(text, max_rows=10)
    assert exc.value.code == code and exc.value.status == 422


def test_fr_02_10_row_limit() -> None:
    body = "date,description,amount,type\n" + "2026-11-01,x,1,expense\n" * 4
    assert len(read_table(body, max_rows=4).rows) == 4
    with pytest.raises(CsvFileError) as exc:
        read_table(body, max_rows=3)
    assert exc.value.code == "TOO_MANY_ROWS"


def test_fr_02_10_malformed_csv_is_a_file_error() -> None:
    huge = "date,description,amount,type\n2026-11-01," + '"' + "x" * 200_000 + '",1,expense\n'
    with pytest.raises(CsvFileError) as exc:
        read_table(huge, max_rows=10)
    assert exc.value.code == "INVALID_CSV"


def test_17_filename_is_sanitized() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\x\\bank statement (1).csv") == "bank statement (1).csv"
    assert safe_filename("a\x00b<script>.csv") == "a b_script_.csv"
    assert safe_filename(None) == "upload.csv"
    assert len(safe_filename("a" * 400 + ".csv")) <= 255
