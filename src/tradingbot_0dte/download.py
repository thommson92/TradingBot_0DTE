"""Download & Historisierung der SPXW-0-DTE-Put-Daten nach Parquet.

Pro Handelstag (== 0-DTE-Expiration):
  1. Greeks-History von ThetaData holen (strike="*", right="put") — liefert
     bid/ask/delta/theta/vega/rho/implied_vol/underlying_price in einem Call.
  2. Relevante Strikes nach Delta-Band bestimmen (volle Tagesreihe behalten,
     damit ein Strike auch nach dem Entry weiter verfolgbar bleibt).
  3. Eine Parquet-Datei je Tag schreiben (idempotent / wiederaufnehmbar).
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import List, Optional, Set

import pandas as pd
from tqdm import tqdm

from .config import Config
from .thetadata_client import ThetaDataClient

log = logging.getLogger(__name__)

KEEP_COLS = [
    "timestamp", "strike", "right", "bid", "ask",
    "delta", "theta", "vega", "rho", "implied_vol", "underlying_price",
]


def _yyyymmdd(d) -> int:
    return int(str(d).replace("-", ""))


def _to_date(yyyymmdd: int) -> dt.date:
    s = str(yyyymmdd)
    return dt.date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def _yesterday_int() -> int:
    return _yyyymmdd((dt.date.today() - dt.timedelta(days=1)).isoformat())


def client_from_config(cfg: Config) -> ThetaDataClient:
    return ThetaDataClient(api_key=cfg.api_key)


def trading_days(client: ThetaDataClient, symbol: str, start: int, end: int) -> List[int]:
    """Expirations (== 0-DTE-Handelstage) im Bereich [start, end]."""
    days = sorted(_yyyymmdd(e) for e in client.list_expirations(symbol))
    return [d for d in days if start <= d <= end]


def partition_path(cfg: Config, exp: int) -> Path:
    return cfg.storage.parquet_dir / cfg.data.symbol / ("%d.parquet" % exp)


def _relevant_strikes(df: pd.DataFrame, low: float, high: float, buffer: float) -> Optional[Set[float]]:
    """Strikes, deren |Delta| das Band [low, high+buffer] im Tagesverlauf beruehrt."""
    if "delta" not in df.columns:
        log.warning("Keine 'delta'-Spalte in den Daten — Strike-Filter wird uebersprungen.")
        return None
    g = df[["strike", "delta"]].copy()
    g["abs_delta"] = g["delta"].abs()
    agg = g.groupby("strike")["abs_delta"].agg(["min", "max"])
    keep = agg[(agg["max"] >= low) & (agg["min"] <= high + buffer)].index
    return set(keep.tolist())


def build_day(client: ThetaDataClient, cfg: Config, exp: int) -> pd.DataFrame:
    d = cfg.data
    df = client.history_greeks(d.symbol, _to_date(exp), d.interval, right=d.right,
                               start_time=d.start_time, end_time=d.end_time)
    if df.empty:
        return df

    keep = _relevant_strikes(df, d.delta_low, d.delta_high, d.delta_buffer)
    if keep is not None:
        df = df[df["strike"].isin(keep)]
    if df.empty:
        return df

    cols = [c for c in KEEP_COLS if c in df.columns]
    df = df[cols].copy()
    if "bid" in df.columns and "ask" in df.columns:
        df["mid"] = (df["bid"] + df["ask"]) / 2.0
    df["symbol"] = d.symbol
    df["expiration"] = exp
    df["date"] = exp
    return df.sort_values(["timestamp", "strike"]).reset_index(drop=True)


def download_range(
    cfg: Config,
    start: Optional[str] = None,
    end: Optional[str] = None,
    overwrite: bool = False,
    limit: Optional[int] = None,
) -> dict:
    client = client_from_config(cfg)

    start_i = _yyyymmdd(start or cfg.data.start_date)
    end_i = _yyyymmdd(end) if end else (_yyyymmdd(cfg.data.end_date) if cfg.data.end_date else _yesterday_int())

    log.info("Ermittle Handelstage fuer %s zwischen %d und %d ...", cfg.data.symbol, start_i, end_i)
    days = trading_days(client, cfg.data.symbol, start_i, end_i)
    if limit:
        days = days[:limit]
    log.info("%d Handelstage zu verarbeiten.", len(days))

    stats = {"requested": len(days), "written": 0, "skipped": 0, "empty": 0, "rows": 0}
    for exp in tqdm(days, desc="Download", unit="Tag"):
        path = partition_path(cfg, exp)
        if path.exists() and not overwrite:
            stats["skipped"] += 1
            continue
        try:
            df = build_day(client, cfg, exp)
        except Exception as exc:  # einzelner Tag soll den Lauf nicht abbrechen
            log.error("Fehler bei %d: %s", exp, exc)
            continue
        if df.empty:
            log.warning("Keine Daten fuer %d.", exp)
            stats["empty"] += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        stats["written"] += 1
        stats["rows"] += len(df)

    log.info("Fertig: %s", stats)
    return stats
