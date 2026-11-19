import numpy as np

from data_generator import noise

NOISE = {
    "scale": 1.0,
    "case_probs": {"as_is": 0.3, "upper": 0.35, "lower": 0.3, "random": 0.05},
    "typo_prob": 0.05,
    "abbrev_prob": 0.3,
    "prefix_prob": 0.25,
    "reference_prob": 0.25,
    "location_prob": 0.2,
}


def test_typo_is_a_single_character_edit() -> None:
    rng = np.random.default_rng(0)
    for _ in range(200):
        out = noise.apply_typo(rng, "kopi kenangan")
        assert abs(len(out) - len("kopi kenangan")) <= 1
        assert out != "" and out != "kopi kenangan" or out == "kopi kenangan"


def test_typo_leaves_very_short_text_alone() -> None:
    assert noise.apply_typo(np.random.default_rng(0), "kfc") == "kfc"


def test_description_is_deterministic_for_same_seed() -> None:
    def build(seed: int) -> list[str]:
        rng = np.random.default_rng(seed)
        return [
            noise.make_description(rng, "Kopi Kenangan", ("kpi knngn",), "qris", NOISE)
            for _ in range(50)
        ]

    assert build(1) == build(1)
    assert build(1) != build(2)


def test_description_never_empty_and_within_limit() -> None:
    rng = np.random.default_rng(3)
    for method in noise.PREFIXES:
        for _ in range(100):
            text = noise.make_description(rng, "Indomaret", (), method, NOISE)
            assert 1 <= len(text) <= 200


def test_zero_scale_returns_base_text_up_to_case() -> None:
    rng = np.random.default_rng(4)
    quiet = {**NOISE, "scale": 0.0, "case_probs": {"as_is": 1, "upper": 0, "lower": 0, "random": 0}}
    for _ in range(50):
        assert (
            noise.make_description(rng, "Alfamart", ("alfamrt",), "e_wallet", quiet) == "Alfamart"
        )


def test_prefix_matches_payment_method() -> None:
    rng = np.random.default_rng(5)
    always = {
        **NOISE,
        "prefix_prob": 1.0,
        "reference_prob": 0.0,
        "location_prob": 0.0,
        "typo_prob": 0.0,
        "abbrev_prob": 0.0,
        "case_probs": {"as_is": 1, "upper": 0, "lower": 0, "random": 0},
    }
    seen = {noise.make_description(rng, "Steam", (), "qris", always) for _ in range(60)}
    assert all(text.startswith(("QRIS Steam", "QR Steam")) for text in seen)
