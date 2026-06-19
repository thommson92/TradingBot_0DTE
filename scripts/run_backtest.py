#!/usr/bin/env python3
"""CLI: Backtest des nackten Short Puts auf den historisierten SPXW-Daten.

Beispiele:
  # Defaults aus settings.yaml, gesamte verfuegbare Historie:
  python scripts/run_backtest.py

  # Einzelner Zeitraum + abweichendes Ziel-Delta:
  python scripts/run_backtest.py --start 2024-01-02 --end 2024-01-31 --target-delta 0.10

  # Mehrere Entry-Zeiten/Tag, Tages-Limit aufheben:
  python scripts/run_backtest.py --entry-times 09:35:00,11:00:00,14:00:00 --max-trades-per-day 0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot_0dte.config import load_config  # noqa: E402
from tradingbot_0dte.backtest.params import params_from_config  # noqa: E402
from tradingbot_0dte.backtest.engine import run  # noqa: E402
from tradingbot_0dte.backtest.metrics import compute_metrics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest: nackter Short Put auf SPXW-0DTE-Daten")
    parser.add_argument("--start", help="Startdatum YYYY-MM-DD (Default: erster verfuegbarer Tag)")
    parser.add_argument("--end", help="Enddatum YYYY-MM-DD (Default: letzter verfuegbarer Tag)")
    parser.add_argument("--target-delta", type=float, help="Ziel-|Delta| fuer die Strike-Wahl")
    parser.add_argument("--entry-times", help="Komma-Liste Entry-Zeiten, z.B. 09:35:00,11:00:00")
    parser.add_argument("--max-trades-per-day", type=int,
                        help="Max. Trades/Tag (0 = unbegrenzt, Default: settings.yaml)")
    parser.add_argument("--profit-target", type=float, help="Profit-Target als Anteil der Eroeffnungspraemie")
    parser.add_argument("--stop-mult", type=float, help="Stop-Loss-Multiplikator der Eroeffnungspraemie")
    parser.add_argument("--time-exit-min", type=int, help="Zeit-Exit X Minuten vor Handelsschluss")
    parser.add_argument("--csv", help="Trade-Log als CSV speichern")
    parser.add_argument("--json", help="Metrics als JSON speichern")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cfg = load_config()
    params = params_from_config(cfg)
    if args.target_delta is not None:
        params.target_delta = args.target_delta
    if args.entry_times:
        params.entry_times = args.entry_times.split(",")
    if args.max_trades_per_day is not None:
        params.max_trades_per_day = args.max_trades_per_day or None
    if args.profit_target is not None:
        params.profit_target_pct = args.profit_target
    if args.stop_mult is not None:
        params.stop_loss_multiplier = args.stop_mult
    if args.time_exit_min is not None:
        params.time_exit_before_close_min = args.time_exit_min

    trades = run(cfg, params, start=args.start, end=args.end)
    metrics = compute_metrics(trades)

    print("=== Backtest: nackter Short Put ===")
    print("Trades          : %d" % metrics["n_trades"])
    print("Win-Rate        : %.1f%%" % (metrics["win_rate"] * 100) if metrics["n_trades"] else "Win-Rate        : n/a")
    print("Gesamt-P&L      : %.2f USD" % metrics["total_pnl"])
    print("Expectancy/Trade: %.2f USD" % metrics["avg_pnl_per_trade"] if metrics["n_trades"] else "")
    print("Profit-Faktor   : %.2f" % metrics["profit_factor"] if metrics["n_trades"] else "")
    print("Max Drawdown    : %.2f USD" % metrics["max_drawdown"])
    print("Sharpe          : %.2f" % metrics["sharpe"] if metrics["n_trades"] else "")
    print("Sortino         : %.2f" % metrics["sortino"] if metrics["n_trades"] else "")

    if args.csv and not trades.empty:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        trades.to_csv(out, index=False)
        print("\nTrade-Log gespeichert: %s" % out)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(metrics, indent=2, default=float))
        print("Metrics gespeichert: %s" % out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
