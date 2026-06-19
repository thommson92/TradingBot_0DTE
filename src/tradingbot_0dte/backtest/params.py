"""Strategie-Parameter fuer den Backtest (nackter Short Put)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..config import Config


@dataclass
class StrategyParams:
    target_delta: float
    delta_low: float
    delta_high: float
    entry_times: List[str] = field(default_factory=lambda: ["09:35:00"])
    max_trades_per_day: Optional[int] = 1
    max_concurrent_positions: int = 1
    profit_target_pct: Optional[float] = 0.30
    stop_loss_multiplier: Optional[float] = 2.0
    time_exit_before_close_min: Optional[int] = 5
    slippage_pct_of_spread: float = 0.25
    commission_per_contract_leg: float = 1.10
    spread_type: str = "naked"  # "naked" oder "put_spread"
    spread_width: Optional[float] = None  # Indexpunkte Abstand der Long-Leg (nur put_spread)


def params_from_config(cfg: Config) -> StrategyParams:
    s = cfg.strategy
    return StrategyParams(
        target_delta=s.target_delta,
        delta_low=s.delta_low,
        delta_high=s.delta_high,
        entry_times=list(s.entry_times),
        max_trades_per_day=s.max_trades_per_day,
        max_concurrent_positions=s.max_concurrent_positions,
        profit_target_pct=s.profit_target_pct,
        stop_loss_multiplier=s.stop_loss_multiplier,
        time_exit_before_close_min=s.time_exit_before_close_min,
        slippage_pct_of_spread=s.slippage_pct_of_spread,
        commission_per_contract_leg=s.commission_per_contract_leg,
        spread_type=s.spread_type,
        spread_width=s.spread_width,
    )
