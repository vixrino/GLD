# QuantFlow Gold — Free Data Sources

Stack de collecte, structuration et livraison de données **gratuites** pour le trading systématique sur l'or (et par extension argent / miners).

> **Rôle** : data manager. On ne fait pas de stratégie. On livre des tables propres, versionnées, datées, documentées.

---

## TL;DR — comment démarrer

```bash
# Depuis la racine du repo (datascrap/)
python -m venv .venv && source .venv/bin/activate
pip install -r quantflow_gold/requirements.txt
cp quantflow_gold/.env.example .env
# Éditer `.env` à la racine du repo : **FRED_API_KEY** (gratuit, obligatoire pour le connecteur `fred`)
#   https://fred.stlouisfed.org/docs/api/api_key.html

# Voir la liste des connecteurs
python -m quantflow_gold.run --list

# Lancer tous les connecteurs sans clé (macro FRED exclue si pas de FRED_API_KEY)
python -m quantflow_gold.run --all --only-no-key

# Lancer tout (FRED est sauté si FRED_API_KEY manquante ; le reste tourne)
python -m quantflow_gold.run --all

# Cibler une source
python -m quantflow_gold.run --source yahoo
python -m quantflow_gold.run --source cftc_cot
python -m quantflow_gold.run --source etf_holdings

# Shortcuts
./scripts/backfill_all.sh
./scripts/daily_refresh.sh
./scripts/weekly_refresh.sh
```

Sortie : `data/processed/<source>/<source>_YYYY-MM-DD.parquet`
Schéma commun minimal : `date`, `value`, `metric`, `unit`, `source`, `ingested_at`.

---

## Pourquoi Parquet ?

Proposition de livraison (à valider avec les quants — voir `docs/questions_quants.md`) :

| Besoin quant | Format proposé | Pourquoi |
|---|---|---|
| Backtest, feature store | **Parquet** partitionné par `source` / `date` | Colonnaire, compressé, lit vite avec pandas/polars/duckdb |
| Interactif / ad-hoc | **DuckDB** sur les parquets | `SELECT … FROM 'data/processed/**/*.parquet'` zéro infra |
| Live / latence faible (carnet IBKR) | **CSV horodaté → Parquet** batch | Le L2 Gold IBKR c'est une ingestion à part (cf. `docs/ibkr_ingestion.md`) |

Pas de Postgres pour l'instant. On l'ajoutera seulement si les quants ont besoin de joins multi-tables complexes.

---

## Catalogue complet — sources gratuites identifiées

Voir [`docs/data_catalog.md`](docs/data_catalog.md) pour le détail. Résumé :

### 🟢 Implémenté (priorité 1)

| # | Source | Type | Fréquence | Historique | Connecteur |
|---|---|---|---|---|---|
| 1 | **FRED** (real yields, DXY, CPI, Fed Funds, M2, breakevens, TIPS) | Macro | Daily | 50+ ans | `connectors/macro/fred.py` |
| 2 | **CFTC Disaggregated COT** (Gold & Silver COMEX) | Positioning | Weekly (mardi, publié vendredi) | 2006 | `connectors/positioning/cftc_cot.py` |
| 3 | **GLD / IAU / GLDM holdings** | Flows ETF | Daily | 2004 (GLD) | `connectors/flows/etf_holdings.py` |
| 4 | **Perth Mint** monthly minted-product sales (gold + silver oz, PMGOLD ETP holdings) | Retail physical | Monthly | 2024-10+ | `connectors/physical/perth_mint.py` |
| 5 | **Shanghai Gold Exchange** daily report (Au99.99, T+D, deliveries) | Physical EM | Daily | 2024+ | `connectors/physical/sge.py` |
| 6 | **Central bank gold reserves** (WGC XLSX + Wiki fallback) | Physical | Monthly | — | `connectors/physical/central_bank_gold.py` |
| 7 | **Yahoo Finance** (GC=F, SI=F, GLD, GDX, GDXJ, DXY, TNX, VIX, miners) | Price | Daily | 1962+ (par ticker) | `connectors/price/yahoo.py` |
| 8 | **Long-history multi-currency gold** (FRED LBMA fix + DEX FX, fallback Yahoo gold ETFs) | Price | Daily | 1968+ | `connectors/price/historical_long.py` |
| 9 | **Miners ratios dérivés** (GDX/GLD, GSR, Gold/Copper, betas) | Mining | Daily | — | `connectors/mining/miners_yahoo.py` |
| 10 | **SEC EDGAR** — Newmont, Barrick, Agnico, Kinross, FNV, WPM, +5 | Mining | Event-driven | 1993+ | `connectors/mining/sec_edgar.py` |
| 11 | **Google Trends** (pytrends) — multi-keywords × 11 régions | Sentiment retail | Weekly (daily sur 90j) | 2004 | `connectors/sentiment/google_trends.py` |
| 12 | **GDELT 2.0 Doc API** — 11 queries, tone+volume | News global | 15min | 2015 | `connectors/sentiment/gdelt.py` |
| 13 | **Wikipedia pageviews** — 21 pages en/fr/de/tr/hi/zh/ru/es | Attention | Daily | 2015 | `connectors/sentiment/wikipedia.py` |
| 14 | **StockTwits** — GLD/GDX/miners sentiment snapshot | Sentiment | Daily | — | `connectors/sentiment/stocktwits.py` |
| 15 | **USGS earthquakes** — M≥4.5 dans 12 zones minières | Alt / supply | Daily | 2010+ | `connectors/alt/usgs_earthquakes.py` |
| 16 | **Open-Meteo archive** — météo 13 sites miniers majeurs | Alt / supply | Daily | 1979+ | `connectors/alt/open_meteo.py` |
| 17 | **DefiLlama** — stablecoin supply & PAXG/XAUT TVL | Alt / macro | Daily | 2018+ | `connectors/alt/defillama.py` |
| 18 | **US Treasury TGA + debt-to-penny** (fiscaldata API) | Macro / liquidity | Daily | 2010+ | `connectors/macro/treasury_tga.py` |
| 19 | **Binance public** — PAXG, XAUT, BTC, ETH, BNB klines + 24h ticker | Alt / price | Daily | 2019+ | `connectors/alt/binance_gold.py` |
| 20 | **CoinGecko** — gold-tokens market cap, supply, 24h vol | Alt / on-chain | Daily | 2018+ | `connectors/alt/coingecko_gold.py` |
| 21 | **Mining.com + GoldSwitzerland RSS** + VADER scoring | News / sentiment | Daily | recent | `connectors/sentiment/mining_news.py` |

*Retirés du pipeline (données vides ou API non viable pour l’équipe) : `comex_stocks`, `us_mint`, `reddit` — voir `docs/data_catalog.md` § « Sources retirées ».*

### 🟡 À brancher facilement (documenté, connecteur stub)

| Source | Description | Endpoint |
|---|---|---|
| **World Gold Council** | Holdings ETF globales, demande trimestrielle, central banks | `gold.org/goldhub/data` |
| **WGC Central Bank Gold Reserves** | Achats/ventes par pays, mensuel | `gold.org` CSV download |
| **Swiss Federal Customs** (Swiss-Impex) | Imports/exports d'or par pays (la Suisse = hub mondial) | `gate.ezv.admin.ch` |
| **UK ONS** — Non-monetary gold imports | Flux UK (vault de Londres) | `ons.gov.uk` |
| **HKMA / HK Census Trade** | Flux or Hong Kong → Chine (proxy demande chinoise) | `censtatd.gov.hk` |
| **Royal Canadian Mint** | Rapports trimestriels | RCM annual reports |
| **CBOE GVZ** (Gold VIX) | Vol implicite sur GLD | Yahoo `^GVZ` |
| **ICE / CME settlement CSV** | Prix règlement GC, SI, OI (via CME public pages) | `cmegroup.com/market-data/settlements` |
| **BIS Central Bank Gold** | Réserves officielles | `bis.org/statistics` |
| **IMF COFER** | Composition réserves FX monde | `data.imf.org` |
| **Fed H.4.1 / H.8** | Balance sheet Fed (proxy liquidité USD) | FRED (déjà inclus) |
| **ECB Data Portal** | Réserves or Eurosystem | `data.ecb.europa.eu` |
| **StockTwits** — symbol GLD, GDX | Message volume + sentiment | `api.stocktwits.com` |
| **GitHub/academic** — Kenneth French, AQR | Factor data (pour régressions) | `mba.tuck.dartmouth.edu` |

### 🔴 Farfelu mais ça fonctionne (à tester)

| Source | Logique | Fréquence |
|---|---|---|
| **Indian Meteorological Department** | Mousson en Inde = demande gold indienne (mariage season) | Saisonnier |
| **Baidu Index / 百度指数** | "黄金" (or) trends en Chine — proxy demande asiatique | Daily |
| **Naver Datalab** (Corée) | Trends locale Corée du Sud | Weekly |
| **Google Trends — régions** | Turquie, Inde, Vietnam, Russie (fort retail gold) | Weekly |
| **FlightRadar24 historical** | Cargo flights Zurich↔NY pendant stress (limited free) | À valider |
| **Wikipedia edit activity** | Éditions pages "Gold standard", "Central bank gold reserves" = intérêt crises | Daily |
| **Archive.org Wayback** | Historique de `kitco.com` headlines pour sentiment backfilling | Ad-hoc |
| **ArXiv daily papers** | Volume papers "gold", "commodity", "safe haven" = intérêt académique | Daily |
| **YouTube Data API v3** | Volume de videos "gold price", "inflation crash" = retail hype | Daily (quota 10k/jour gratuit) |
| **Crypto TVL / stablecoin supply** | Tether / USDC supply = proxy liquidité USD offshore | Daily (DefiLlama free API) |
| **Open-Meteo (archive)** | Température en Alaska / Yukon / WA = saison mining disruptions | Daily |
| **USGS Earthquakes** | Séismes > M5 dans régions minières (Nevada, Peru, Australie) | Real-time |
| **ACLED / GDELT** | Conflits en Afrique (Ghana, Burkina Faso, Soudan = gold informel) | Real-time |
| **Twitter/X academic via Bluesky / nitter** | Alternative gratuite depuis que X API est payante | Variable |

---

## Structure du projet

```
datascrap/
├── data/
│   ├── raw/                        # artefacts originaux (XLS, PDF, JSON)
│   └── processed/                  # Parquet canonique par source
│       └── <source>/
│           ├── latest.parquet      # toujours à jour
│           └── snapshots/          # horodatage pour audit/reproductibilité
├── docs/
│   ├── data_catalog.md             # catalogue complet des sources
│   ├── questions_quants.md         # cadrage à faire avec l'équipe
│   └── ibkr_ingestion.md           # roadmap L2 IBKR
├── notebooks/
│   └── 00_explore_gold_data.ipynb  # DuckDB + pandas
├── scripts/
│   ├── backfill_all.sh
│   ├── daily_refresh.sh
│   └── weekly_refresh.sh
└── quantflow_gold/
    ├── connectors/
    │   ├── macro/
    │   │   ├── fred.py
    │   │   └── treasury_tga.py
    │   ├── positioning/cftc_cot.py
    │   ├── flows/etf_holdings.py
    │   ├── physical/
    │   │   ├── perth_mint.py              # retail mint sales (remplace ancien us_mint)
    │   │   ├── sge.py
    │   │   └── central_bank_gold.py
    │   ├── mining/
    │   │   ├── sec_edgar.py
    │   │   └── miners_yahoo.py
    │   ├── price/
    │   │   ├── yahoo.py
    │   │   └── historical_long.py
    │   ├── sentiment/
    │   │   ├── google_trends.py
    │   │   ├── gdelt.py
    │   │   ├── wikipedia.py
    │   │   ├── stocktwits.py
    │   │   └── mining_news.py
    │   └── alt/
    │       ├── usgs_earthquakes.py
    │       ├── open_meteo.py
    │       ├── defillama.py
    │       ├── binance_gold.py
    │       └── coingecko_gold.py
    ├── core/
    │   ├── base.py                  # BaseConnector + canonical run()
    │   ├── schema.py
    │   └── utils.py
    ├── storage/
    │   └── parquet_writer.py
    ├── run.py                       # CLI
    └── requirements.txt
```

---

## Roadmap

### Sprint 1 — DONE
- [x] Scaffolding + **21 connecteurs** actifs (FRED = seule clé API requise : `FRED_API_KEY`)
- [x] `run --all` orchestrateur + scripts cron-like
- [x] Catalogue documenté (`docs/data_catalog.md`)

### Sprint 2 (en cours)
- [ ] Faire tourner `run --all --only-no-key` sur 5 ans d'historique pour backfill
- [ ] Livrer 1er dump Parquet aux quants
- [ ] Containerisation : packager le repo en Docker (équipe, prochaine étape)
- [ ] Quality checks (`pandera` ou `great_expectations`)
- [ ] Intégrer IBKR L2 gold (stream TWS via `ib_insync`) — voir `docs/ibkr_ingestion.md`

### Sprint 3
- [ ] Sources "farfelues" (Baidu, Naver Datalab, YouTube hype index)
- [ ] Dashboard de monitoring des connecteurs (Grafana / Streamlit)
- [ ] Feature engineering layer (real yields - DXY, paper-to-physical ratio, COT Z-score, PAXG-vs-LBMA premium)
- [ ] Cron / scheduler (Prefect ou GitHub Actions)

---

## Questions ouvertes pour les quants

Voir [`docs/questions_quants.md`](docs/questions_quants.md).
