#!/usr/bin/env python3
"""Offline-Test der Pipeline-Logik ohne Netzwerkzugriff auf ThetaData.

Validiert: Delta-Band-Filter (build_day), Parquet-Write, DuckDB-Zugriff
(MarketData) und den Datenqualitaets-Report — alles mit synthetischen Daten.
Aufruf: python tests/test_pipeline_offline.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tradingbot_0dte.config import Config, DataConfig, StorageConfig
from tradingbot_0dte import download as dl
from tradingbot_0dte.storage import MarketData
from tradingbot_0dte.data_quality import per_day_summary, missing_trading_days, expected_bars

EXP = 20240105
TS = ["09:30:00", "09:31:00"]


def _make_cfg(tmp: Path) -> Config:
    return Config(
        data=DataConfig(
            symbol="SPXW", right="put", interval="1m",
            delta_low=0.01, delta_high=0.50, delta_buffer=0.05,
            start_date="2024-01-05", end_date=None,
            start_time="09:30:00", end_time="09:31:00",  # 2 Bars erwartet
        ),
        storage=StorageConfig(parquet_dir=tmp / "parquet", duckdb_path=tmp / "m.duckdb"),
        api_key=None, project_root=tmp,
    )


def _synthetic_greeks() -> pd.DataFrame:
    rows = {
        4700.0: (5.0, 5.4, -0.50),
        4650.0: (2.0, 2.2, -0.16),
        4600.0: (1.0, 1.1, -0.05),
        4750.0: (9.0, 9.4, -0.80),
        4500.0: (0.05, 0.10, -0.005),
    }
    out = []
    for ts in TS:
        for k, (b, a, d) in rows.items():
            out.append({"timestamp": ts, "strike": k, "right": "PUT",
                        "bid": b, "ask": a, "delta": d, "theta": -0.5, "vega": 0.3,
                        "rho": 0.1, "implied_vol": 0.15, "underlying_price": 4700.0})
    return pd.DataFrame(out)


class _FakeClient:
    def history_greeks(self, symbol, expiration, interval, right="put", strike="*",
                       start_time=None, end_time=None):
        return _synthetic_greeks()


def test_build_day(cfg):
    df = dl.build_day(_FakeClient(), cfg, EXP)
    # ITM 4750 (|d|=0.80) und 4500 (|d|=0.005) raus -> 3 Strikes
    assert set(df["strike"]) == {4700.0, 4650.0, 4600.0}, set(df["strike"])
    assert "mid" in df.columns and "delta" in df.columns
    assert df["mid"].iloc[0] == (df["bid"].iloc[0] + df["ask"].iloc[0]) / 2.0
    print("[ok] build_day + delta-band filter (3 strikes)")
    return df


def test_storage_and_qc(cfg, df):
    path = dl.partition_path(cfg, EXP)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)

    md = MarketData(cfg)
    try:
        assert md.available_dates() == [EXP]
        chain = md.chain_at(EXP, "09:31:00")
        assert len(chain) == 3, "3 Strikes im Snapshot"
        assert chain["timestamp"].nunique() == 1
    finally:
        md.close()

    assert expected_bars(cfg) == 2
    summary = per_day_summary(cfg)
    assert summary["bars"].iloc[0] == 2
    assert summary["coverage"].iloc[0] == 1.0
    assert summary["strikes"].iloc[0] == 3
    print("[ok] storage (DuckDB) + quality summary")

    gaps = missing_trading_days([20240105, 20240108, 20240116])
    assert gaps and gaps[0][0] == 20240108
    print("[ok] missing-day heuristic")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(Path(tmp))
        df = test_build_day(cfg)
        test_storage_and_qc(cfg, df)
    print("\nAlle Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
