"""Tests for merchant normalization and description preprocessing (PRD 7.3.2, 7.3.3; T-07)."""

from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from ml.config import load_aliases
from ml.preprocessing import (
    derive_merchant,
    derive_merchant_key,
    normalize_merchant,
    preprocess_description,
    resolve_merchant,
)

CASES = [
    # step 1: NFKC + lowercase
    ("KOPI KENANGAN", "kopi kenangan"),
    ("ＫＯＰＩ Kenangan", "kopi kenangan"),
    ("  Warteg   Bahari  ", "warteg bahari"),
    # step 2: payment prefixes / suffixes
    ("QRIS Mie Gacoan", "mie gacoan"),
    ("QR Mie Gacoan", "mie gacoan"),
    ("POS Hypermart", "hypermart"),
    ("EDC Hypermart", "hypermart"),
    ("DEBIT Hypermart", "hypermart"),
    ("PURCHASE Zara", "zara"),
    ("TRF Budi Santoso", "budi santoso"),
    ("TRANSFER KE Budi Santoso", "budi santoso"),
    ("PEMBAYARAN Listrik PLN", "listrik pln"),
    ("PAYMENT Netflix", "netflix"),
    ("BYR Spotify", "spotify"),
    ("Spotify QRIS", "spotify"),
    ("pmb telkomsel", "telkomsel"),
    ("pos", "pos"),  # a lone prefix word is kept: nothing else to return
    ("Kantor Pos", "kantor"),  # known limitation: "pos" is stripped at the edges (PRD 7.3.2)
    ("Mall Pos Kota", "mall pos kota"),  # but not in the middle
    ("Trans Jakarta", "transjakarta"),  # alias that ends in a city word
    # step 3: platform wrappers
    ("GOPAY*Kopi Kenangan", "kopi kenangan"),
    ("SHOPEEPAY - Indomaret", "indomaret"),
    ("OVO/SHOPEEFOOD", "shopeefood"),
    ("DANA MIE GACOAN", "mie gacoan"),
    ("dana", "dana"),  # wrapper word alone is the merchant
    ("TRF DANA Budi", "budi"),  # prefix then wrapper
    # step 4: reference numbers
    ("Starbucks #12345", "starbucks"),
    ("Gojek 9876543210", "gojek"),
    ("Gojek INV/2025/1234567", "gojek"),
    ("Tokopedia 12/03/2025", "tokopedia"),
    ("7 Eleven", "7 eleven"),  # short digit runs stay
    # step 5: locations, branches, cities
    ("Indomaret - JKT SELATAN", "indomaret"),
    ("Indomaret @ BSD", "indomaret"),
    ("Alfamart CAB 12", "alfamart"),
    ("Alfamart Outlet 7 Depok", "alfamart"),
    ("Mie Gacoan Bandung", "mie gacoan"),
    ("Soto Surabaya", "soto"),
    ("Jakarta", "jakarta"),  # nothing left to keep
    # step 6: punctuation
    ("Mc.Donald's", "mc donald s"),
    ("A&W", "a w"),
    # step 7: aliases
    ("Indomart", "indomaret"),
    ("ALFA MART", "alfamart"),
    ("Gojek GoRide", "gojek"),
    ("kpi knngn", "kopi kenangan"),
    ("SBUX", "starbucks"),
    # step 8 and empties
    ("", ""),
    ("   ", ""),
    ("QRIS 12345678", ""),
]


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_fr_03_normalize_merchant_cases(raw: str, expected: str) -> None:
    assert normalize_merchant(raw) == expected


def test_fr_03_at_least_30_cases() -> None:
    assert len(CASES) >= 30


def test_fr_03_truncates_to_64_chars() -> None:
    result = normalize_merchant("warung " + "makan " * 30)
    assert len(result) <= 64
    assert result == result.rstrip()


def test_fr_03_is_deterministic() -> None:
    assert normalize_merchant("GOPAY*Kopi Kenangan") == normalize_merchant("GOPAY*Kopi Kenangan")


def test_fr_03_aliases_are_not_chained() -> None:
    aliases = load_aliases()
    assert not set(aliases) & set(aliases.values())
    for alias, canonical in aliases.items():
        assert normalize_merchant(alias) == canonical


@given(st.text(max_size=200))
def test_fr_03_never_raises_and_output_is_clean(raw: str) -> None:
    out = normalize_merchant(raw)
    assert len(out) <= 64
    assert out == out.strip()
    assert "  " not in out
    assert all(ch.isalnum() or ch == " " for ch in out)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Gojek INV/2025/1234567 PAYMENT", "gojek payment"),
        ("Indomaret #12345  Jakarta", "indomaret jakarta"),
        ("QRIS  MIE   GACOAN 12/03/2025", "qris mie gacoan"),
        ("ＫＯＰＩ 99999", "kopi"),
        ("kopi kenangn", "kopi kenangn"),  # typos are NOT corrected
    ],
)
def test_fr_03_preprocess_description(raw: str, expected: str) -> None:
    assert preprocess_description(raw) == expected


def test_fr_03_derived_merchant_and_key() -> None:
    assert derive_merchant("QRIS warung makan sederhana 123456") == "Warung Makan"
    assert derive_merchant_key("QRIS warung makan sederhana bu tini") == "warung makan sederhana"
    assert derive_merchant("") == ""


def test_fr_03_resolve_merchant_prefers_given_value() -> None:
    assert resolve_merchant("Indomart", "whatever") == ("Indomart", "indomaret")
    assert resolve_merchant(None, "GOPAY*Kopi Kenangan") == ("Kopi Kenangan", "kopi kenangan")
    assert resolve_merchant("   ", "TRF Budi Santoso") == ("Budi Santoso", "budi santoso")


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "v1" / "transactions.parquet"


@pytest.mark.skipif(not DATA.exists(), reason="needs data/synthetic/v1 (make data)")
def test_fr_03_agreement_with_true_merchant_on_synthetic_data() -> None:
    """Misses come from the generator's injected typos, which are intentionally not corrected."""
    tx = pd.read_parquet(DATA, columns=["description", "true_merchant"]).iloc[::40]
    got = tx["description"].map(normalize_merchant)
    want = tx["true_merchant"].map(normalize_merchant)
    assert (got == want).mean() > 0.90
