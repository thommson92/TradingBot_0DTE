"""Datenqualitaets-Check der historisierten Parquet-Daten (ThetaData v3).

Prueft pro Tag Bar-Abdeckung und Strike-Anzahl und sucht fehlende Handelstage
(Luecken an Werktagen). Liefert ein Summary-DataFrame + Auffaelligkeiten.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import Config
from .storage import MarketData

log = logging.getLogger(__name__)

_INTERVAL_UNITS = [("ms", 0.001), ("s", 1.0), ("m", 60.0), ("h", 3600.0)]


def _to_date(yyyymmdd: int) -> dt.date:
    s = str(int(yyyymmdd))
    return dt.date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def interval_seconds(interval: str) -> Optional[float]:
    s = interval.strip().lower()
    if s == "tick":
        return None
    for unit, factor in _INTERVAL_UNITS:  # 'ms' vor 's'/'m' pruefen
        if s.endswith(unit):
            try:
                return float(s[: -len(unit)]) * factor
            except ValueError:
                return None
    return None


def _time_seconds(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def expected_bars(cfg: Config) -> Optional[int]:
    ivl = interval_seconds(cfg.data.interval)
    if not ivl:
        return None
    span = _time_seconds(cfg.data.end_time) - _time_seconds(cfg.data.start_time)
    return int(span // ivl) + 1


def per_day_summary(cfg: Config) -> pd.DataFrame:
    md = MarketData(cfg)
    if not md.available_dates():
        md.close()
        return pd.DataFrame()
    try:
        sql = (
            "SELECT date, "
            "COUNT(*) AS rows, "
            "COUNT(DISTINCT strike) AS strikes, "
            "COUNT(DISTINCT timestamp) AS bars, "
            "MIN(timestamp) AS first_ts, "
            "MAX(timestamp) AS last_ts "
            "FROM {scan} GROUP BY date ORDER BY date"
        )
        df = md.query(sql)
    finally:
        md.close()

    if df.empty:
        return df

    exp_bars = expected_bars(cfg)
    if exp_bars:
        df["bars_expected"] = exp_bars
        df["coverage"] = (df["bars"] / exp_bars).round(3)
    return df


def missing_trading_days(dates: List[int]) -> List[Tuple[int, int, int]]:
    """Sucht Werktags-Luecken zwischen aufeinanderfolgenden vorhandenen Tagen.

    Rueckgabe: Liste (vorher, nachher, fehlende_werktage). Feiertage koennen
    hier als 'fehlend' erscheinen — Heuristik, kein Boersenkalender.
    """
    out: List[Tuple[int, int, int]] = []
    ds = sorted(dates)
    for prev, cur in zip(ds, ds[1:]):
        gap = int(np.busday_count(_to_date(prev), _to_date(cur)))
        if gap > 1:
            out.append((prev, cur, gap - 1))
    return out


def run_quality_report(cfg: Config, min_coverage: float = 0.9) -> pd.DataFrame:
    summary = per_day_summary(cfg)
    if summary.empty:
        print("Keine Daten gefunden — wurde der Download schon ausgefuehrt?")
        return summary

    n = len(summary)
    has_cov = "coverage" in summary.columns
    print("=== Datenqualitaet ===")
    print("Tage gespeichert : %d (%d bis %d)"
          % (n, int(summary["date"].min()), int(summary["date"].max())))
    if has_cov:
        print("Bars/Tag erwartet: %d" % int(summary["bars_expected"].iloc[0]))
    print("Strikes/Tag      : min %d, median %d, max %d"
          % (summary["strikes"].min(), int(summary["strikes"].median()), summary["strikes"].max()))
    if has_cov:
        print("Abdeckung        : min %.2f, median %.2f"
              % (summary["coverage"].min(), summary["coverage"].median()))

    if has_cov:
        low = summary[summary["coverage"] < min_coverage]
        print("\nTage mit Abdeckung < %.0f%%: %d" % (min_coverage * 100, len(low)))
        if not low.empty:
            print(low[["date", "bars", "bars_expected", "coverage", "strikes"]].to_string(index=False))

    gaps = missing_trading_days(summary["date"].tolist())
    print("\nMoegliche fehlende Handelstage (Werktags-Luecken): %d" % len(gaps))
    for prev, cur, miss in gaps[:50]:
        print("  zwischen %d und %d: ~%d Werktag(e) fehlen" % (prev, cur, miss))
    if len(gaps) > 50:
        print("  ... (%d weitere)" % (len(gaps) - 50))

    return summary
