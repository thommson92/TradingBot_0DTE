#!/usr/bin/env python3
"""CLI: SPXW-0-DTE-Put-Daten von ThetaData nach Parquet historisieren.

Beispiele:
  # Erst EINEN Tag zum Testen ziehen:
  python scripts/download_data.py --start 2024-01-05 --end 2024-01-05

  # Gesamten Zeitraum aus settings.yaml laden:
  python scripts/download_data.py

  # Begrenzte Anzahl Tage (Smoke-Test):
  python scripts/download_data.py --limit 1
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot_0dte.config import load_config  # noqa: E402
from tradingbot_0dte.download import download_range  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Download SPXW 0-DTE Put-Daten -> Parquet")
    parser.add_argument("--start", help="Startdatum YYYY-MM-DD (Default: settings.yaml)")
    parser.add_argument("--end", help="Enddatum YYYY-MM-DD (Default: gestern)")
    parser.add_argument("--overwrite", action="store_true", help="Vorhandene Tagesdateien neu schreiben")
    parser.add_argument("--limit", type=int, help="Max. Anzahl Tage (zum Testen)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config()
    if not cfg.api_key:
        logging.warning("THETADATA_API_KEY ist nicht gesetzt (.env) — Requests werden fehlschlagen.")

    stats = download_range(
        cfg,
        start=args.start,
        end=args.end,
        overwrite=args.overwrite,
        limit=args.limit,
    )
    print("Ergebnis:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
