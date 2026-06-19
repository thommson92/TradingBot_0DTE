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
scripts/
  download_data.py            CLI: Daten laden
  check_data.py               CLI: Qualitaets-Report
tests/
  test_pipeline_offline.py    Offline-End-to-End-Test
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

## Naechste Phasen

- **Phase 2:** Backtest-Engine (1 Strategie: nackter Short Put)
- **Phase 3:** Parametermatrix (Grid-Search, parallelisiert) + Put-Spreads
- **Phase 4:** Streamlit-Dashboard (Strategie-Vergleich, Chance/Risiko-Profil)
