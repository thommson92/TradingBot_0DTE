"""Leakage-sicheres Feature-Engineering fuer den ML-EV-Scorer.

Alle Features verwenden ausschliesslich Daten bis zum Entry-Bar
(timestamp <= entry_ts). Das Label (realer P&L) wird separat in labels.py aus der
Zukunft des Tages simuliert -- nur dort ist Blick in die Zukunft erlaubt.

Aufteilung in:
- market_features:    Marktzustand, unabhaengig vom Kandidaten (pro Bar einmal).
- candidate_features: kandidatenspezifisch (Ziel-Delta, gewaehlter Strike, Typ).
- compute_features:   beides kombiniert (waehlt den Strike via pick_strike).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.strategy import pick_strike

# Stabile Feature-Reihenfolge fuer Modelltraining/-inferenz.
MARKET_FEATURES = [
    "minute_of_day", "minutes_to_close", "day_of_week", "month",
    "underlying", "ret_since_open", "gap_open", "realized_vol_intraday",
    "atm_iv", "iv_skew",
]
CANDIDATE_FEATURES = [
    "cand_target_delta", "cand_is_spread", "cand_spread_width",
    "strike_delta", "strike_theta", "strike_vega", "strike_iv",
    "strike_dist_pct", "strike_mid",
]
FEATURE_COLUMNS = MARKET_FEATURES + CANDIDATE_FEATURES


def _nearest_by_abs_delta(puts: pd.DataFrame, target: float) -> Optional[pd.Series]:
    """Put mit |Delta| am naechsten zu target (z. B. 0.50 = ATM, 0.10 = Wing)."""
    if puts.empty:
        return None
    idx = (puts["delta"].abs() - target).abs().idxmin()
    return puts.loc[idx]


def _underlying_series(day_df: pd.DataFrame, entry_ts) -> pd.Series:
    """Ein Underlying-Kurs je Zeitstempel bis Entry (leakage-sicher, NaN entfernt)."""
    hist = day_df[day_df["timestamp"] <= entry_ts]
    s = (
        hist.dropna(subset=["underlying_price"])
        .groupby("timestamp")["underlying_price"]
        .first()
        .sort_index()
    )
    return s


def market_features(
    day_df: pd.DataFrame,
    snapshot: pd.DataFrame,
    entry_ts,
    prev_close: Optional[float],
) -> dict:
    """Kandidatenunabhaengiger Marktzustand zum Entry-Bar."""
    und = _underlying_series(day_df, entry_ts)
    underlying = float(und.iloc[-1]) if len(und) else np.nan
    open_underlying = float(und.iloc[0]) if len(und) else np.nan

    # Realisierte Intraday-Vola: Std der Minuten-Log-Returns des Underlyings bis Entry.
    if len(und) >= 3:
        logret = np.diff(np.log(und.to_numpy()))
        realized_vol = float(np.std(logret, ddof=1))
    else:
        realized_vol = np.nan

    ret_since_open = (underlying / open_underlying - 1.0) if open_underlying else np.nan
    gap_open = (
        open_underlying / prev_close - 1.0
        if (prev_close and open_underlying and not np.isnan(open_underlying))
        else np.nan
    )

    puts = snapshot[snapshot["right"] == "PUT"]
    atm = _nearest_by_abs_delta(puts, 0.50)
    iv10 = _nearest_by_abs_delta(puts, 0.10)
    iv30 = _nearest_by_abs_delta(puts, 0.30)
    atm_iv = float(atm["implied_vol"]) if atm is not None else np.nan
    iv_skew = (
        float(iv10["implied_vol"]) - float(iv30["implied_vol"])
        if (iv10 is not None and iv30 is not None)
        else np.nan
    )

    ts = pd.Timestamp(entry_ts)
    session_open = pd.Timestamp(und.index[0]) if len(und) else ts
    minute_of_day = (ts - session_open).total_seconds() / 60.0
    close_ts = pd.Timestamp(day_df["timestamp"].max())
    minutes_to_close = (close_ts - ts).total_seconds() / 60.0

    return {
        "minute_of_day": minute_of_day,
        "minutes_to_close": minutes_to_close,
        "day_of_week": float(ts.dayofweek),
        "month": float(ts.month),
        "underlying": underlying,
        "ret_since_open": ret_since_open,
        "gap_open": gap_open,
        "realized_vol_intraday": realized_vol,
        "atm_iv": atm_iv,
        "iv_skew": iv_skew,
    }


def candidate_features(entry_row: Optional[pd.Series], candidate, underlying: float) -> dict:
    """Kandidatenspezifische Features inkl. Greeks des gewaehlten Short-Strikes."""
    is_spread = 1.0 if candidate.spread_type == "put_spread" else 0.0
    feats = {
        "cand_target_delta": float(candidate.target_delta),
        "cand_is_spread": is_spread,
        "cand_spread_width": float(candidate.spread_width) if (is_spread and candidate.spread_width) else 0.0,
        "strike_delta": np.nan,
        "strike_theta": np.nan,
        "strike_vega": np.nan,
        "strike_iv": np.nan,
        "strike_dist_pct": np.nan,
        "strike_mid": np.nan,
    }
    if entry_row is not None:
        feats["strike_delta"] = float(abs(entry_row["delta"]))
        feats["strike_theta"] = float(entry_row.get("theta", np.nan))
        feats["strike_vega"] = float(entry_row.get("vega", np.nan))
        feats["strike_iv"] = float(entry_row.get("implied_vol", np.nan))
        feats["strike_mid"] = float((entry_row["bid"] + entry_row["ask"]) / 2.0)
        if underlying and not np.isnan(underlying):
            feats["strike_dist_pct"] = float((underlying - entry_row["strike"]) / underlying)
    return feats


def compute_features(
    day_df: pd.DataFrame,
    snapshot: pd.DataFrame,
    entry_ts,
    candidate,
    prev_close: Optional[float],
) -> dict:
    """Vollstaendiger Feature-Vektor (Markt + Kandidat) fuer einen Kandidaten.

    Der Short-Strike wird mit derselben pick_strike-Logik gewaehlt wie im Backtest,
    damit Features und Label denselben Strike beschreiben.
    """
    mf = market_features(day_df, snapshot, entry_ts, prev_close)
    entry_row = pick_strike(snapshot, candidate.target_delta, candidate.delta_low, candidate.delta_high)
    cf = candidate_features(entry_row, candidate, mf["underlying"])
    return {**mf, **cf}
