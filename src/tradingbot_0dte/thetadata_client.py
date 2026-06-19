"""Client fuer die offizielle ThetaData-Python-Library.

Verbindet sich direkt mit der ThetaData-Cloud (gRPC) — kein lokales
Theta Terminal noetig. Authentifizierung ueber den API-Key aus der .env
(THETADATA_API_KEY).

Setzt ein Abo-Tier voraus, das Options-Greeks abdeckt ("Option Data
Standard" oder hoeher) — die Greeks-Endpunkte liefern bid/ask gleich mit,
ein separater Quote-Call ist daher nicht noetig.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import List, Optional

import pandas as pd
from thetadata import ThetaClient
from thetadata.errors import NoDataFoundError

log = logging.getLogger(__name__)


class ThetaDataError(RuntimeError):
    pass


class ThetaDataClient:
    def __init__(self, api_key: Optional[str] = None):
        if not api_key:
            raise ThetaDataError("THETADATA_API_KEY fehlt (.env).")
        self._client = ThetaClient(api_key=api_key, dataframe_type="pandas")

    def list_expirations(self, symbol: str) -> List[dt.date]:
        """Verfuegbare Expirations (== 0-DTE-Handelstage) fuer ein Symbol."""
        try:
            df = self._client.option_list_expirations(symbol)
        except NoDataFoundError:
            return []
        if df.empty:
            return []
        return sorted(pd.to_datetime(df["expiration"]).dt.date.unique().tolist())

    def history_greeks(
        self,
        symbol: str,
        expiration: dt.date,
        interval: str,
        right: str = "put",
        strike: str = "*",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> pd.DataFrame:
        """1st-Order-Greeks inkl. bid/ask/underlying_price fuer einen Handelstag."""
        try:
            return self._client.option_history_greeks_first_order(
                symbol=symbol,
                expiration=expiration,
                date=expiration,
                interval=interval,
                strike=strike,
                right=right,
                start_time=start_time,
                end_time=end_time,
            )
        except NoDataFoundError:
            return pd.DataFrame()
