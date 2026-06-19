"""Label-Erzeugung fuer das ML-Dataset.

Ein Trade-Kandidat beschreibt nur den ENTRY (Entry-Zeit, Ziel-Delta,
naked/Put-Spread). Das Label ist der REALE P&L dieses Kandidaten, simuliert durch
die bestehende Backtest-Engine -- dieselben Simulatoren, die der Backtest spaeter
handelt. Dadurch sind Trainings-Labels und Backtest garantiert konsistent (eine
einzige Quelle der Wahrheit fuer die Trade-Mechanik), statt die Fill-/Exit-Logik
hier zu duplizieren.

Die EXIT-Regel ist in dieser Phase fix (regelbasiert, Entscheidung #16) und wird
ueber ein ExitRule-Objekt hereingereicht; in einem Folgeschritt wird sie mitgelernt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

from ..backtest.engine import (
    _cutoff_time,
    _simulate_naked_entry,
    _simulate_spread_entry,
    _snapshot,
)
from ..backtest.params import StrategyParams
from ..backtest.trade import Trade


@dataclass
class ExitRule:
    """Fixe (regelbasierte) Exit-Regel fuer die Label-Simulation.

    Defaults entsprechen einer plausiblen 0-DTE-Short-Put-Regel; die konkreten
    Werte stammen spaeter aus der Grid-Search (bester Exit als Ausgangspunkt).
    """
    profit_target_pct: Optional[float] = 0.50
    stop_loss_multiplier: Optional[float] = 2.0
    time_exit_before_close_min: Optional[int] = 5
    slippage_pct_of_spread: float = 0.25
    commission_per_contract_leg: float = 1.10


@dataclass
class Candidate:
    """Ein Trade-Kandidat -- nur die Entry-Seite (die KI lernt diese Auswahl)."""
    entry_time: str                      # "HH:MM:SS"
    target_delta: float
    spread_type: str = "naked"           # "naked" | "put_spread"
    spread_width: Optional[float] = None  # Indexpunkte (nur put_spread)
    delta_low: float = 0.01
    delta_high: float = 0.50


def _params_for(candidate: Candidate, exit_rule: ExitRule) -> StrategyParams:
    """Baut die StrategyParams, mit denen die Engine genau diesen einen Kandidaten
    (eine Entry-Zeit, ein Trade) unter der fixen Exit-Regel simuliert."""
    return StrategyParams(
        target_delta=candidate.target_delta,
        delta_low=candidate.delta_low,
        delta_high=candidate.delta_high,
        entry_times=[candidate.entry_time],
        max_trades_per_day=1,
        max_concurrent_positions=1,
        profit_target_pct=exit_rule.profit_target_pct,
        stop_loss_multiplier=exit_rule.stop_loss_multiplier,
        time_exit_before_close_min=exit_rule.time_exit_before_close_min,
        slippage_pct_of_spread=exit_rule.slippage_pct_of_spread,
        commission_per_contract_leg=exit_rule.commission_per_contract_leg,
        spread_type=candidate.spread_type,
        spread_width=candidate.spread_width,
    )


def simulate_candidate(
    day_df: pd.DataFrame,
    date: int,
    candidate: Candidate,
    exit_rule: ExitRule,
) -> Tuple[Optional[Trade], pd.DataFrame]:
    """Simuliert einen Kandidaten und liefert (Trade | None, entry_snapshot).

    - Trade ist None, wenn zum Entry-Bar kein passender Strike existiert (kein
      Strike im Delta-Band bzw. -- beim Spread -- keine Long-Leg).
    - entry_snapshot ist die Optionskette zum Entry-Bar; sie wird auch bei
      Trade=None zurueckgegeben, damit der Aufrufer den Marktzustand kennt
      (Feature-Berechnung) und "nicht handelbar" von "Verlust-Trade" trennen kann.
    """
    params = _params_for(candidate, exit_rule)
    snapshot = _snapshot(day_df, candidate.entry_time)
    if snapshot.empty:
        return None, snapshot
    cutoff = _cutoff_time(day_df, exit_rule.time_exit_before_close_min)
    simulate = _simulate_spread_entry if candidate.spread_type == "put_spread" else _simulate_naked_entry
    trade = simulate(day_df, snapshot, date, params, cutoff)
    return trade, snapshot
