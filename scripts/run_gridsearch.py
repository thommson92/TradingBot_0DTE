#!/usr/bin/env python3
"""CLI: Grid-Search ueber Strategie-Parameter, parallelisiert ueber Worker-Prozesse.

Jede mit einer Komma-Liste angegebene Option wird zu einer Achse der
Parametermatrix (kartesisches Produkt). Nicht angegebene Optionen bleiben fix
auf dem Config-/Basis-Wert.

Beispiele:
  # 3 Ziel-Deltas x 2 Profit-Targets = 6 Kombinationen, Januar 2024:
  python scripts/run_gridsearch.py --start 2024-01-02 --end 2024-01-31 \\
      --target-delta 0.10,0.16,0.20 --profit-target 0.20,0.30

  # Naked vs. Put-Spread (zwei Breiten) im selben Lauf, 8 Worker:
  python scripts/run_gridsearch.py --spread-type naked,put_spread \\
      --spread-width 5,10 --n-jobs 8 --top 10 --csv out/backtests/grid.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot_0dte.config import load_config  # noqa: E402
from tradingbot_0dte.backtest.params import params_from_config  # noqa: E402
from tradingbot_0dte.backtest.gridsearch import build_param_grid, run_grid  # noqa: E402

def _parse_floats(s: str) -> list:
    return [float(x) for x in s.split(",")]


def _parse_ints(s: str) -> list:
    return [int(x) for x in s.split(",")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Grid-Search ueber Strategie-Parameter")
    parser.add_argument("--start", help="Startdatum YYYY-MM-DD")
    parser.add_argument("--end", help="Enddatum YYYY-MM-DD")
    parser.add_argument("--target-delta", help="Komma-Liste Ziel-Deltas, z.B. 0.10,0.16,0.20")
    parser.add_argument("--profit-target", help="Komma-Liste Profit-Targets, z.B. 0.20,0.30")
    parser.add_argument("--stop-mult", help="Komma-Liste Stop-Loss-Multiplikatoren, z.B. 2,3")
    parser.add_argument("--time-exit-min", help="Komma-Liste Zeit-Exit-Minuten, z.B. 5,0 (0=deaktiviert)")
    parser.add_argument("--spread-type", help="Komma-Liste naked,put_spread")
    parser.add_argument("--spread-width", help="Komma-Liste Spread-Breiten, z.B. 5,10")
    parser.add_argument("--n-jobs", type=int, help="Anzahl Worker-Prozesse (Default: CPU-Anzahl)")
    parser.add_argument("--sort-by", default="total_pnl", help="Metrik zum Sortieren (Default: total_pnl)")
    parser.add_argument("--top", type=int, default=20, help="Anzahl Zeilen in der Konsolen-Ausgabe")
    parser.add_argument("--csv", help="Volles Leaderboard als CSV speichern")
    args = parser.parse_args()

    cfg = load_config()
    base = params_from_config(cfg)

    axes = {}
    if args.target_delta:
        axes["target_delta"] = _parse_floats(args.target_delta)
    if args.profit_target:
        axes["profit_target_pct"] = _parse_floats(args.profit_target)
    if args.stop_mult:
        axes["stop_loss_multiplier"] = _parse_floats(args.stop_mult)
    if args.time_exit_min:
        axes["time_exit_before_close_min"] = [v or None for v in _parse_ints(args.time_exit_min)]
    if args.spread_type:
        axes["spread_type"] = args.spread_type.split(",")
    if args.spread_width:
        axes["spread_width"] = _parse_floats(args.spread_width)

    spread_types = axes.get("spread_type", [base.spread_type])
    if "put_spread" in spread_types and not axes.get("spread_width") and base.spread_width is None:
        parser.error("--spread-width ist fuer spread_type=put_spread erforderlich")

    param_grid = build_param_grid(base, axes)
    print("Parametermatrix: %d Kombination(en)" % len(param_grid))

    leaderboard = run_grid(cfg, param_grid, start=args.start, end=args.end,
                            n_jobs=args.n_jobs, sort_by=args.sort_by)

    cols = ["target_delta", "profit_target_pct", "stop_loss_multiplier",
            "time_exit_before_close_min", "spread_type", "spread_width",
            "n_trades", "win_rate", "total_pnl", "profit_factor", "sharpe", "sortino"]
    cols = [c for c in cols if c in leaderboard.columns]
    print(leaderboard[cols].head(args.top).to_string(index=False))

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        leaderboard.to_csv(out, index=False)
        print("\nLeaderboard gespeichert: %s" % out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
