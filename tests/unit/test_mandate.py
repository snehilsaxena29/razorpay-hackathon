"""Every mandate validation rule, proven to raise.

An invalid mandate must not be constructible. If one were, every verdict
computed against it would be quietly wrong, which is the worst failure mode this
tool has.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gauntlet.errors import MandateError
from gauntlet.mandate import Mandate, Merchant, VelocityLimit, load_mandate, mandate_from_dict


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "mandate_id": "mnd_test",
        "principal": "test@example.com",
        "currency": "INR",
        "per_transaction_cap_minor": 500_000,
        "daily_cap_minor": 2_000_000,
        "velocity": VelocityLimit(max_payments=3, window_seconds=3600),
        "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
        "valid_until": datetime(2026, 12, 31, tzinfo=UTC),
    }
    base.update(overrides)
    return base


def test_valid_mandate_constructs() -> None:
    mandate = Mandate(**_kwargs())  # type: ignore[arg-type]
    assert mandate.mandate_id == "mnd_test"


def test_per_transaction_cap_above_daily_cap_raises() -> None:
    """A single permitted payment must not be able to breach the day."""
    with pytest.raises(MandateError, match="exceeds daily_cap_minor"):
        Mandate(**_kwargs(per_transaction_cap_minor=3_000_000))  # type: ignore[arg-type]


def test_cap_equal_to_daily_cap_is_allowed() -> None:
    """Boundary: equal caps are coherent — one payment may use the whole day."""
    mandate = Mandate(**_kwargs(per_transaction_cap_minor=2_000_000))  # type: ignore[arg-type]
    assert mandate.per_transaction_cap_minor == mandate.daily_cap_minor


def test_category_in_both_allowed_and_denied_raises() -> None:
    with pytest.raises(MandateError, match="both allowed and denied"):
        Mandate(
            **_kwargs(
                allowed_categories=frozenset({"crypto", "cloud_compute"}),
                denied_categories=frozenset({"crypto"}),
            )  # type: ignore[arg-type]
        )


def test_merchant_in_both_allowed_and_denied_raises() -> None:
    with pytest.raises(MandateError, match="both allowed and denied"):
        Mandate(
            **_kwargs(
                allowed_merchants=(Merchant("mrc_x", "X Ltd"),),
                denied_merchant_ids=frozenset({"mrc_x"}),
            )  # type: ignore[arg-type]
        )


def test_duplicate_merchant_ids_raise() -> None:
    with pytest.raises(MandateError, match="duplicate merchant ids"):
        Mandate(
            **_kwargs(
                allowed_merchants=(Merchant("mrc_x", "X Ltd"), Merchant("mrc_x", "X Limited"))
            )  # type: ignore[arg-type]
        )


def test_valid_from_after_valid_until_raises() -> None:
    with pytest.raises(MandateError, match="is not before"):
        Mandate(
            **_kwargs(
                valid_from=datetime(2026, 12, 31, tzinfo=UTC),
                valid_until=datetime(2026, 1, 1, tzinfo=UTC),
            )  # type: ignore[arg-type]
        )


def test_equal_validity_bounds_raise() -> None:
    """A zero-width validity window authorises nothing and is certainly a mistake."""
    same = datetime(2026, 6, 1, tzinfo=UTC)
    with pytest.raises(MandateError):
        Mandate(**_kwargs(valid_from=same, valid_until=same))  # type: ignore[arg-type]


@pytest.mark.parametrize("currency", ["inr", "RUPEE", "IN", "1NR", ""])
def test_malformed_currency_raises(currency: str) -> None:
    with pytest.raises(MandateError, match="currency"):
        Mandate(**_kwargs(currency=currency))  # type: ignore[arg-type]


def test_negative_cap_raises() -> None:
    with pytest.raises(MandateError, match="non-negative"):
        Mandate(**_kwargs(per_transaction_cap_minor=-1))  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["mandate_id", "principal"])
def test_empty_identity_field_raises(field: str) -> None:
    with pytest.raises(MandateError, match="non-empty"):
        Mandate(**_kwargs(**{field: "   "}))  # type: ignore[arg-type]


def test_zero_velocity_raises() -> None:
    with pytest.raises(MandateError, match="at least 1"):
        VelocityLimit(max_payments=0, window_seconds=3600)


def test_bool_cap_is_rejected_not_coerced_to_int() -> None:
    """bool is a subclass of int; a cap of True would silently become 1 paisa."""
    with pytest.raises(MandateError, match="must be an int"):
        Mandate(**_kwargs(per_transaction_cap_minor=True))  # type: ignore[arg-type]


def test_float_cap_from_toml_is_rejected() -> None:
    """Money is never a float, including at the point it enters the system."""
    with pytest.raises(MandateError, match="integer number of minor units"):
        mandate_from_dict(
            {
                "mandate_id": "m",
                "principal": "p@example.com",
                "currency": "INR",
                "per_transaction_cap_minor": 5000.0,
                "daily_cap_minor": 20000,
                "velocity": {"max_payments": 3, "window_seconds": 3600},
                "valid_from": "2026-01-01T00:00:00+00:00",
                "valid_until": "2026-12-31T00:00:00+00:00",
            }
        )


def test_missing_key_names_the_key() -> None:
    with pytest.raises(MandateError, match="missing required key"):
        mandate_from_dict({"mandate_id": "m"})


def test_load_mandate_missing_file_raises_mandate_error(tmp_path: object) -> None:
    with pytest.raises(MandateError, match="cannot read mandate"):
        load_mandate("does/not/exist.toml")


def test_load_mandate_malformed_toml_raises(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "bad.toml"
    path.write_text("mandate_id = [unclosed", encoding="utf-8")
    with pytest.raises(MandateError, match="malformed TOML"):
        load_mandate(path)


# ---- the shipped mandate ---------------------------------------------------


def test_shipped_mandate_loads(ops_mandate: Mandate) -> None:
    assert ops_mandate.mandate_id == "mnd_ops_default"
    assert ops_mandate.enforces_merchant_allowlist
    assert "mrc_aws_in" in ops_mandate.allowed_merchant_ids


def test_merchant_by_id_returns_none_for_unknown(ops_mandate: Mandate) -> None:
    assert ops_mandate.merchant_by_id("mrc_nonexistent") is None
    assert ops_mandate.merchant_by_id("mrc_aws_in") is not None


def test_render_for_agent_states_closed_by_default(ops_mandate: Mandate) -> None:
    """The agent must be told the mandate is closed, not infer it."""
    rendered = ops_mandate.render_for_agent()
    assert "closed by default" in rendered
    assert "₹5,000.00" in rendered
    assert "mrc_aws_in" in rendered


def test_render_for_agent_is_deterministic(ops_mandate: Mandate) -> None:
    """Set iteration order must not leak into what the agent sees."""
    assert ops_mandate.render_for_agent() == ops_mandate.render_for_agent()


def test_to_dict_sorts_collections(ops_mandate: Mandate) -> None:
    payload = ops_mandate.to_dict()
    assert payload["allowed_categories"] == sorted(payload["allowed_categories"])
    assert payload["denied_merchant_ids"] == sorted(payload["denied_merchant_ids"])
