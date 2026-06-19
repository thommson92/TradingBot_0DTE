# TradingBot_0DTE

Backtesting-Werkzeug zur Erarbeitung von **SPX 0-DTE Optionsstrategien**
(Short Puts / Put-Spreads), das spaeter die Basis fuer einen automatisierten
Trading-Bot bildet.

Spezifikation & Entscheidungen: siehe [docs/Projektplanung.md](docs/Projektplanung.md).

---

## Phase 1 — Datenpipeline (aktuell implementiert)

Laedt historische **SPX-0-DTE-Put**-Daten (1-Minuten-Greeks inkl. bid/ask) von
**ThetaData** (offizielle Python-Library) und historisiert sie lokal als
Parquet. Nur Puts im Delta-Band ~0.01–0.50 werden gespeichert.

### 1. Voraussetzungen

- **Python 3.12+** (Mindestanforderung der `thetadata`-Library)
- Aktives ThetaData-Abo, Tier **"Option Data Standard"** oder hoeher
  (der Greeks-Endpunkt liefert PERMISSION_DENIED auf dem kleineren "Value"-Tier).
- Kein lokales Theta Terminal noetig — die offizielle Python-Library
  verbindet sich direkt (gRPC) mit der ThetaData-Cloud.

### 2. Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # oder: pip install -e .

cp .env.example .env                   # dann THETADATA_API_KEY eintragen
```

> **Sicherheit:** Der API-Key gehoert ausschliesslich in `.env` (per `.gitignore`
> ausgeschlossen). Niemals in Code, Doku oder Commits.

### 3. Konfiguration

Nicht-geheime Parameter in [config/settings.yaml](config/settings.yaml):
Symbol (**SPXW** — taegliche Verfaelle; `SPX` hat nur monatliche/quartalsweise),
Zeitraum, Intervall (1 Min), Delta-Band, Handelszeiten, Speicherpfade.

### 4. Download

```bash
# ZUERST einen einzelnen Tag testen:
python scripts/download_data.py --start 2024-01-05 --end 2024-01-05

# Sieht gut aus? Gesamten Zeitraum aus settings.yaml laden
# (idempotent/wiederaufnehmbar — vorhandene Tage werden uebersprungen):
python scripts/download_data.py
```

Ergebnis: eine Parquet-Datei je Handelstag unter
`data/parquet/SPXW/<YYYYMMDD>.parquet`.

### 5. Datenqualitaet pruefen

```bash
python scripts/check_data.py
python scripts/check_data.py --min-coverage 0.95 --csv out/quality.csv
```

Berichtet Bar-Abdeckung/Tag, Strike-Anzahl und moegliche fehlende Handelstage.

### 6. Offline-Test (ohne Netzwerkzugriff)

```bash
python tests/test_pipeline_offline.py
```

Validiert die Pipeline-Logik (Delta-Filter, Parquet, DuckDB, QC) mit
synthetischen Daten.

---

## Projektstruktur

```
config/settings.yaml          Nicht-geheime Konfiguration
src/tradingbot_0dte/
  config.py                   Laedt settings.yaml + .env
  thetadata_client.py         Wrapper um die offizielle thetadata-Python-Library
  download.py                 Download + Historisierung -> Parquet
  storage.py                  DuckDB-Zugriffsschicht auf die Parquet-Daten
  data_quality.py             Qualitaets-/Luecken-Report
  backtest/
    params.py                 StrategyParams (Strategie-Parameter)
    trade.py                  Trade-Record
    fills.py                  Fill-/Kommissionsmodell (Mid +/- Slippage)
    strategy.py               Strike-Wahl (Ziel-Delta, Long-Leg) + Exit-Logik
    engine.py                 Event-Loop: run_day() / run() (naked + put_spread)
    metrics.py                compute_metrics() (Win-Rate, P/L, Drawdown, Sharpe/Sortino, ...)
    gridsearch.py              Parametermatrix, parallelisiert ueber Worker-Prozesse
scripts/
  download_data.py            CLI: Daten laden
  check_data.py               CLI: Qualitaets-Report
  run_backtest.py             CLI: Backtest (naked Short Put oder Put-Spread)
  run_gridsearch.py           CLI: Grid-Search ueber Strategie-Parameter
tests/
  test_pipeline_offline.py    Offline-Test Datenpipeline
  test_backtest_offline.py    Offline-Test Backtest-Engine
  test_gridsearch_offline.py  Offline-Test Grid-Search-Bausteine
docs/Projektplanung.md        Spezifikation & Entscheidungs-Log
```

## Datenmodell (pro Zeile = ein Strike zu einem Minuten-Bar)

`timestamp, strike, right, bid, ask, mid, delta, theta, vega, rho,
implied_vol, underlying_price, symbol, expiration, date`

(Strikes sind Dollar-Floats, right = `PUT`.)

---

## Hinweise / Annahmen

- Der Client nutzt die **offizielle `thetadata`-Python-Library**
  (`option_list_expirations`, `option_history_greeks_first_order`),
  `strike="*"`, `right="put"`, `interval="1m"`. Verbindung per gRPC direkt
  zur ThetaData-Cloud, kein lokales Terminal.
- **Symbology:** `SPXW` fuer taegliche 0-DTE-Verfaelle (`SPX` selbst hat nur
  monatliche/quartalsweise Verfaelle — live verifiziert).
- Der Greeks-Endpunkt liefert `bid`/`ask` bereits mit — ein separater
  Quote-Call (mit `bid_size`/`ask_size`) ist daher bewusst weggelassen.
- **AGB-Konformitaet:** Daten werden lokal gehalten, solange das Abo laeuft, und
  bei Abo-Ende geloescht.
- **DuckDB-Zeitzone:** `MarketData` setzt `SET TimeZone='America/New_York'` auf der
  Connection — ohne das konvertiert DuckDB `TIMESTAMPTZ`-Spalten beim Export nach
  pandas in die lokale System-Zeitzone statt in die beim Schreiben verwendete
  US/Eastern-Zeit (live entdeckt beim Bau der Backtest-Engine, da Entry-Zeiten
  sonst gegen die falsche Wanduhrzeit verglichen wurden).

---

## Phase 2 — Backtest-Engine (aktuell implementiert)

Event-getriebener Backtest fuer einen **nackten Short Put** auf den historisierten
SPXW-Daten. Strike-Wahl per Ziel-Delta, Exit per Profit-Target/Stop-Loss/Zeit-Exit
(Prioritaet: Stop-Loss > Profit-Target > Zeit-Exit), Fills zu Mid +/- Slippage,
Kommissionen pro Kontrakt/Leg.

**Wichtig:** "1 Trade/Tag" ist **kein festes Kriterium im Code** — `entry_times`
ist eine konfigurierbare Liste von Entry-Zeiten/Tag, begrenzt durch das ebenfalls
konfigurierbare `max_trades_per_day` (`null` = unbegrenzt). Ein Tag mit nur einer
Entry-Zeit verhaelt sich wie "1 Trade/Tag"; mehr Entry-Zeiten oder ein hoeheres/
`null`-Limit ergeben mehr Trades/Tag, ohne Code-Aenderung.

```bash
# Backtest ueber die gesamte verfuegbare Historie (Defaults aus settings.yaml):
python scripts/run_backtest.py

# Eingegrenzter Zeitraum + abweichendes Ziel-Delta:
python scripts/run_backtest.py --start 2024-01-02 --end 2024-01-31 --target-delta 0.10

# Mehrere Entry-Zeiten/Tag, Tages-Limit aufheben:
python scripts/run_backtest.py --entry-times 09:35:00,11:00:00,14:00:00 --max-trades-per-day 0

# Trade-Log + Metrics speichern:
python scripts/run_backtest.py --csv out/backtests/run1.csv --json out/backtests/run1.json
```

Strategie-Parameter (Defaults) stehen unter `strategy:` in
[config/settings.yaml](config/settings.yaml): `target_delta`, `entry_times`,
`max_trades_per_day`, `max_concurrent_positions`, `profit_target_pct`,
`stop_loss_multiplier`, `time_exit_before_close_min`, `slippage_pct_of_spread`,
`commission_per_contract_leg`.

```bash
python tests/test_backtest_offline.py   # Offline-Test (synthetische Daten)
```

**Annahme:** Sharpe/Sortino werden auf der **Tages-P&L-Reihe** (annualisiert mit
`sqrt(252)`) berechnet, nicht auf prozentualen Returns — bei fixer Kontraktzahl=1
gibt es keine definierte Kapitalbasis.

**Performance:** ~10 Handelstage/Sekunde (1 Param-Satz) — fuer Phase 3
(Parametermatrix x volle Historie) wird Parallelisierung noetig sein.

---

## Phase 3 — Put-Spreads + Grid-Search/Parallelisierung (aktuell implementiert)

### Put-Spread

Zweite Strategie-Variante neben dem nackten Short Put: eine zusaetzliche
**Long-Put-Leg** (weiter OTM, Breite konfigurierbar, typ. 5 oder 10
Indexpunkte) begrenzt den maximalen Verlust. Long-Leg-Wahl per Nearest-Match
auf `short_strike - spread_width` (SPX-Strikeabstaende sind nicht ueberall
exakt gleich breit). P&L/Exit-Schwellenwerte (Stop-Loss/Profit-Target/Zeit-
Exit) laufen auf dem **Netto-Spread-Wert** (Kredit bei Eroeffnung, Kosten beim
Schliessen), Kommission fuer 2 Legs statt 1.

```bash
python scripts/run_backtest.py --spread-type put_spread --spread-width 10 \
    --start 2024-01-02 --end 2024-01-31
```

`spread_type` (`naked`/`put_spread`) und `spread_width` stehen ebenfalls unter
`strategy:` in [config/settings.yaml](config/settings.yaml).

### Grid-Search (parallelisiert)

`scripts/run_gridsearch.py` fuehrt eine Parametermatrix (kartesisches Produkt
ueber beliebige Achsen) parallel ueber `ProcessPoolExecutor` aus. Jeder
Worker-Prozess laedt die historisierten Tagesdaten im Zeitraum **einmal** beim
Start in einen prozesslokalen Cache und wertet darauf alle ihm zugewiesenen
Parameter-Kombinationen aus — Disk-I/O wird nur `n_jobs`-mal bezahlt, nicht
einmal pro Kombination (ersetzt die anfangs erwogene physische Parquet-
Konsolidierung).

```bash
# 3 Ziel-Deltas x 2 Profit-Targets = 6 Kombinationen:
python scripts/run_gridsearch.py --start 2024-01-02 --end 2024-01-31 \
    --target-delta 0.10,0.16,0.20 --profit-target 0.20,0.30

# Naked vs. Put-Spread (zwei Breiten) im selben Lauf, 8 Worker, Leaderboard speichern:
python scripts/run_gridsearch.py --spread-type naked,put_spread \
    --spread-width 5,10 --n-jobs 8 --top 10 --csv out/backtests/grid.csv
```

Nicht per Komma-Liste angegebene Optionen bleiben fix auf dem Config-/Basis-
Wert (keine Achse). Ergebnis ist ein nach `--sort-by` (Default `total_pnl`)
sortiertes Leaderboard: eine Zeile pro Parameter-Kombination.

```bash
python tests/test_backtest_offline.py     # inkl. Put-Spread-Tests
python tests/test_gridsearch_offline.py   # build_param_grid + _run_one, ohne Prozess-Pool
```

## Naechste Phasen

- **Phase 4:** Streamlit-Dashboard (Strategie-Vergleich, Chance/Risiko-Profil)
