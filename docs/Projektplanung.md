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
