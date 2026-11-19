"""Pure helpers behind the transactions API (PRD 7.2.1, 13.1.4, 17.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from app.core.cursor import Cursor, decode_cursor, encode_cursor
from app.core.errors import ProblemError
from app.core.text import clean_text, mask_long_numbers
from app.schemas.transactions import (
    TransactionCreate,
    TransactionUpdate,
    normalize_payment_method,
    parse_amount,
    parse_when,
)
from app.services.idempotency import request_hash, validate_key
from pydantic import ValidationError

SECRET = "c" * 32
USER = uuid.uuid4()


def test_fr_02_amount_parsing_is_decimal_exact() -> None:
    assert parse_amount("25000.50") == Decimal("25000.50")
    assert parse_amount(25000.5) == Decimal("25000.5")
    assert parse_amount(10) == Decimal(10)
    for bad in (0, -1, "0.00", "x", "1.001", True, None, [], "NaN", "Infinity", "1e999999"):
        with pytest.raises(ValueError, match="INVALID_AMOUNT"):
            parse_amount(bad)
    with pytest.raises(ValueError):
        parse_amount(0.1 + 0.2)  # float noise is rejected, not rounded


def test_fr_02_date_parsing() -> None:
    assert parse_when("2026-11-01") == dt.date(2026, 11, 1)
    assert isinstance(parse_when("2026-11-01"), dt.date) and not isinstance(
        parse_when("2026-11-01"), dt.datetime
    )
    assert parse_when("2026-11-01T10:00:00+07:00").utcoffset() == dt.timedelta(hours=7)  # type: ignore[union-attr]
    assert parse_when("2026-11-01T10:00:00Z").tzinfo is not None  # type: ignore[union-attr]
    for bad in ("01/11/2026", "2026-13-01", "", 5, None, "tomorrow"):
        with pytest.raises(ValueError, match="INVALID_DATE"):
            parse_when(bad)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("E-Wallet", "e_wallet"),
        ("ewallet", "e_wallet"),
        (" bank ", "bank_transfer"),
        ("CARD", "debit_card"),
        ("qr", "qris"),
        ("credit card", "credit_card"),
        ("cash", "cash"),
    ],
)
def test_4_7_payment_method_aliases(raw: str, expected: str) -> None:
    assert normalize_payment_method(raw) == expected


def test_4_7_unknown_payment_method_is_rejected() -> None:
    for bad in ("bitcoin", "", None, 3):
        with pytest.raises(ValueError, match="INVALID_PAYMENT_METHOD"):
            normalize_payment_method(bad)


def test_fr_02_create_schema_forbids_server_fields() -> None:
    ok = TransactionCreate(
        transaction_type="expense", amount="1", description="x", transaction_date="2026-01-01"
    )
    assert ok.payment_method == "other" and ok.category is None
    for extra in ("user_id", "id", "category_status", "source", "version"):
        with pytest.raises(ValidationError):
            TransactionCreate(
                transaction_type="expense",
                amount="1",
                description="x",
                transaction_date="2026-01-01",
                **{extra: "v"},
            )  # type: ignore[arg-type]


def test_fr_02_update_schema_tracks_which_fields_were_sent() -> None:
    patch = TransactionUpdate(notes=None)
    assert patch.model_fields_set == {"notes"}
    assert TransactionUpdate().model_fields_set == set()


def test_17_2_masking_and_control_characters() -> None:
    assert mask_long_numbers("kartu 4111111111111111 ok") == "kartu ****1111 ok"
    assert mask_long_numbers("4111-1111-1111-1111") == "****1111"
    assert mask_long_numbers("order 12345678") == "order 12345678"  # < 13 digits
    assert (
        mask_long_numbers("12345678901234567890") == "12345678901234567890"
    )  # 20 digits: not a card
    assert clean_text("  a\x00b\tc\n ") == "a b c"
    assert clean_text("a\nb", keep_newlines=True) == "a\nb"


def test_13_1_4_cursor_round_trip_and_tamper_detection() -> None:
    cursor = Cursor("date", "2026-11-01T00:00:00+00:00", uuid.uuid4())
    token = encode_cursor(cursor, USER, SECRET)
    assert decode_cursor(token, USER, SECRET, "date") == cursor
    for bad in (token + "A", token[:-2], "x.y", "", token.replace(".", "")):
        with pytest.raises(ProblemError) as exc:
            decode_cursor(bad, USER, SECRET, "date")
        assert exc.value.code == "INVALID_CURSOR" and exc.value.status == 400
    for args in (
        (uuid.uuid4(), SECRET, "date"),
        (USER, "d" * 32, "date"),
        (USER, SECRET, "amount"),
    ):
        with pytest.raises(ProblemError):
            decode_cursor(token, *args)  # wrong owner, wrong key, wrong sort


def test_13_1_5_request_hash_is_order_independent_and_sensitive() -> None:
    a = request_hash("POST", "/x", {"a": 1, "b": 2})
    assert a == request_hash("POST", "/x", {"b": 2, "a": 1})
    assert a != request_hash("POST", "/x", {"a": 1, "b": 3})
    assert a != request_hash("POST", "/y", {"a": 1, "b": 2})
    assert a != request_hash("PATCH", "/x", {"a": 1, "b": 2})


def test_13_1_5_idempotency_key_validation() -> None:
    assert validate_key("a" * 8, required=True) == "a" * 8
    assert validate_key(None, required=False) is None
    for bad in (None, "", "a" * 7, "a" * 129):
        with pytest.raises(ProblemError):
            validate_key(bad, required=True)
    with pytest.raises(ProblemError):
        validate_key("short", required=False)
