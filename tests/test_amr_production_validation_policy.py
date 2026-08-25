from datetime import date

import pytest

from backend.amr.production_validation_policy import FULL_MARKET_COST_SCHEDULE_V1


def test_transfer_fee_effective_date_boundary():
    policy = FULL_MARKET_COST_SCHEDULE_V1
    assert policy.transfer_fee_bps(date(2022, 4, 28)) == 0.2
    assert policy.transfer_fee_bps(date(2022, 4, 29)) == 0.1


def test_stamp_duty_effective_date_boundary_and_sell_only():
    policy = FULL_MARKET_COST_SCHEDULE_V1
    assert policy.stamp_duty_bps(date(2023, 8, 27), "sell") == 10.0
    assert policy.stamp_duty_bps(date(2023, 8, 28), "sell") == 5.0
    assert policy.stamp_duty_bps(date(2023, 8, 28), "buy") == 0.0


def test_base_cost_totals_do_not_double_count_exchange_fees():
    policy = FULL_MARKET_COST_SCHEDULE_V1
    assert policy.total_bps(date(2021, 1, 1), "buy") == pytest.approx(8.2)
    assert policy.total_bps(date(2021, 1, 1), "sell") == pytest.approx(18.2)
    assert policy.total_bps(date(2024, 1, 1), "buy") == pytest.approx(8.1)
    assert policy.total_bps(date(2024, 1, 1), "sell") == pytest.approx(13.1)


def test_stress_scenario_adds_five_bps_per_side():
    policy = FULL_MARKET_COST_SCHEDULE_V1
    base = policy.total_bps(date(2024, 1, 1), "sell", "base")
    stress = policy.total_bps(date(2024, 1, 1), "sell", "stress")
    assert stress - base == pytest.approx(5.0)


def test_unknown_side_or_scenario_fails_closed():
    policy = FULL_MARKET_COST_SCHEDULE_V1
    with pytest.raises(ValueError):
        policy.total_bps(date(2024, 1, 1), "hold")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        policy.total_bps(date(2024, 1, 1), "buy", "optimistic")  # type: ignore[arg-type]
