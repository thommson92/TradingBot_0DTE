"""Zugriffsschicht auf die historisierten Parquet-Daten via DuckDB."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import duckdb
import pandas as pd

from .config import Config


class MarketData:
    """Liest die pro Tag abgelegten Parquet-Dateien als eine logische Tabelle."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root_dir = cfg.storage.parquet_dir / cfg.data.symbol
        self.con = duckdb.connect(database=":memory:")
        # Ohne dies konvertiert DuckDB TIMESTAMPTZ-Spalten in die lokale
        # System-Zeitzone statt in die beim Schreiben verwendete US/Eastern-Zeit.
        self.con.execute("SET TimeZone='America/New_York'")

    def _files(self) -> List[str]:
        if not self.root_dir.exists():
            return []
        return sorted(str(p) for p in self.root_dir.glob("*.parquet"))

    def _scan(self) -> str:
        """Liefert ein read_parquet(...)-SQL-Fragment ueber alle Dateien."""
        files = self._files()
        if not files:
            raise FileNotFoundError("Keine Parquet-Dateien unter %s" % self.root_dir)
        listed = ", ".join("'%s'" % f for f in files)
        return "read_parquet([%s])" % listed

    def available_dates(self) -> List[int]:
        return [int(Path(f).stem) for f in self._files()]

    def query(self, sql: str) -> pd.DataFrame:
        """SQL ausfuehren; der Platzhalter {scan} wird durch die Parquet-Quelle ersetzt."""
        return self.con.execute(sql.format(scan=self._scan())).df()

    def load_day(self, date: int) -> pd.DataFrame:
        path = self.root_dir / ("%d.parquet" % date)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return self.con.execute("SELECT * FROM read_parquet('%s')" % path).df()

    def chain_at(self, date: int, timestamp) -> pd.DataFrame:
        """Optionskette eines Tages zu einem Zeitpunkt (naechster Bar <= timestamp).

        'timestamp' muss vom selben Typ sein wie die gespeicherte Spalte
        (String-ISO oder numerisch) — der Vergleich funktioniert fuer beides.
        """
        df = self.load_day(date)
        avail = df.loc[df["timestamp"] <= timestamp, "timestamp"]
        if avail.empty:
            return df.iloc[0:0]
        snap = avail.max()
        return df[df["timestamp"] == snap].reset_index(drop=True)

    def close(self) -> None:
        self.con.close()
