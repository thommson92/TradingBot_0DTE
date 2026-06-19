#!/usr/bin/env python3
"""CLI: Datenqualitaets-Report ueber die historisierten Parquet-Daten.

Beispiel:
  python scripts/check_data.py
  python scripts/check_data.py --min-coverage 0.95 --csv out/quality.csv
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot_0dte.config import load_config  # noqa: E402
from tradingbot_0dte.data_quality import run_quality_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Datenqualitaets-Check (Parquet)")
    parser.add_argument("--min-coverage", type=float, default=0.9,
                        help="Schwelle fuer 'gute' Tagesabdeckung (Default 0.9)")
    parser.add_argument("--csv", help="Optional: Summary als CSV speichern")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cfg = load_config()
    summary = run_quality_report(cfg, min_coverage=args.min_coverage)

    if args.csv and not summary.empty:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(out, index=False)
        print("\nSummary gespeichert: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
