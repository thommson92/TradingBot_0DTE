"""Konfiguration laden (settings.yaml + .env) — ThetaData v3.

Geheimnisse kommen ausschliesslich aus der Umgebung (.env / Env-Vars),
nicht-geheime Parameter aus config/settings.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
class Config:
    data: DataConfig
    storage: StorageConfig
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

    api_key = os.getenv("THETADATA_API_KEY")

    return Config(
        data=data,
        storage=storage,
        api_key=api_key,
        project_root=root,
    )
