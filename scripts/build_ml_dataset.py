#!/usr/bin/env python3
"""CLI: ML-Trainingstabelle bauen (Phase 5, Schritt 2).

Erzeugt pro Handelstag x Kandidat (Entry-Zeit x Ziel-Delta x naked/Spread) eine
Zeile mit Features + realem Label (Trade-P&L via Backtest-Engine) und speichert
sie als Parquet-Cache fuer das anschliessende Training.

Beispiele:
  # Kleines Raster, Januar 2024, 8 Worker:
  python scripts/build_ml_dataset.py --start 2024-01-02 --end 2024-01-31 \\
      --entry-step-min 30 --target-deltas 0.10,0.16,0.20 --spreads naked \\
      --n-jobs 8 --out out/ml/dataset_jan2024.parquet

  # Volles Raster ueber die ganze Historie (Default-Pfad):
  python scripts/build_ml_dataset.py \\
      --target-deltas 0.05,0.10,0.16,0.20,0.30 --spreads naked,put_spread:5,put_spread:10

  # Mit gelernter Exit-Achse (Schritt 6): Profit-Targets x Stops x Zeit-Exits:
  python scripts/build_ml_dataset.py --start 2023-01-01 \\
      --profit-targets 0.30,0.50,none --stop-mults 2.0,3.0 --time-exits 5,30,0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot_0dte.config import load_config  # noqa: E402
from tradingbot_0dte.ml.dataset import (  # noqa: E402
    CandidateGrid, ExitRule, ExitSpec, build_dataset, default_entry_times, save_dataset,
)

DEFAULT_OUT = "out/ml/dataset.parquet"


def _parse_floats(s: str) -> list:
    return [float(x) for x in s.split(",")]


def _parse_opt_floats(s: str) -> list:
    """Komma-Liste optionaler Floats; 'none'/'off'/'' -> None (Regel deaktiviert)."""
    out = []
    for tok in s.split(","):
        tok = tok.strip().lower()
        out.append(None if tok in ("none", "off", "") else float(tok))
    return out


def _parse_opt_ints(s: str) -> list:
    """Komma-Liste optionaler Ints; '0'/'none'/'off'/'' -> None (kein Zeit-Exit)."""
    out = []
    for tok in s.split(","):
        tok = tok.strip().lower()
        out.append(None if tok in ("none", "off", "", "0") else int(tok))
    return out


def _build_exit_specs(args) -> list:
    """Baut die Exit-Achse: kartesisches Produkt aus Profit-Targets x Stop-Mults x
    Zeit-Exits, falls eine der Plural-Optionen gesetzt ist (gelernte Exits,
    Schritt 6); sonst eine einzige Spec aus den Singular-Defaults (altes Verhalten)."""
    learned = args.profit_targets or args.stop_mults or args.time_exits
    if not learned:
        return [ExitSpec(
            profit_target_pct=args.profit_target,
            stop_loss_multiplier=args.stop_mult,
            time_exit_before_close_min=(args.time_exit_min or None),
        )]
    pts = _parse_opt_floats(args.profit_targets) if args.profit_targets else [args.profit_target]
    sms = _parse_opt_floats(args.stop_mults) if args.stop_mults else [args.stop_mult]
    tes = _parse_opt_ints(args.time_exits) if args.time_exits else [(args.time_exit_min or None)]
    return [ExitSpec(p, s, t) for p in pts for s in sms for t in tes]


def _parse_spreads(s: str) -> list:
    """'naked,put_spread:5,put_spread:10' -> [('naked',None),('put_spread',5.0),...]."""
    specs = []
    for tok in s.split(","):
        tok = tok.strip()
        if tok == "naked":
            specs.append(("naked", None))
        elif tok.startswith("put_spread"):
            _, _, width = tok.partition(":")
            if not width:
                raise SystemExit("put_spread benoetigt eine Breite, z.B. put_spread:5")
            specs.append(("put_spread", float(width)))
        else:
            raise SystemExit("Unbekannte Spread-Spezifikation: %s" % tok)
    return specs


def main() -> int:
    parser = argparse.ArgumentParser(description="ML-Trainingstabelle bauen")
    parser.add_argument("--start", help="Startdatum YYYY-MM-DD")
    parser.add_argument("--end", help="Enddatum YYYY-MM-DD")
    parser.add_argument("--entry-start", default="09:35:00", help="Erste Entry-Zeit (HH:MM:SS)")
    parser.add_argument("--entry-end", default="15:55:00", help="Letzte Entry-Zeit (HH:MM:SS)")
    parser.add_argument("--entry-step-min", type=int, default=15, help="Schrittweite Entry-Zeiten in Minuten")
    parser.add_argument("--target-deltas", default="0.05,0.10,0.16,0.20,0.30",
                        help="Komma-Liste Ziel-Deltas")
    parser.add_argument("--spreads", default="naked,put_spread:5,put_spread:10",
                        help="Komma-Liste: naked / put_spread:<Breite>")
    parser.add_argument("--profit-target", type=float, default=0.50, help="Fixe Exit-Regel: Profit-Target")
    parser.add_argument("--stop-mult", type=float, default=2.0, help="Fixe Exit-Regel: Stop-Loss-Multiplikator")
    parser.add_argument("--time-exit-min", type=int, default=5, help="Fixe Exit-Regel: Minuten vor Close (0=aus)")
    parser.add_argument("--profit-targets", help="Exit-Achse (Schritt 6): Komma-Liste Profit-Targets, z.B. 0.30,0.50,none")
    parser.add_argument("--stop-mults", help="Exit-Achse: Komma-Liste Stop-Multiplikatoren, z.B. 2.0,3.0,none")
    parser.add_argument("--time-exits", help="Exit-Achse: Komma-Liste Minuten vor Close, z.B. 5,30,0 (0/none=aus)")
    parser.add_argument("--n-jobs", type=int, help="Anzahl Worker-Prozesse (Default: CPU-Anzahl)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Ausgabepfad (Parquet)")
    args = parser.parse_args()

    cfg = load_config()

    entry_times = default_entry_times(args.entry_start, args.entry_end, args.entry_step_min)
    exit_specs = _build_exit_specs(args)
    grid = CandidateGrid(
        entry_times=entry_times,
        target_deltas=_parse_floats(args.target_deltas),
        spreads=_parse_spreads(args.spreads),
        delta_low=cfg.strategy.delta_low,
        delta_high=cfg.strategy.delta_high,
        exit_specs=exit_specs,
    )
    # ExitRule traegt nur noch die (nicht gelernten) Kosten + den Default-Exit; der
    # tatsaechliche Exit kommt je Kandidat aus seiner ExitSpec im Raster.
    exit_rule = ExitRule(
        slippage_pct_of_spread=cfg.strategy.slippage_pct_of_spread,
        commission_per_contract_leg=cfg.strategy.commission_per_contract_leg,
    )

    n_candidates = len(grid.expand())
    print("Kandidatenraster: %d Entry-Zeiten x %d Deltas x %d Spread-Typen x %d Exit-Specs = %d Kandidaten/Tag"
          % (len(entry_times), len(grid.target_deltas), len(grid.spreads), len(exit_specs), n_candidates))
    if len(exit_specs) > 1:
        print("Exit-Achse (gelernte Exits, Schritt 6):")
        for s in exit_specs:
            print("  - PT=%s Stop=%s Zeit-Exit=%s" % (
                s.profit_target_pct, s.stop_loss_multiplier, s.time_exit_before_close_min))

    df = build_dataset(cfg, grid, exit_rule, start=args.start, end=args.end, n_jobs=args.n_jobs)

    tradable = int(df["tradable"].sum()) if not df.empty else 0
    print("\nZeilen gesamt: %d | handelbar: %d (%.1f%%)"
          % (len(df), tradable, 100.0 * tradable / len(df) if len(df) else 0.0))
    if tradable:
        t = df[df["tradable"] == 1]
        print("Label-P&L: mean %.2f | win-rate %.1f%% | min %.1f | max %.1f"
              % (t["pnl"].mean(), 100.0 * t["is_win"].mean(), t["pnl"].min(), t["pnl"].max()))

    out = Path(args.out)
    save_dataset(df, out)
    print("\nDataset gespeichert: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
