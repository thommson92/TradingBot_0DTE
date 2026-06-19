# Projektplanung — TradingBot 0-DTE (Backtesting-Tool)

> Status: **Planungsphase** (noch kein Code). Dieses Dokument hält Nachfragen,
> Entscheidungen und die abgeleitete Spezifikation fest.
> Letzte Aktualisierung: 2026-06-18

## 1. Projektüberblick

Werkzeug zur **Erarbeitung und Backtesting** von 0-DTE-Optionsstrategien, das später
die Grundlage für einen automatisierten Trading-Bot bildet. Fokus: **Verkauf von Puts**
(nackt oder als Put-Spread mit definiertem Verlust), die idealerweise wertlos verfallen
oder günstiger zurückgekauft werden.

- **Geschäftsziel:** Profitable, robuste 0-DTE-Strategie finden, die ein Bot automatisiert handeln kann.
- **Zielgruppe:** Einzelnutzer (der Projektinhaber).
- **Sprache/Tech:** Python.
- **Bot/Live-Trading:** Vorerst **außerhalb des Scopes** (Architektur soll später aber daran anknüpfen).

## 2. Entscheidungs-Log (Nachfragen & Antworten)

| # | Nachfrage | Entscheidung |
|---|-----------|--------------|
| Instrument | SPY vs. SPX/XSP (Assignment-, Steuer-, Settlement-Unterschiede) | **SPX** (europäisch, cash-settled, kein vorzeitiges Assignment). Gehandelt werden die SPXW-0-DTE-Optionen. |
| 1 | Datenquelle (IBKR limitiert für intraday-Optionshistorie) | Beste/günstigste Alternative wählen; **kein Abo vorhanden**. → Empfehlung **ThetaData** (siehe §4). |
| 2 | Datengranularität | **Minütlich (1 Min.)** — entspricht dem abgeschlossenen ThetaData-Abo. Bekannte Einschränkung: 2x/3x-Stops in der Schlussphase ggf. leicht zu optimistisch (siehe §3.3). Upgrade auf feiner später möglich. |
| 3 | Historientiefe | Zurück bis **Start der täglichen Verfälle (~2022)**. |
| 4 | Greeks-Herkunft | **Direkt aus der Datenquelle** (nicht selbst berechnen). |
| 5 | Entry / Strike-Wahl | **Max. 1 Trade pro Tag**; Strike-Wahl primär über **Ziel-Delta**. |
| 6 | Exit-Regeln | **Profit-Target 30 %** der Prämie; **Stop-Loss 2x oder 3x** Prämie; Alternative: **immer 5 Min. vor Close** schließen. |
| 7 | Spread-Breite | **5 oder 10 Index-Punkte**. |
| 8 | Position Sizing | **Fixe Kontraktzahl = 1**. |
| 9 | Fill-Annahmen | **Mid minus Slippage**, inkl. **Kommissionen**. |
| 10 | Kennzahlen | Win-Rate, Gesamt-P/L, Max Drawdown, Sharpe/Sortino, Profit-Faktor, Expectancy — **reicht zunächst**. |
| 11 | Bedienoberfläche | **Dashboard** (z. B. Streamlit/Dash). |
| 12 | Parallelisierung | **Ja** — Grid-Search über hunderte bis tausende Varianten. |
| 13 | Live-Bot | **Vorerst außen vor.** |
| 14 | MVP-Reihenfolge | **Bestätigt:** 1) Datenpipeline + Speicherung → 2) eine Strategie (nackter Short Put) → 3) Parametermatrix + Spreads. |
| 15 (2026-06-19) | ML-Ansatz | **Gestaffelt:** zuerst Supervised-EV-Scorer (Gradient-Boosting), der den erwarteten Trade-Ausgang vorhersagt; RL als optionaler späterer Aufsatz. Begründung: bei nur 1088 Handelstagen ist reines RL überanpassungsanfällig und schwer validierbar; der Supervised-Ansatz reicht schneller ein belastbares Signal und nutzt die bestehende Engine als Label-Generator. |
| 16 (2026-06-19) | Lern-Scope | **Entry zuerst gelernt** (Timing, Ziel-Delta, naked/Spread), **Exit zunächst regelbasiert** (fixe, grid-gesuchte Stop/Target/Zeit-Regel). Exits werden in einem Folgeschritt mitgelernt (Kandidatenraum erweitern). |
| 17 (2026-06-19) | Validierung | **Walk-Forward** (rollierendes/expandierendes Training) **+ unberührtes Holdout-Jahr** (letzte ~12 Monate, nie für Training/Threshold-Tuning gesehen). Versöhnt „komplette Historie fürs Training" mit ehrlicher Out-of-Sample-Bewertung. |
| 18 (2026-06-19) | Zielgröße | **Komposit-Ziel:** Balance aus hohem Gesamt-P&L, hoher Trefferquote und geringem Max-Drawdown (nicht eine einzelne Kennzahl). Wird als gewichteter/normierter Score auf der Walk-Forward-Equity-Kurve berechnet und zum Tuning der Policy-Schwelle genutzt. |

## 3. Abgeleitete Spezifikation (Entwurf)

### 3.1 Instrument & Marktannahmen
- Underlying: **SPX**, Optionen **SPXW** (tägliche Verfälle, europäisch, cash-settled).
- Multiplikator 100; 1 Kontrakt ≈ Index × 100 Notional.
- Kein Assignment-/Dividenden-Modell nötig (cash-settled, europäisch).
- Settlement der 0-DTE am Handelsschluss (PM-Settlement).

### 3.2 Strategie-Parameter (variabel, Basis der Testmatrix)
- **Typ:** nackter Short Put **oder** Put-Spread.
- **Spread-Breite:** {5, 10} Index-Punkte (bei Spread).
- **Entry-Uhrzeit:** parametrisierbar (eine Uhrzeit/Tag, max. 1 Trade/Tag).
- **Strike-Wahl:** Ziel-Delta (z. B. 0.10 / 0.16 / 0.20 …).
- **Profit-Target:** 30 % der Prämie (parametrisierbar).
- **Stop-Loss:** {2x, 3x} Prämie (parametrisierbar) — oder deaktiviert.
- **Zeit-Exit:** Schließen 5 Min. vor Close (parametrisierbar) — oder bis Verfall halten.
- **Handelstage:** filterbar (Wochentage / bestimmte Tage).
- **Sizing:** 1 Kontrakt (fix, später erweiterbar).

### 3.3 Backtest-Engine
- **Event-getrieben** entlang der **1-Minuten**-Quote-Historie (für Stop-/Target-/Zeit-Exit-Handling).
- **Bekannte Einschränkung (Minutengranularität):** Intra-minütliche Ausschläge werden nicht erfasst; 2x/3x-Stops in der Schlussphase tendenziell leicht zu optimistisch. Zeit-Exit „5 Min. vor Close" ist unbeeinträchtigt.
- **Fills:** Mid ± Slippage (Verkauf erhält Mid − Slippage, Rückkauf zahlt Mid + Slippage).
  - **Slippage-Default:** 25 % des Bid/Ask-Spreads, adversativ angewendet (parametrisierbar).
- **Kommissionen:** Default **~1,10 USD pro Kontrakt und Leg** (IBKR-nahe: Commission + Exchange/Reg-Fees, parametrisierbar). Beim Spread fallen Gebühren für beide Legs an.
- **Kennzahlen:** Win-Rate, Gesamt-P/L, Max Drawdown, Sharpe, Sortino, Profit-Faktor, Expectancy/Trade.
- **Parametermatrix:** Grid-Search, **parallelisiert** (z. B. multiprocessing / joblib).

### 3.4 Bedienung
- **Dashboard (Streamlit)** zum Definieren von Strategien, Starten von Läufen und Vergleichen der Ergebnisse
  (Performance-Vergleich + Chance/Risiko-Profil). Streamlit gewählt: schnell zu bauen, ideal für Single-User.

## 4. Datenquelle (Empfehlung)

**ThetaData** als primäre Quelle:
- NBBO-Quotes für SPXW mit einstellbarem Intervall (1-Sekunden-Sampling möglich).
- Greeks + IV werden mitgeliefert.
- History ≥ 2022.
- Kosten grob ~30–80 USD/Monat je nach Tier (aktuellen Stand prüfen).

> **Hinweis:** Eine kostenlose Quelle für sekündliche Optionsketten mit Greeks ab 2022 existiert nicht.
> Alternativen: Polygon.io (Greeks rückwirkend schwächer), CBOE DataShop / Databento (autoritativ, teurer).

### Storage-Konzept (Entwurf)
- **1-Min-Quotes**, nur **Puts im Delta-Band ~0.01–0.50** (statt Vollkette) → schlankes Volumen.
- **Parquet**, partitioniert pro Handelstag; Abfrage via **DuckDB**.
- **Beschaffung:** Komplett-Download über das laufende **ThetaData-Abo**.
  - **AGB-Konformität (Nutzerentscheidung):** Abo läuft weiter; sobald es erlischt, werden die lokalen Daten gelöscht.
  - **API-Key:** Wird **niemals** ins Repo/Doku geschrieben — Ablage in `.env` (gitignored) bzw. Umgebungsvariable. (Der im Chat genannte Key sollte rotiert werden.)

## 5. Offene Punkte / vor Spezifikations-Freigabe zu klären
- [x] Sampling-Intervall: **10 s einheitlich**.
- [x] Slippage-Modell: **25 % des Bid/Ask-Spreads**, adversativ (parametrisierbar).
- [x] Kommissionsmodell: **~1,10 USD/Kontrakt/Leg** (IBKR-nah, parametrisierbar).
- [x] Dashboard-Framework: **Streamlit**.
- [x] Stop-Loss 2x/3x: bezogen auf die **Eröffnungsprämie** (Rückkaufpreis ≥ 2x/3x).
- [x] Beschaffung: **1-Monats-Abo → Download → Kündigung**.
- [x] ThetaData: **monatliches SPX-Abo (minütlich) abgeschlossen.** AGB-Konformität via „Daten bei Abo-Ende löschen".
- [x] Strike-/Delta-Band: **Puts mit Delta ~0.01–0.50** (deckt Short-Strikes + Long-Legs der Spreads ab).

**→ Spezifikation vollständig. Nächster Schritt: MVP-Phase 1 (Datenpipeline + Speicherung).**

## 7. Umsetzungs-Log

### Phase 1 — Datenpipeline (implementiert)
- Projektgerüst, ThetaData-Client, Download→Parquet, DuckDB-Layer, QC, CLIs, Offline-Test.
- Offline-End-to-End-Test besteht (synthetische Daten).

### ThetaData v2 → v3 geklärt (Key ist v3)
Der `td1_prod_…`-Key ist ein **v3-Key**. Der Client wurde von v2 auf **v3** umgebaut:
- Lokaler REST-Server **Port 25503**, Pfad-Präfix `/v3`.
- Auth: **API-Key direkt** (`--api-key` / `THETA_DATA_API_KEY`) — kein Passwort.
- Endpunkte: `/v3/option/history/quote`, `/v3/option/history/greeks/first_order`.
- Strikes = **Dollar-Floats**, right = **`put`**, interval = **`1m`**, Bulk via `strike="*"`.
- **Java 21+** nötig (auf dem Rechner ist nur Java 8 → Live-Test noch blockiert).
- **Beim ersten Live-Lauf zu verifizieren:** Antwortformat (CSV/JSON), `timestamp`-Format,
  Paginierung, Symbology (`SPX` vs. `SPXW`).

### 2026-06-19 — Wechsel auf offizielle ThetaData-Python-Library
Statt des selbstgebauten REST-Clients gegen das lokale Theta Terminal v3 nutzen
wir jetzt die offizielle **`thetadata`-Python-Library** (`pip install thetadata`,
benötigt **Python 3.12+**):
- Verbindet sich per **gRPC direkt mit der ThetaData-Cloud** — kein lokales
  Theta Terminal/Java-Prozess mehr nötig (Java-Upgrade war daher nicht erforderlich,
  schadet aber nicht).
- Auth ausschließlich über `THETADATA_API_KEY` in der `.env` (`ThetaClient(api_key=...)`).
- **Live verifiziert:** `option_history_greeks_first_order` liefert `bid`/`ask`
  bereits zusammen mit den Greeks (`delta, theta, vega, rho, implied_vol,
  underlying_price`) — ein separater Quote-Call ist daher unnötig. Einziger
  Verlust: `bid_size`/`ask_size` (nur im separaten Quote-Endpunkt verfügbar,
  aktuell nicht benötigt).
- **Symbology live geklärt:** `SPX` hat nur monatliche/quartalsweise Verfälle.
  Für tägliche 0-DTE-Verfälle ist **`SPXW`** das richtige Symbol
  (`config/settings.yaml: data.symbol`).
- **Abo-Stufen wichtig:** Das ursprüngliche ThetaData-Abo ("Value"-Tier) deckte
  den Options-Greeks-Endpunkt nicht ab (`PERMISSION_DENIED`, braucht mind.
  "Option Data Standard"). Index-Endpunkte (SPX-Kassakurs) erfordern zusätzlich
  ein separates Index-Abo (mind. "Value"-Tier) — aktuell nicht gebucht, aber auch
  nicht mehr nötig, da der Greeks-Endpunkt `underlying_price` mitliefert.
  **Nutzer hat auf "Option Data Standard" upgegradet** → Greeks-Abruf funktioniert.
- `thetadata_client.py` ist jetzt ein dünner Wrapper um `thetadata.ThetaClient`
  (`list_expirations`, `history_greeks`); `download.py` braucht nur noch einen
  API-Call pro Handelstag (vorher zwei + Merge).
- **Vollständige Historie geladen** (2022-01-03 bis 2026-06-18): 1088 Handelstage,
  ~64,5 Mio. Zeilen, ~832 MB Parquet unter `data/parquet/SPXW/`. 1 Tag ohne Daten
  (kein 0-DTE-Verfall). QC-Report zeigt 76 Werktags-„Lücken" — das sind keine
  fehlenden Daten, sondern (a) Markt-Feiertage und (b) die historische
  Cboe-Erweiterung der SPXW-Verfälle: Anfang 2022 gab es nur Mo/Mi/Fr-Verfälle,
  Di/Do kamen erst im Laufe des Jahres 2022 dazu. Die QC-Heuristik kennt den
  Börsenkalender/die Verfalls-Historie nicht und meldet das als „Lücke".

### 2026-06-19 — Phase 2: Backtest-Engine (nackter Short Put)
Neues Modul `src/tradingbot_0dte/backtest/` (params, trade, fills, strategy,
engine, metrics) + CLI `scripts/run_backtest.py` + `strategy:`-Abschnitt in
`config/settings.yaml`.

- **Entscheidung #5 angepasst (Nutzer-Vorgabe):** „Max. 1 Trade pro Tag" ist
  **kein festes Kriterium im Code** mehr. Stattdessen: konfigurierbare Liste
  `entry_times` (beliebig viele Entry-Zeiten/Tag) + konfigurierbares
  `max_trades_per_day` (`null` = unbegrenzt) + `max_concurrent_positions`
  (Default 1, kein Stacking). Ein Tag mit nur einer Entry-Zeit verhält sich wie
  bisher; mehr Entry-Zeiten/höheres Limit ergeben mehr Trades/Tag ohne
  Code-Änderung. Entry-Zeiten werden sequentiell verarbeitet — jede Position
  wird sofort bis zum Exit durchsimuliert, bevor die nächste Entry-Zeit geprüft
  wird (vereinfacht den Concurrency-Check, kein paralleles Bar-Stepping nötig).
- **Exit-Priorität:** Stop-Loss → Profit-Target → Zeit-Exit (Risiko zuerst),
  alle drei einzeln nullable (für spätere A/B-Tests in Phase 3). Kein Exit bis
  Tagesende → Fallback `expiration` (Schluss zum letzten verfügbaren Bar).
- **Bug gefunden & gefixt:** `MarketData` (DuckDB) konvertierte `TIMESTAMPTZ`-
  Spalten beim Export nach pandas in die **lokale System-Zeitzone** (hier
  Europe/Berlin) statt in die beim Schreiben verwendete **US/Eastern-Zeit** —
  dadurch verglichen Entry-Zeiten wie `09:35:00` gegen die falsche Wanduhrzeit
  (0 Trades im ersten Smoke-Test). Fix: `SET TimeZone='America/New_York'` auf
  der DuckDB-Connection (`storage.py`). Betraf nur die Backtest-Engine (die
  Phase-1-QC-Checks vergleichen keine Wanduhrzeiten, daher unbemerkt).
- **Sharpe/Sortino-Annahme:** berechnet auf der Tages-P&L-Reihe (annualisiert
  `sqrt(252)`), nicht auf prozentualen Returns — bei fixer Kontraktzahl=1 (Entscheidung
  #8) gibt es keine definierte Kapitalbasis.
- **Verifiziert:** Offline-Tests grün (`test_backtest_offline.py`,
  `test_pipeline_offline.py`); Smoke-Test Januar 2024 (21 Trades, Win-Rate 71%,
  plausible Strikes/Exits) und Volljahr 2023 (250 Trades, ~30s Laufzeit,
  ~10 Handelstage/s) gegen die echten historisierten Daten geprüft.

### 2026-06-19 — Phase 3: Put-Spreads + Grid-Search/Parallelisierung
Erweitert `src/tradingbot_0dte/backtest/` um Put-Spread-Unterstützung (ohne
Breaking Changes am nackten Put) + neues Modul `gridsearch.py` +
CLI `scripts/run_gridsearch.py`. Setzt Entscheidungen #7 (Spread-Breite
{5,10}), #12 (parallelisierte Grid-Search) und #14 (MVP-Reihenfolge) um.

- **Long-Leg-Wahl per Nearest-Match:** `pick_long_leg()` sucht den Strike, der
  `short_strike - spread_width` am nächsten liegt, statt einen exakten Match zu
  verlangen — SPX-Strikeabstände sind nicht überall exakt gleich breit. Live
  gegen echte Daten verifiziert: Januar 2024 liefert bei Breite 10 durchgehend
  exakte `long_strike = short_strike - 10`-Treffer.
- **Schwellenwert-Logik geteilt statt dupliziert:** `check_exit()` wurde in eine
  gemeinsame `_check_thresholds()` (Stop-Loss → Profit-Target → Zeit-Exit,
  unverändert) plus zwei dünne Wrapper aufgeteilt — `check_exit()` (nackter Put,
  Signatur/Verhalten unverändert) und `check_exit_spread()` (Netto-Spread-Wert
  als aktueller Preis). Bestehende 5 Phase-2-Tests bleiben unverändert grün.
- **Grid-Search-Performance:** statt die Parquet-Dateien physisch zu
  konsolidieren (in der vorherigen Diskussion erwogen und verworfen), lädt jeder
  `ProcessPoolExecutor`-Worker die Tagesdaten im Zeitraum einmal beim Start
  (Pool-`initializer`) in einen prozesslokalen Cache und wertet darauf alle ihm
  zugewiesenen Parameter-Kombinationen aus. Disk-I/O wird nur `n_jobs`-mal
  bezahlt, kein Pickle/IPC großer DataFrames zwischen Prozessen nötig.
  Stdlib-`ProcessPoolExecutor` verwendet (kein neues Abhängigkeit zu `joblib`).
- **Beobachtung Smoke-Test (Januar 2024, Breite 10):** Put-Spread liefert bei
  gleichen Stop/Target-Parametern wie der nackte Put eine **niedrigere
  Win-Rate** (57% vs. 71%) und negatives Gesamt-P&L (-287 USD vs. +538 USD beim
  nackten Put im selben Zeitraum) — die Long-Leg verringert den Netto-Kredit
  stark (typ. ~1.00–1.40 USD statt ~2.00 USD Prämie), wodurch der relative
  2x-Stop-Loss-Schwellenwert schon bei kleineren Indexbewegungen greift. Das ist
  ein erwartetes Charakteristikum enger Spreads (begrenzter Verlust, aber auch
  empfindlichere relative Schwellenwerte) und kein Bug — eine Optimierung der
  Stop/Target-Parameter speziell für Spreads ist Aufgabe der Grid-Search, nicht
  dieser Phase.
- **Verifiziert:** Offline-Tests grün (`test_backtest_offline.py` inkl. 2 neuer
  Put-Spread-Tests, neues `test_gridsearch_offline.py`); Smoke-Test Put-Spread
  Januar 2024 gegen echte Daten; Grid-Search-Smoke-Test (`naked,put_spread` x
  Breite `5,10` = 4 Kombinationen, `--n-jobs 4`) — Ergebnis für
  `put_spread/Breite 10` deckt sich exakt mit dem einzelnen Backtest-Lauf
  (-287.40 USD), `spread_width` hat erwartungsgemäß keinen Effekt auf
  `naked`-Zeilen.

### 2026-06-19 — Phase 4: Streamlit-Dashboard
Neues Verzeichnis `dashboard/` (Home `app.py` + drei Seiten unter `pages/`),
letzter MVP-Baustein laut Entscheidung #11/#14 und §3.4 (Strategien
definieren, Läufe starten, Ergebnisse vergleichen — Performance + Chance/
Risiko-Profil). Einzige neue Abhängigkeit: `streamlit`; Diagramme über die
nativen `st.line_chart`/`st.bar_chart`/`st.scatter_chart` (kein zusätzliches
Plotting-Paket).

- **Subprocess statt Pool für die Grid-Search-Seite:** ein
  `ProcessPoolExecutor` direkt aus dem Streamlit-Skript heraus zu starten ist
  riskant — Streamlit-Skripte laufen ohne `if __name__ == "__main__":`-Guard
  auf Modulebene, und der `spawn`-Start (macOS) importiert das `__main__`-
  Modul in jedem Worker neu, was im Worst Case zum erneuten Booten der ganzen
  App pro Worker führen könnte. Die Grid-Search-Seite ruft daher das bereits
  einzeln getestete `scripts/run_gridsearch.py` als Subprocess auf und lädt das
  resultierende Leaderboard-CSV zurück, statt `gridsearch.run_grid()` im
  Streamlit-Prozess aufzurufen. Der Einzel-Backtest hat dieses Problem nicht
  (kein Pool) und ruft `engine.run()` direkt im Prozess auf.
- **Lauf-Persistenz (`dashboard/runs.py`):** bewusst ohne Streamlit-Import
  gehalten (reine Logik), damit sie wie der restliche Kern offline testbar ist
  (`test_dashboard_runs_offline.py`). Jeder gespeicherte Lauf schreibt
  CSV (Trade-Log)/JSON (Metrics bei Backtests) unter `out/backtests/` und
  hängt eine flache Zeile an `out/backtests/runs_index.csv` an, damit die
  Vergleichsseite Läufe auflisten kann, ohne jede Ergebnisdatei erneut zu
  parsen. Bei Grid-Search-Läufen repräsentiert die Index-Zeile die **beste**
  Zeile des Leaderboards; `csv_path` zeigt auf das volle Leaderboard für den
  Drilldown auf der Vergleichsseite.
- **Verifiziert:** alle Offline-Tests grün (inkl. neuem
  `test_dashboard_runs_offline.py`, 4 Tests); manueller Smoke-Test über
  `streamlit.testing.v1.AppTest` (kein Browser nötig) gegen echte historisierte
  Daten — Home zeigt den korrekten Datenzeitraum (1088 Handelstage,
  20220103–20260618); Backtest-Seite liefert mit Defaults über die letzten 90
  Tage 63 Trades/69.8% Win-Rate/+3706.40 USD und lässt sich speichern;
  Grid-Search-Seite liefert über einen 2-Werte-Delta-Achse (Subprocess) ein
  Leaderboard ohne Exception und lässt sich speichern; Vergleichsseite zeigt
  beide gespeicherten Läufe (Tabelle, Balkendiagramm, Scatter, Grid-Search-
  Drilldown) ohne Fehler. `use_container_width` (in dieser Streamlit-Version
  bereits über dem Removal-Datum) durch `width="stretch"` ersetzt.

## 8. Phase 5 — ML-gesteuerte Entry-Strategie (Planung, 2026-06-19)

> Status: **geplant**, noch nicht implementiert. Setzt Entscheidungen #15–#18 um.
> Ziel: Die KI lernt aus der **kompletten Historie**, *wann*, mit *welchem Delta*
> und als *naked Put oder Put-Spread* eröffnet wird — ohne feste Vorgaben bei
> Uhrzeit, Delta oder Trade-Anzahl. Exit-Regeln bleiben in diesem Schritt fix
> (regelbasiert), werden aber in einem Folgeschritt mitgelernt.

### 8.1 Grundidee (Supervised-EV-Scorer als Contextual Bandit)
Statt jede Minute „blind" zu handeln, bewertet ein Modell **Trade-Kandidaten**:
- Ein **Kandidat** = (Entry-Zeit-Bar, Ziel-Delta-Bucket, Strategietyp ∈
  {naked, spread-5, spread-10}).
- **Features** = leakage-sicherer Marktzustand zum Entry-Zeitpunkt (nur Daten
  bis zu diesem Bar).
- **Label** = der **real simulierte P&L** dieses Kandidaten, erzeugt durch die
  **bestehende Engine** (`_simulate_naked_entry` / `_simulate_spread_entry`) mit
  einer fixen Exit-Regel. Zusätzlich Win-Flag und Exit-Grund.
- Das Modell lernt also: „Gegeben dieser Marktzustand und dieser Kandidat —
  welcher P&L / welche Gewinnwahrscheinlichkeit ist zu erwarten?"
- **Policy** (Inferenz): an jedem Bar alle Kandidaten scoren; jene über einer
  getunten Schwelle eröffnen. Keine harte Trade-Anzahl-Grenze (Wunsch des
  Nutzers); mehrere/überlappende Trades/Tag erlaubt, P&L additiv (Optionen sind
  unabhängige, cash-gesettelte Instrumente → keine komplexe Concurrency-Sim
  nötig, jeder gewählte Trade wird einzeln durchsimuliert und tagesweise
  summiert).

### 8.2 Features (Entwurf, alle leakage-sicher zum Entry-Bar)
- **Zeit:** Minuten seit Open, Minuten bis Close, Wochentag, (Monat).
- **Underlying:** Return seit Open, Open-Gap ggü. Vortagesschluss, intraday
  realisierte Vola (rollierende Minuten-Returns bis Entry).
- **Vol-Surface:** ATM-IV, IV des Kandidaten-Strikes, einfacher Put-Skew
  (IV(0.10Δ) − IV(0.30Δ)), IV-Änderung seit Open.
- **Kandidat:** Ziel-Delta, Delta/Theta/Vega des gewählten Strikes, Prämie
  (Credit) relativ zum Underlying, Spread-Breite (bei Spread), Bid/Ask-Spread
  (Liquiditätsproxy).
- Modul `ml/features.py`, rein aus `day_df` + Vortageskontext berechnet.

### 8.3 Modell
- **Default:** `sklearn.ensemble.HistGradientBoostingRegressor` (P&L-Regression)
  **+** `…Classifier` (P(Win)). Bewusst gewählt, weil das venv auf **Python 3.14**
  läuft und LightGBM/XGBoost dort evtl. noch keine Wheels haben; HGB ist dieselbe
  Modellfamilie (histogrammbasiertes GBDT) ohne fragile Native-Abhängigkeit.
- **Optionales Upgrade:** LightGBM, falls Wheel/Build verfügbar (gleiche
  Schnittstelle, hinter einem Adapter gekapselt).
- Interpretierbar: Feature-Importances + Permutation-Importance fürs Dashboard.

### 8.4 Validierung & Overfitting-Schutz (Entscheidung #17)
- **Walk-Forward:** expandierendes Trainingsfenster, Vorhersage auf dem jeweils
  nächsten Block (z. B. quartalsweise), rollierend über 2022→2025.
- **Purging/Embargo:** keine Überlappung zwischen Train- und Test-Tagen (0-DTE
  → Trades enden am selben Tag, daher genügt ein Tages-Embargo).
- **Holdout:** letzte ~12 Monate (≈ 2025-07 … 2026-06) werden **nie** fürs
  Training oder Schwellen-Tuning angefasst — finaler Realitäts-Check.
- Realistische Kosten sind bereits in der Engine (Slippage + Kommission).
- Reporting immer **In-Sample vs. OOS vs. Holdout** nebeneinander.

### 8.5 Komposit-Zielgröße (Entscheidung #18)
- Per-Trade-Lernen liefert nur Scores; das **Portfolio-Ziel** wird auf der
  Equity-Kurve der Policy bewertet (nutzt `metrics.compute_metrics`:
  `total_pnl`, `win_rate`, `max_drawdown`).
- **Komposit-Score** (Default, konfigurierbar): normierte, gewichtete
  Kombination aus P&L↑, Win-Rate↑ und Max-Drawdown↓ (z. B.
  Calmar-ähnlich `total_pnl / (1 + max_drawdown)` × Win-Rate-Faktor, mit
  Win-Rate-Mindestschwelle). Die **Policy-Schwelle** (und erlaubte
  Delta-Buckets/Strategietypen) werden auf den Walk-Forward-Validierungsblöcken
  so gewählt, dass dieser Score maximal wird — Drawdown fließt also über die
  Selektion ein, nicht per Trade.

### 8.6 Geplante Module & CLIs
- `src/tradingbot_0dte/ml/features.py` — Feature-Engineering.
- `src/tradingbot_0dte/ml/labels.py` — Kandidat → simulierter P&L (Engine-Reuse).
- `src/tradingbot_0dte/ml/dataset.py` — baut die Trainingstabelle (Tag × Kandidat
  → Features + Label), parallelisiert analog Grid-Search; Cache als Parquet.
- `src/tradingbot_0dte/ml/model.py` — Modell-Adapter (HGB-Default, LightGBM optional).
- `src/tradingbot_0dte/ml/walkforward.py` — Splits, Training je Fold, OOS-Predict.
- `src/tradingbot_0dte/ml/policy.py` — Scores → Trade-Entscheidungen (Schwellen-
  Tuning); erzeugt ein Trade-Log im selben Format wie die Engine.
- `src/tradingbot_0dte/ml/evaluate.py` — Komposit-Score + Equity-Kurve.
- Scripts: `build_ml_dataset.py`, `train_ml.py`, `run_ml_backtest.py`.
- Tests: `test_ml_features_offline.py`, `test_ml_dataset_offline.py`,
  `test_ml_policy_offline.py` (synthetische Daten, kein Marktzugriff).
- Neue Abhängigkeit: **scikit-learn** (LightGBM optional).

### 8.7 Dashboard-Anbindung (Wunsch: Backtests im Dashboard ansehen)
- Neue Seite `dashboard/pages/5_ML_Strategie.py`: Dataset bauen/laden, Modell
  trainieren, Feature-Importances anzeigen, ML-Policy-Backtest starten und als
  Lauf speichern.
- Ergebnis landet über `dashboard/runs.py` im selben `runs_index.csv` →
  **direkt vergleichbar** mit Grid-Search-/Einzel-Backtests auf der bestehenden
  Vergleichsseite (Equity-Kurve, Win-Rate, Drawdown, Scatter).

### 8.8 Umsetzungsreihenfolge (Vorschlag, je ein Commit)
1. `features.py` + `labels.py` + Offline-Test.
2. `dataset.py` (+ Script, Cache) — Trainingstabelle aus der Historie bauen.
3. `model.py` + `walkforward.py` + `train_ml.py` — Training & OOS-Predict.
4. `policy.py` + `evaluate.py` + `run_ml_backtest.py` — Policy, Komposit-Score,
   Backtest-Lauf über die Engine.
5. Dashboard-Seite + Vergleichsanbindung.
6. (Später, separate Phase) Exit-Mitlernen; danach optional RL-Aufsatz.

### 8.9 Umsetzungs-Log Phase 5

**2026-06-19 — Schritt 1: ML-Features + Label-Simulation** (`ml/features.py`,
`ml/labels.py`, `test_ml_features_offline.py`). Leakage-sicheres Feature-Set
(Zeit/Underlying/Vol-Surface/Kandidat) + `simulate_candidate()`, das das Label
(realer P&L) über die bestehenden Engine-Simulatoren erzeugt (eine Quelle der
Wahrheit). 5 Offline-Tests inkl. Leakage-Prüfung; Smoke-Test gegen echte Daten.

**2026-06-19 — Schritt 2: Dataset-Aufbau** (`ml/dataset.py`,
`scripts/build_ml_dataset.py`, `test_ml_dataset_offline.py`).
`CandidateGrid` (Entry-Zeiten × Ziel-Deltas × naked/Spread) → eine Zeile je
Tag×Kandidat mit Features + Label, parallelisiert **über Tage** (jeder Tag genau
einmal von Platte gelesen). `prev_close` (für `gap_open`) wird im Hauptprozess
per DuckDB-`arg_max`-Scan vorab bestimmt und den Workern mitgegeben.
- **Bekannte Kleinigkeit:** `gap_open` ist beim **ersten Tag eines Fensters**
  NaN (kein Vortag im gefilterten Bereich) — bei einem Voll-Historie-Build genau
  1 Tag (2022-01-03). HistGradientBoosting verarbeitet NaN nativ, daher
  unkritisch; kein Imputieren nötig.
- **Verifiziert:** 4 Offline-Tests grün; End-to-End-Lauf Januar 2024
  (13 Entry-Zeiten × 3 Deltas × {naked, spread-10} = 78 Kandidaten/Tag →
  1638 Zeilen, Win-Rate 70.7 %, ~1.8 s/Tag bei 6 Workern). Parquet-Cache unter
  `out/ml/` (gitignored).
- **Performance-Hinweis:** Das Default-Vollraster (26 Entry-Zeiten × 5 Deltas ×
  3 Spread-Typen = 390 Kandidaten/Tag × 1088 Tage) ist ein einmaliger
  Cache-Build von grob 1–3 h; Rastergröße ist per CLI frei wählbar.
