# Data Catalog — QuantFlow Gold (v0.1)

Chaque source = un connecteur Python qui écrit un Parquet canonique
`data/processed/<source>/latest.parquet`.

Schéma commun (long format) :

| colonne | type | notes |
|---|---|---|
| `date` | datetime | date d'observation (UTC-naive pour daily, UTC-aware pour intraday) |
| `metric` | str | nom unique de la série (préfixe = source) |
| `value` | float | observation numérique |
| `unit` | str | `usd/oz`, `tonnes`, `contracts`, `pct`, `bps`, etc. |
| `source` | str | égal à `<connector.name>` |
| `ingested_at` | datetime (UTC) | horodatage d'ingestion |
| `<extra>` | — | colonnes spécifiques optionnelles (ticker, country, query, region…) |

---

## 1. `fred` — macro US (FRED / St. Louis Fed)
- **Type** : macro. **Clé requise** : oui (gratuite).
- **Fréquence** : daily (selon série, parfois monthly).
- **Historique** : 50+ ans.
- **Métriques** : real yields, nominal yields, breakevens, DXY, Fed Funds, CPI, M2, Fed balance sheet, RRP, TGA, VIX, STLFSI, HY spread, LBMA gold fix AM/PM, FX majors.
- **Endpoint** : `https://api.stlouisfed.org/fred/series/observations`
- **Clé** : créer sur https://fred.stlouisfed.org/docs/api/api_key.html

## 2. `cftc_cot` — positioning COMEX
- **Type** : positioning. **Clé** : non.
- **Fréquence** : hebdomadaire (vendredi 15:30 ET, snapshot du mardi).
- **Historique** : 2006 (Disaggregated), 1986 (Legacy).
- **Métriques** : managed money long/short/net/spread, PMPU long/short/net, swap dealers, non-reportables, open interest, pour Gold / Silver / Copper / Pt / Pd.
- **Endpoint** : Socrata `https://publicreporting.cftc.gov/resource/72hh-3qpy.json`

## 3. `etf_holdings` — flux ETF or (SPDR GLD)
- **Type** : flows. **Clé** : non.
- **Fréquence** : daily (T+1).
- **Historique** : 2004 → aujourd'hui.
- **Métriques** : `gld_tonnes`, `gld_nav`, `gld_price`, `gld_shares_outstanding`, `gld_aum_usd`, `gld_flow_tonnes_d1` (dérivé).
- **Endpoint** : `http://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv`

## 4. Sources retirées du pipeline (avril 2026)
Les connecteurs suivants ont été **supprimés du code** (plus d’écriture Parquet, plus de maintenance) :
| ID | Raison | Alternative |
|----|--------|-------------|
| `comex_stocks` | CME bloque l’accès programmatique aux inventaires COMEX (403). | `cftc_cot`, `etf_holdings`, `central_bank_gold` |
| `us_mint` | Mirror gratuit gelé en 2012 ; site US Mint derrière Cloudflare. | **`perth_mint`** (§ suivant) |
| `reddit` | API Reddit / PRAW non opérationnelle côté équipe (clés indisponibles). | `google_trends`, `gdelt`, `wikipedia`, `stocktwits`, `mining_news` |

## 5. `perth_mint` — ventes physiques Perth Mint (Western Australia)
- **Type** : physical (retail). **Clé** : non.
- **Fréquence** : monthly (publiée ~10 jours après la fin du mois).
- **Historique** : octobre 2024 → présent (URL slug avant cette date utilise
  un autre schéma, à backfiller plus tard).
- **Métriques** :
  - `perth_mint_gold_oz` (troy oz of minted gold sold worldwide)
  - `perth_mint_silver_oz`
  - `perth_mint_silver_gold_ratio_retail` (ratio dérivé)
  - `pmgold_holdings_oz` (ASX:PMGOLD client holdings — gold ETP listé en Australie)
- **Pourquoi utile** : Perth Mint est la **plus grande raffinerie du monde
  occidental** (~10% de l'or nouvellement extrait). Les ventes mensuelles de
  produits frappés = proxy de demande retail physique côté APAC, complémentaire
  des flux ETF (institutionnel) et de la COT (spéculatif). Spike d'octobre 2025
  (85,603 oz vs ~30,000 oz en moyenne) capté par exemple.
- **Endpoint** : enumération du pattern d'URL prédictible
  `https://www.perthmint.com/news/investor/market-research-and-analysis/<month>-<year>-sales-update/`,
  parsing regex de la phrase d'introduction.

## 6. `sge` — Shanghai Gold Exchange
- **Type** : physical EM. **Clé** : non.
- **Fréquence** : daily.
- **Historique** : 2024+ (via l'endpoint international ; SGE publie depuis 2002 sur la version chinoise).
- **Métriques** : close / volume / open interest / delivery pour Au99.99, Au(T+D), mAu(T+D), Au100g, Ag(T+D).
- **Endpoint** : `https://en.sge.com.cn/data/data_daily_international_new`

## 7. `central_bank_gold` — réserves or des banques centrales
- **Type** : physical. **Clé** : non.
- **Fréquence** : monthly.
- **Métriques** : `cb_gold_tonnes_<country>`, `cb_gold_world_total_tonnes`, `cb_gold_top10_share_pct`.
- **Sources** : WGC XLSX (primaire) + fallback Wikipedia "Gold reserve".

## 8. `yahoo` — prix daily OHLCV multi-actifs
- **Type** : price. **Clé** : non (yfinance).
- **Fréquence** : daily.
- **Historique** : start par défaut **1996-01-01** ; chaque ticker rend ce qu'il
  a depuis sa date d'inception (^GSPC 1962, ^IRX 1960, GC=F 2000-08, GLD 2004-11,
  GDX 2006-05, BTC-USD 2014-09, PAXG-USD 2020). Override possible via
  `--start 2000-01-01` etc.
- **Métriques** : `<slug>_open/high/low/close/adj_close/volume` pour ~60 tickers : gold/silver futures, mini, platine, palladium, copper, énergie, FX (DXY, JPY, EUR, CNY, INR, TRY), rates (^TNX, ^IRX, ^FVX, ^TYX), vol (^VIX, ^GVZ, ^OVX), crypto (BTC, ETH, PAXG), ETFs (GLD, IAU, GLDM, SGOL, BAR, PHYS, SLV, GDX, GDXJ, SIL, RING, NUGT, JNUG), miners majors (NEM, GOLD, AEM, FNV, WPM, KGC, GFI, AU, AGI, PAAS, HL, FSM, AG, EXK, HMY, IAG, EGO, NGD, OR, SAND), benchmarks equity (^GSPC, ^NDX, ^HSI, 000001.SS).

## 9. `historical_long` — prix spot long history multi-devises
- **Type** : price. **Clé** : non.
- **Historique** : 1968+ pour USD (LBMA fix via FRED), 5+ ans pour les ETFs Yahoo.
- **Sources** :
  1. **FRED CSV** (no-key, `fred.stlouisfed.org/graph/fredgraph.csv`) : LBMA Gold PM/AM
     fix USD/oz + DEXUSEU/UK/AL, DEXJPUS, DEXCHUS, DEXINUS, DEXSZUS, DEXCAUS, DEXTHUS,
     DEXKOUS pour dériver gold-en-EUR/GBP/JPY/CNY/INR/CHF/CAD/AUD/THB/KRW.
  2. **Yahoo Finance ETFs** (yfinance, fallback robuste) : PHGP.L (GBp), EGLN.L (EUR),
     4GLD.DE (EUR), PHAU.L / SGLD.L (USD), GLD, IAU.
- **Métriques exposées** :
  - Brutes : `gold_london_pm_fix_usd`, `gold_london_am_fix_usd`, `usd_per_eur`,
    `jpy_per_usd`, etc.
  - Dérivées : `gold_pm_fix_eur`, `gold_pm_fix_gbp`, `gold_pm_fix_jpy`, …
  - Yahoo : `gold_etf_eur_close`, `gold_etf_gbp_close`, `gld_us_close`, …
- **Note Stooq** : la source originale (`stooq.com/q/d/l/?s=xauusd`) est désormais
  derrière une captcha-API key payante → abandonnée.

## 10. `sec_edgar` — filings miners
- **Type** : mining / event. **Clé** : non (User-Agent avec email requis).
- **Fréquence** : event-driven.
- **Métriques** : `edgar_<miner>_filing_<form>` (10-K, 10-Q, 8-K, 20-F) + company facts XBRL (Revenues, NetIncome, CashAndCashEquivalentsAtCarryingValue, LongTermDebtNoncurrent, etc.).
- **Miners couverts** : NEM, GOLD, AEM, KGC, FNV, WPM, GFI, AU, HL, PAAS, AG.
- **Endpoint** : `https://data.sec.gov/submissions/` + `companyfacts/`.

## 11. `miners_yahoo` — ratios dérivés
- **Dépend de** `yahoo/latest.parquet`.
- **Métriques** : `gdx_gld_ratio`, `gdxj_gdx_ratio`, `sil_slv_ratio`, `gold_silver_ratio`, `gold_copper_ratio`, `gold_oil_ratio`, `gold_sp500_ratio`, `gold_btc_ratio`, `miners_relative_strength_20d`, `<miner>_beta_gold_90d`.

## 12. `google_trends` — attention retail
- **Clé** : non (mais rate-limité).
- **Fréquence** : weekly (daily sur 90j).
- **Historique** : 2004.
- **Régions** : GLOBAL, US, IN, TR, VN, RU, DE, FR, HK, CA, AU.
- **Keywords** : `buy gold`, `gold price`, `gold crash`, `silver squeeze`, `inflation`, `recession`, `fed rate`, `dollar collapse`, + équivalents FR / ES / DE / TR / HI / VI / ID.

## 13. `gdelt` — news global tone + volume
- **Clé** : non.
- **Fréquence** : daily.
- **Queries** : gold price, central bank gold, gold reserves, inflation hedge, mine disruption, bullion, etc. Tone (-10/+10) + volume (% d'articles).

## 14. `wikipedia` — pageviews multi-langue
- **Clé** : non.
- **Fréquence** : daily.
- **Pages** : Gold, Gold_standard, Hyperinflation, Weimar_Republic, Fiat_money, Federal_Reserve, Gold_reserve + FR/DE/TR/HI/ZH/RU/ES.

## 15. `stocktwits` — sentiment live par symbole
- **Clé** : non (public endpoint, ~200 req/h).
- **Fréquence** : daily (snapshot des 30 derniers messages).
- **Symbols** : GLD, IAU, GDX, GDXJ, SLV, SIL, NEM, GOLD, AEM, KGC, FNV, NUGT.
- **Métriques** : messages_recent, bullish_pct, bearish_pct, unique_users, msgs_per_hour_est.

## 16. `usgs_earthquakes` — séismes zones minières
- **Clé** : non.
- **Fréquence** : daily (historique récupérable).
- **Régions** : South Africa, Nevada, WA, Peru, West Africa, PNG, Russia Far East, Indonesia, Canada, Kyrgyzstan, Uzbekistan, China.
- **Métriques** : count M>=4.5 / jour, max_mag, énergie totale.

## 17. `open_meteo` — météo sites miniers
- **Clé** : non.
- **Fréquence** : daily archive.
- **Sites** : Carlin, Witwatersrand, Kalgoorlie, Yanacocha, Obuasi, Lihir, Muruntau, Kumtor, Porgera, Timmins, Red Lake, Oyu Tolgoi, Grasberg.
- **Variables** : T°C max/min/mean, précipitations, neige, vent max.

## 18. `defillama` — stablecoins & gold tokens on-chain
- **Clé** : non.
- **Fréquence** : daily.
- **Métriques** : `defi_stablecoins_total_supply`, per-peg breakdown, per-coin snapshots, `defi_paxg_tvl`, `defi_tether_gold_tvl`, `defi_total_tvl`.

## 19. `treasury_tga` — US Treasury cash & dette
- **Type** : macro / liquidity. **Clé** : non (API Fiscal Data).
- **Fréquence** : daily.
- **Historique** : 2010+ (TGA), 1993+ (debt to penny).
- **Métriques** :
  - `tga_open_balance_open` / `_close` (mln USD, Operating Cash Balance Treasury General Account)
  - `tga_total_deposits_open`, `tga_total_withdrawals_open`
  - `debt_held_by_public`, `debt_intragov_holdings`, `debt_total_public` (USD)
- **Pourquoi utile** : la TGA est devenue un proxy de net-liquidity système ; la
  dynamique vs Fed RRP (déjà dans `fred`) est un input classique pour les
  régressions or-macro.
- **Endpoint** : `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance` + `/v2/accounting/od/debt_to_penny`.

## 20. `binance_gold` — tokens gold + digital gold (Binance public)
- **Type** : alt / price. **Clé** : non.
- **Fréquence** : daily klines + snapshot 24h.
- **Historique** : depuis 2020 (PAXG), 2019 (XAUT, BTC, ETH, BNB).
- **Métriques** :
  - Klines daily : `paxg_usdt_open/high/low/close/volume/quote_volume/trades`,
    idem `xaut_usdt_*`, `btc_usdt_*`, `eth_usdt_*`, `bnb_usdt_*`.
  - Snapshot 24h : `*_price_change_pct_24h`, `*_vwap_24h`, `*_volume_24h`,
    `*_high_24h`, `*_low_24h`, `*_trade_count_24h`.
- **Pourquoi utile** : PAXG / XAUT = retail-gold 24/7 ; le premium vs LBMA fix
  (à dériver côté quant) est un signal de stress physique. BTC/ETH = digital-gold
  cross-check.
- **Endpoint** : `https://api.binance.com/api/v3/{klines,ticker/24hr}`.

## 21. `coingecko_gold` — gold-tokens fundamentals
- **Type** : alt / on-chain. **Clé** : non (free tier ~10 req/min).
- **Fréquence** : daily snapshot + 90j d'historique.
- **Métriques** :
  - Live : `paxg_price_usd`, `paxg_market_cap_usd`, `paxg_volume_24h_usd`,
    `paxg_change_pct_24h`, `paxg_circulating_supply_oz`, `_total_supply_oz`,
    `_max_supply_oz` (idem XAUT, KAU, AWG, DGX, PMGT).
  - Historique : `<slug>_price_usd_d`, `_market_cap_usd_d`, `_volume_usd_d` (90 jours).
- **Pourquoi utile** : market cap = oz physiques en custody (LBMA-grade) ; les
  variations de supply = primary issuance / redemption = livraison physique réelle.
- **Endpoint** : `https://api.coingecko.com/api/v3/simple/price`, `/coins/<id>/market_chart`,
  `/coins/<id>`.

## 22. `mining_news` — headlines RSS gold-mining + VADER
- **Type** : sentiment. **Clé** : non.
- **Fréquence** : daily (snapshot des derniers items publiés).
- **Feeds** : `mining.com/feed/`, `goldswitzerland.com/feed/`.
- **Filtre** : keywords `gold`, `bullion`, `xau`, `comex`, `lbma`, `newmont`,
  `barrick`, `agnico`, `kinross`, `gdx`, `gld`, `iau`, `miner`, `mine`, `smelter`,
  `refinery`, `ounce`.
- **Métriques** : `news_<feed>_polarity` (compound VADER), `_pos`, `_neg`, `_neu`,
  `_count`, plus `news_kw_<keyword>_count`.
- **Persistance** : items bruts (titre, description, lien, date) en JSON dans
  `data/raw/mining_news/` pour ré-évaluer le sentiment avec un autre modèle plus tard.

---

## Sources documentées mais NON implémentées encore

### Blocage = URL instable, scraping lourd, ou API payante

- **ICE / CME settlement CSV** — déjà disponible via IBKR (Market Data L2), à archiver via `ib_insync` (cf. `docs/ibkr_ingestion.md`).
- **Swiss customs (Swiss-Impex)** — le moteur de recherche ne renvoie pas directement en API. À scrape via Selenium ou en téléchargeant mensuellement les XLS officiels. Roadmap Sprint 2.
- **HK Census & Statistics** — exports mensuels XLS, URL stable, à ajouter. (1-2 jours de dev.)
- **UK HMRC Trade Info** — API gratuite mais gating via accès datalab. À creuser.
- **India DGCIS Trade Statistics** — portail Tradestat, scraping fragile. Alternative : GTIS (payant).
- **IMF IFS SDMX** — API existe mais schéma instable depuis refonte 2024. À retester.
- **Royal Canadian Mint / Royal Mint UK** — sales annuels publiés en PDF (rapport
  annuel govinfo.gov pour la USMint, idem pour les autres). À parser au besoin.

### Bonus "farfelu" qui resteraient à tester

- **Baidu Index** — nécessite login + OCR anti-bot. Pas gratuit en pratique.
- **Naver Datalab** — API Korean gratuite, intéressant pour l'or coréen.
- **YouTube Data API** — implémentable, 10k req/jour gratuit : compte et volume de vidéos "gold price crash".
- **Kitco news RSS** — simple à ajouter si besoin d'un flux daily headlines.
- **SEDAR+ (miners canadiens)** — API JSON en beta, à tester.
- **Archive.org Wayback** — utile pour reconstituer l'historique de pages qui n'ont pas d'API.

---

## Livraison aux quants

Pour lire l'ensemble en DuckDB :

```sql
INSTALL parquet; LOAD parquet;
SELECT * FROM 'data/processed/*/latest.parquet'
WHERE metric LIKE 'gold_%'
ORDER BY date DESC LIMIT 100;
```

Ou en pandas :

```python
import duckdb, pandas as pd
df = duckdb.sql("SELECT * FROM 'data/processed/*/latest.parquet'").to_df()
```

Ou en polars :

```python
import polars as pl
pl.scan_parquet("data/processed/*/latest.parquet").collect()
```

Le dossier `data/processed/<source>/snapshots/` garde une copie horodatée de chaque run pour audit / backfill / reproductibilité.
