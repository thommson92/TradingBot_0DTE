#!/usr/bin/env python3
"""CLI: ML-Policy-Backtest (Phase 5, Schritt 4).

Tunt die *kausale* Per-Tag-Top-N-Policy auf den OOS-Vorhersagen (Komposit-Score:
Calmar-aehnlich mit Win-Rate-Mindestschwelle) und wendet das gewaehlte N
unveraendert auf das unberuehrte Holdout an -- die ehrliche Out-of-Sample-
Bewertung. Top-N (taeglich die N besten Kandidaten nach erwartetem P&L) statt
einer absoluten pnl_hat-Schwelle, weil Letztere zwischen Zeitraeumen nicht
generalisiert (Score-Drift). Beide Vorhersage-Dateien stammen aus train_ml.py.

Speichert den Holdout-Lauf dashboard-kompatibel (out/backtests/), damit er auf der
Vergleichsseite neben Backtests/Grid-Search erscheint.

Beispiel:
  python scripts/run_ml_backtest.py --oos out/ml/oos_predictions.parquet \\
      --holdout out/ml/holdout_predictions.parquet --min-win-rate 0.62
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from tradingbot_0dte.ml.evaluate import policy_metrics, tune_top_n  # noqa: E402
from tradingbot_0dte.ml.policy import ENTRY_KEY, select_trades  # noqa: E402


def _has_learned_exits(df: pd.DataFrame) -> bool:
    """True, wenn das Dataset eine Exit-Achse hat (mehrere Exit-Specs je Entry-
    Gelegenheit) -> die Policy muss je Gelegenheit die beste Exit-Variante waehlen."""
    keys = [k for k in ENTRY_KEY if k in df.columns]
    if not keys or df.empty:
        return False
    # dropna=False: spread_width ist bei naked NaN -> sonst faellt der ganze Frame raus.
    return bool((df.groupby(keys, dropna=False).size() > 1).any())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
import runs as dashboard_runs  # noqa: E402

METRIC_KEYS = ["n_trades", "win_rate", "total_pnl", "avg_pnl_per_trade",
               "profit_factor", "max_drawdown", "sharpe", "sortino"]


def _print_metrics(name: str, m: dict) -> None:
    print("  [%s] n=%d | total=%.1f | mean/Trade=%.2f | win=%.1f%% | maxDD=%.1f | "
          "PF=%.2f | Sharpe=%.2f"
          % (name, m["n_trades"], m["total_pnl"], m["avg_pnl_per_trade"],
             100.0 * m["win_rate"], m["max_drawdown"],
             m["profit_factor"], m["sharpe"] if m["sharpe"] == m["sharpe"] else float("nan")))


def main() -> int:
    parser = argparse.ArgumentParser(description="ML-Policy-Backtest (Tuning auf OOS, Bewertung auf Holdout)")
    parser.add_argument("--oos", default="out/ml/oos_predictions.parquet")
    parser.add_argument("--holdout", default="out/ml/holdout_predictions.parquet")
    parser.add_argument("--pnl-hat-floor", type=float, default=0.0, help="nur Kandidaten mit erwartetem P&L >= floor")
    parser.add_argument("--min-win-rate", type=float, default=0.60, help="Win-Rate-Mindestschwelle im Komposit-Score")
    parser.add_argument("--n", type=int, default=None, help="festes N (Trades/Tag); sonst auf OOS getunt")
    parser.add_argument("--collapse-exits", choices=["auto", "on", "off"], default="auto",
                        help="je Entry-Gelegenheit die beste Exit-Variante waehlen (Schritt 6); "
                             "auto = an, wenn das Dataset eine Exit-Achse hat")
    parser.add_argument("--out-dir", default="out/backtests", help="Speicherort fuer den Dashboard-Lauf")
    parser.add_argument("--label", default="ML-Policy (Holdout)")
    parser.add_argument("--no-save", action="store_true", help="Lauf nicht persistieren")
    args = parser.parse_args()

    oos = pd.read_parquet(args.oos)
    holdout = pd.read_parquet(args.holdout)

    if args.collapse_exits == "auto":
        collapse = _has_learned_exits(oos)
    else:
        collapse = args.collapse_exits == "on"
    print("Exit-Achse: %s (collapse_exits=%s)"
          % ("gelernt" if _has_learned_exits(oos) else "fix", "an" if collapse else "aus"))

    print("Per-Tag-Top-N-Tuning auf OOS (n=%d), pnl_hat-floor=%.1f:" % (len(oos), args.pnl_hat_floor))
    best, table = tune_top_n(oos, pnl_hat_floor=args.pnl_hat_floor, min_win_rate=args.min_win_rate,
                             collapse_exits=collapse)
    cols = ["n_per_day", "composite", "n_trades", "total_pnl", "avg_pnl_per_trade",
            "win_rate", "max_drawdown", "sharpe"]
    print(table[cols].to_string(index=False, float_format=lambda x: "%.3f" % x))

    n = args.n if args.n is not None else int(best["n_per_day"])
    print("\nGewaehltes N (Trades/Tag): %d%s | Komposit=%.3f"
          % (n, " (vorgegeben)" if args.n is not None else " (getunt)", best["composite"]))

    print("\nOOS (in-Tuning) vs. Holdout (out-of-sample) mit N=%d:" % n)
    oos_sel = select_trades(oos, args.pnl_hat_floor, max_trades_per_day=n, collapse_exits_first=collapse)
    hold_sel = select_trades(holdout, args.pnl_hat_floor, max_trades_per_day=n, collapse_exits_first=collapse)
    m_oos = policy_metrics(oos_sel)
    m_hold = policy_metrics(hold_sel)
    _print_metrics("OOS    ", m_oos)
    _print_metrics("HOLDOUT", m_hold)

    if not args.no_save and not hold_sel.empty:
        start = str(int(holdout["date"].min()))
        end = str(int(holdout["date"].max()))
        info = {
            "policy": "per_day_top_n", "n_per_day": n, "pnl_hat_floor": args.pnl_hat_floor,
            "min_win_rate": args.min_win_rate, "segment": "holdout",
            "learned_exits": bool(collapse),
        }
        row = dashboard_runs.save_ml_run(
            Path(args.out_dir), args.label, start, end, m_hold, hold_sel, info,
        )
        print("\nDashboard-Lauf gespeichert: %s" % row["csv_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
