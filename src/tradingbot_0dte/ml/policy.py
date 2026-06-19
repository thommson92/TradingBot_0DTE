"""ML-Policy: wandelt Modell-Scores in Trade-Entscheidungen um.

Die Policy selektiert aus den gescorten Kandidaten (pnl_hat = erwarteter P&L,
win_proba = P(Win)) jene, die eroeffnet werden. Primaerer Selektor ist pnl_hat
(der erwartete P&L) -- die Echtdaten-Analyse zeigte, dass eine Selektion nach
win_proba den P&L NICHT verbessert (typisch fuer Short-Puts: hohe Trefferquote,
aber seltene grosse Verluste). win_proba dient daher nur als optionaler Filter.

Bewusst keine harte Trade-Anzahl-Grenze als Default (Nutzerwunsch: keine
Vorgabe), aber ein optionales Tageslimit zur Drawdown-Daempfung. Mehrere/
ueberlappende Trades pro Tag sind erlaubt (Optionen sind unabhaengige, cash-
gesettelte Instrumente -> P&L additiv).
"""
from __future__ import annotations

from typing import List

import pandas as pd

# Die exit-unabhaengige Entry-Identitaet: ein Eintrag pro (Tag, Entry-Zeit, Delta,
# Spread-Typ/-Breite). Mit gelernten Exits (Schritt 6) erscheint jede Entry-Gelegen-
# heit mehrfach (eine Zeile je Exit-Spec) -- collapse_exits waehlt davon die beste.
ENTRY_KEY: List[str] = ["date", "entry_time", "target_delta", "spread_type", "spread_width"]


def collapse_exits(scored: pd.DataFrame, keys: List[str] = ENTRY_KEY) -> pd.DataFrame:
    """Reduziert je Entry-Gelegenheit auf die hoechstbewertete Exit-Variante.

    Schritt 6: Das Modell scort (Entry x Exit)-Kombinationen. Ein realer Bot
    eroeffnet je Gelegenheit nur EINEN Trade -- naemlich mit dem Exit, der den
    hoechsten erwarteten P&L hat. Erst danach werden die Gelegenheiten tagesweise
    nach pnl_hat gerankt (Top-N). Ohne diesen Schritt wuerde Top-N N nahezu
    identische Trades derselben Gelegenheit waehlen (kuenstliche Risikokonzentration).
    Spalten, die nicht im Frame sind, werden ignoriert (Rueckwaerts-Kompatibilitaet).
    """
    if scored.empty:
        return scored
    subset = [k for k in keys if k in scored.columns]
    if not subset:
        return scored
    return (
        scored.sort_values("pnl_hat", ascending=False)
        .drop_duplicates(subset=subset, keep="first")
    )


def select_trades(
    scored: pd.DataFrame,
    pnl_hat_threshold: float,
    win_proba_floor: float | None = None,
    max_trades_per_day: int | None = None,
    collapse_exits_first: bool = False,
) -> pd.DataFrame:
    """Waehlt die zu eroeffnenden Kandidaten.

    - pnl_hat_threshold: nur Kandidaten mit erwartetem P&L >= Schwelle.
    - win_proba_floor: optionaler Mindest-Win-Wahrscheinlichkeits-Filter.
    - collapse_exits_first: bei gelernten Exits zuerst je Entry-Gelegenheit die
      beste Exit-Variante waehlen (Schritt 6), bevor das Tageslimit greift.
    - max_trades_per_day: optional je Tag nur die n Kandidaten mit hoechstem
      pnl_hat (Drawdown-Daempfung); None = unbegrenzt.
    """
    sel = scored[scored["pnl_hat"] >= pnl_hat_threshold]
    if win_proba_floor is not None:
        sel = sel[sel["win_proba"] >= win_proba_floor]
    if collapse_exits_first:
        sel = collapse_exits(sel)
    if max_trades_per_day is not None and not sel.empty:
        sel = (
            sel.sort_values("pnl_hat", ascending=False)
            .groupby("date", group_keys=False)
            .head(max_trades_per_day)
        )
    return sel
