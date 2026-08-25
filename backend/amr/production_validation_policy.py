"""Frozen policy primitives for full-market OOS financial-factor validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Side = Literal["buy", "sell"]
CostScenario = Literal["base", "stress"]


@dataclass(frozen=True)
class DateEffectiveCostSchedule:
    """Research execution-cost schedule in basis points of traded notional.

    Broker commission is an explicit research assumption inclusive of exchange
    handling and regulatory fees. Stamp duty and transfer fees follow their
    historical effective dates. Slippage is scenario-based, not calibrated.
    """

    broker_commission_bps: float = 3.0
    base_slippage_bps: float = 5.0
    stress_slippage_bps: float = 10.0

    @staticmethod
    def stamp_duty_bps(trade_date: date, side: Side) -> float:
        if side == "buy":
            return 0.0
        return 5.0 if trade_date >= date(2023, 8, 28) else 10.0

    @staticmethod
    def transfer_fee_bps(trade_date: date) -> float:
        return 0.1 if trade_date >= date(2022, 4, 29) else 0.2

    def total_bps(
        self,
        trade_date: date,
        side: Side,
        scenario: CostScenario = "base",
    ) -> float:
        if side not in ("buy", "sell"):
            raise ValueError(f"unsupported side: {side}")
        if scenario == "base":
            slippage = self.base_slippage_bps
        elif scenario == "stress":
            slippage = self.stress_slippage_bps
        else:
            raise ValueError(f"unsupported cost scenario: {scenario}")
        return (
            self.broker_commission_bps
            + self.transfer_fee_bps(trade_date)
            + self.stamp_duty_bps(trade_date, side)
            + slippage
        )


FULL_MARKET_COST_SCHEDULE_V1 = DateEffectiveCostSchedule()
