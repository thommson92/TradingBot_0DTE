"""Label-Erzeugung fuer das ML-Dataset.

Ein Trade-Kandidat beschreibt Entry (Entry-Zeit, Ziel-Delta, naked/Put-Spread)
UND -- seit Schritt 6 -- eine Exit-Regel (Profit-Target/Stop-Loss/Zeit-Exit). Das
Label ist der REALE P&L dieses Kandidaten, simuliert durch die bestehende
Backtest-Engine -- dieselben Simulatoren, die der Backtest spaeter handelt.
Dadurch sind Trainings-Labels und Backtest garantiert konsistent (eine einzige
Quelle der Wahrheit fuer die Trade-Mechanik), statt die Fill-/Exit-Logik hier zu
duplizieren.

Schritt 6 (gelernte Exits, Entscheidung #16): Die Exit-Regel wandert vom festen
ExitRule in eine zusaetzliche Achse des Kandidatenrasters (ExitSpec). Das Modell
scort dann (Entry x Exit)-Kombinationen, die Top-N-Policy waehlt implizit den
besten Exit je Marktlage. ExitRule traegt weiterhin die (nicht gelernten) Kosten
(Slippage/Kommission) und liefert den Default-Exit, wenn ein Kandidat keine
eigene ExitSpec hat.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

import pandas as pd

from ..backtest.engine import (
    _cutoff_time,
    _naked_exit_walk,
    _naked_setup,
    _naked_trade,
    _simulate_naked_entry,
    _simulate_spread_entry,
    _snapshot,
    _spread_exit_walk,
    _spread_setup,
    _spread_trade,
)
from ..backtest.params import StrategyParams
from ..backtest.trade import Trade


@dataclass
class ExitRule:
    """Fixe (regelbasierte) Exit-Regel + Kostenparameter fuer die Label-Simulation.

    Die drei Exit-Felder bilden den Default-Exit (genutzt, wenn ein Kandidat keine
    eigene ExitSpec hat); slippage/commission sind nicht gelernte Kostenparameter.
    """
    profit_target_pct: Optional[float] = 0.50
    stop_loss_multiplier: Optional[float] = 2.0
    time_exit_before_close_min: Optional[int] = 5
    slippage_pct_of_spread: float = 0.25
    commission_per_contract_leg: float = 1.10


@dataclass(frozen=True)
class ExitSpec:
    """Die *gelernte* Exit-Achse (Schritt 6): nur die drei Exit-Schwellen.

    None bedeutet jeweils 'deaktiviert' (kein Profit-Target / kein Stop / kein
    Zeit-Exit -> bis Verfall halten); die Werte sind hier immer explizit, daher
    keine Verwechslung mit 'Default benutzen' (das uebernimmt ExitRule).
    """
    profit_target_pct: Optional[float] = 0.50
    stop_loss_multiplier: Optional[float] = 2.0
    time_exit_before_close_min: Optional[int] = 5


@dataclass
class Candidate:
    """Ein Trade-Kandidat -- Entry-Seite plus optionale (gelernte) Exit-Achse.

    exit_spec=None  -> der Default-Exit aus der hereingereichten ExitRule gilt
                       (Rueckwaerts-kompatibel zu Schritt 1-5).
    exit_spec gesetzt -> diese ExitSpec ist massgeblich (Schritt 6).
    """
    entry_time: str                      # "HH:MM:SS"
    target_delta: float
    spread_type: str = "naked"           # "naked" | "put_spread"
    spread_width: Optional[float] = None  # Indexpunkte (nur put_spread)
    delta_low: float = 0.01
    delta_high: float = 0.50
    exit_spec: Optional[ExitSpec] = None


def effective_exit(candidate: Candidate, exit_rule: ExitRule) -> ExitSpec:
    """Die tatsaechlich wirksame Exit-Regel: die ExitSpec des Kandidaten, sonst der
    Default-Exit der ExitRule."""
    if candidate.exit_spec is not None:
        return candidate.exit_spec
    return ExitSpec(
        profit_target_pct=exit_rule.profit_target_pct,
        stop_loss_multiplier=exit_rule.stop_loss_multiplier,
        time_exit_before_close_min=exit_rule.time_exit_before_close_min,
    )


def _params_for(candidate: Candidate, exit_rule: ExitRule, spec: Optional[ExitSpec] = None) -> StrategyParams:
    """Baut die StrategyParams, mit denen die Engine genau diesen einen Kandidaten
    (eine Entry-Zeit, ein Trade) unter der wirksamen Exit-Regel simuliert."""
    spec = spec or effective_exit(candidate, exit_rule)
    return StrategyParams(
        target_delta=candidate.target_delta,
        delta_low=candidate.delta_low,
        delta_high=candidate.delta_high,
        entry_times=[candidate.entry_time],
        max_trades_per_day=1,
        max_concurrent_positions=1,
        profit_target_pct=spec.profit_target_pct,
        stop_loss_multiplier=spec.stop_loss_multiplier,
        time_exit_before_close_min=spec.time_exit_before_close_min,
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
    spec = effective_exit(candidate, exit_rule)
    cutoff = _cutoff_time(day_df, spec.time_exit_before_close_min)
    simulate = _simulate_spread_entry if candidate.spread_type == "put_spread" else _simulate_naked_entry
    trade = simulate(day_df, snapshot, date, params, cutoff)
    return trade, snapshot


def simulate_candidate_exits(
    day_df: pd.DataFrame,
    snapshot: pd.DataFrame,
    date: int,
    candidate: Candidate,
    exit_specs: List[ExitSpec],
    exit_rule: ExitRule,
) -> List[Tuple[ExitSpec, Optional[Trade]]]:
    """Simuliert EINEN Entry-Kandidaten unter MEHREREN Exit-Specs effizient.

    Entry (Strike-Wahl, Entry-Fill, Strike-Zeitreihe/Merge) haengt nicht von der
    Exit-Regel ab und wird daher genau einmal aufgebaut; je Exit-Spec wird nur der
    (billige) Exit-Walk wiederholt. Dieselbe check_exit-Logik wie im Backtest
    (eine Quelle der Wahrheit). Bei fehlendem Strike: Trade=None fuer jede Spec.

    `snapshot` wird hereingereicht (build_day_rows hat ihn ohnehin), `candidate`
    liefert nur die Entry-Achsen (sein exit_spec wird ignoriert).
    """
    base_params = _params_for(candidate, exit_rule, spec=exit_specs[0] if exit_specs else None)
    is_spread = candidate.spread_type == "put_spread"
    setup = _spread_setup(day_df, snapshot, base_params) if is_spread \
        else _naked_setup(day_df, snapshot, base_params)
    if setup is None:
        return [(spec, None) for spec in exit_specs]

    out: List[Tuple[ExitSpec, Optional[Trade]]] = []
    for spec in exit_specs:
        params = _params_for(candidate, exit_rule, spec=spec)
        cutoff = _cutoff_time(day_df, spec.time_exit_before_close_min)
        if is_spread:
            reason, cost, ts = _spread_exit_walk(setup, params, cutoff)
            trade = _spread_trade(setup, date, params, reason, cost, ts)
        else:
            reason, price, ts = _naked_exit_walk(setup, params, cutoff)
            trade = _naked_trade(setup, date, params, reason, price, ts)
        out.append((spec, trade))
    return out
