"""Fill- und Kommissionsmodell: Mid +/- Slippage (adversativ), IBKR-nahe Gebuehren."""
from __future__ import annotations

MULTIPLIER = 100  # SPXW: 1 Kontrakt = Index * 100 Notional
LEGS_NAKED_PUT = 1
LEGS_PUT_SPREAD = 2


def mid(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0


def sell_fill(bid: float, ask: float, slippage_pct: float) -> float:
    """Verkauf einer Leg -> Erhalt von Mid minus Slippage."""
    spread = ask - bid
    return mid(bid, ask) - slippage_pct * spread


def buy_fill(bid: float, ask: float, slippage_pct: float) -> float:
    """Kauf einer Leg -> Zahlung von Mid plus Slippage."""
    spread = ask - bid
    return mid(bid, ask) + slippage_pct * spread


# Aliase fuer den nackten Put: Eroeffnung = Verkauf, Schliessung = Rueckkauf.
entry_fill = sell_fill
exit_fill = buy_fill


def total_commission(commission_per_contract_leg: float, legs: int = LEGS_NAKED_PUT) -> float:
    """Kommissionen fuer Open + Close, je nach Anzahl Legs (1 = naked, 2 = Spread)."""
    return commission_per_contract_leg * legs * 2


def trade_pnl(
    entry_price: float, exit_price: float, commission_per_contract_leg: float,
    legs: int = LEGS_NAKED_PUT,
) -> float:
    """P&L in USD fuer 1 Kontrakt, inkl. Kommissionen. entry_price/exit_price sind
    bereits Netto-Preise (bei Spreads: Differenz der beiden Legs)."""
    gross = (entry_price - exit_price) * MULTIPLIER
    return gross - total_commission(commission_per_contract_leg, legs)
