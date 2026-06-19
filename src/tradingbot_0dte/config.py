"""Konfiguration laden (settings.yaml + .env) — ThetaData v3.

Geheimnisse kommen ausschliesslich aus der Umgebung (.env / Env-Vars),
nicht-geheime Parameter aus config/settings.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv


@dataclass
class DataConfig:
    symbol: str
    right: str
    interval: str
    delta_low: float
    delta_high: float
    delta_buffer: float
    start_date: str
    end_date: Optional[str]
    start_time: str
    end_time: str


@dataclass
class StorageConfig:
    parquet_dir: Path
    duckdb_path: Path


@dataclass
class StrategyConfig:
    target_delta: float
    delta_low: float
    delta_high: float
    entry_times: List[str]
    max_trades_per_day: Optional[int]
    max_concurrent_positions: int
    profit_target_pct: Optional[float]
    stop_loss_multiplier: Optional[float]
    time_exit_before_close_min: Optional[int]
    slippage_pct_of_spread: float
    commission_per_contract_leg: float
    spread_type: str = "naked"
    spread_width: Optional[float] = None


@dataclass
class Config:
    data: DataConfig
    storage: StorageConfig
    strategy: StrategyConfig
    api_key: Optional[str]
    project_root: Path


def project_root() -> Path:
    """Repo-Wurzel: src/tradingbot_0dte/config.py -> parents[2]."""
    return Path(__file__).resolve().parents[2]


def _resolve(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path)


def load_config(settings_path: Optional[Path] = None) -> Config:
    root = project_root()
    load_dotenv(root / ".env")

    if settings_path is None:
        settings_path = root / "config" / "settings.yaml"
    with open(settings_path, "r") as fh:
        raw = yaml.safe_load(fh)

    d = raw["data"]
    band = d["delta_band"]
    data = DataConfig(
        symbol=d["symbol"],
        right=d["right"],
        interval=str(d["interval"]),
        delta_low=float(band["low"]),
        delta_high=float(band["high"]),
        delta_buffer=float(band.get("buffer", 0.0)),
        start_date=str(d["start_date"]),
        end_date=(str(d["end_date"]) if d.get("end_date") else None),
        start_time=str(d["start_time"]),
        end_time=str(d["end_time"]),
    )

    s = raw["storage"]
    storage = StorageConfig(
        parquet_dir=_resolve(root, s["parquet_dir"]),
        duckdb_path=_resolve(root, s["duckdb_path"]),
    )

    st = raw["strategy"]
    strategy = StrategyConfig(
        target_delta=float(st["target_delta"]),
        delta_low=float(st.get("delta_low", band["low"])),
        delta_high=float(st.get("delta_high", band["high"])),
        entry_times=[str(t) for t in st["entry_times"]],
        max_trades_per_day=(int(st["max_trades_per_day"]) if st.get("max_trades_per_day") is not None else None),
        max_concurrent_positions=int(st.get("max_concurrent_positions", 1)),
        profit_target_pct=(float(st["profit_target_pct"]) if st.get("profit_target_pct") is not None else None),
        stop_loss_multiplier=(float(st["stop_loss_multiplier"]) if st.get("stop_loss_multiplier") is not None else None),
        time_exit_before_close_min=(int(st["time_exit_before_close_min"]) if st.get("time_exit_before_close_min") is not None else None),
        slippage_pct_of_spread=float(st.get("slippage_pct_of_spread", 0.25)),
        commission_per_contract_leg=float(st.get("commission_per_contract_leg", 1.10)),
        spread_type=str(st.get("spread_type", "naked")),
        spread_width=(float(st["spread_width"]) if st.get("spread_width") is not None else None),
    )

    api_key = os.getenv("THETADATA_API_KEY")

    return Config(
        data=data,
        storage=storage,
        strategy=strategy,
        api_key=api_key,
        project_root=root,
    )
