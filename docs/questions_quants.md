# Questions ouvertes pour les quants

Cette doc sert à cadrer avec les quants ce qu'on doit prioriser sur la couche data. Chaque réponse a un impact direct sur la stack.

---

## 1. Horizon de trading

- [ ] **HFT / tick-by-tick** → on doit prioriser l'ingestion L2 IBKR (ib_insync → Postgres/TimescaleDB ou kdb+). Le daily Parquet devient secondaire.
- [ ] **Intraday (minutes à heures)** → mix : L2 IBKR archivé + features daily Parquet pour le context macro.
- [x] **Swing (1-10 jours)** _(hypothèse par défaut, à valider)_ → Parquet daily suffit pour 95 % du feature store.
- [ ] **Positional (semaines-mois)** → idem, Parquet weekly/monthly + rebalancing.

## 2. Instruments tradés (au-delà du gold)

- [x] **Gold COMEX (GC, MGC)** — confirmé.
- [ ] Silver (SI) ?
- [ ] Miners (GDX, NEM, GOLD, AEM) ?
- [ ] Platine / Palladium ?
- [ ] Options sur GLD / miners ? → Impact majeur : il faut une source d'IV surface (pas gratuit sauf Yahoo options chain, limité).

## 3. Format de livraison préféré

- [x] **Parquet** partitionné par source → lit avec pandas / polars / DuckDB. _(proposition par défaut)_
- [ ] **CSV** → simple mais pas de typage, pas compressé.
- [ ] **DuckDB file** unique → requêtes SQL simples.
- [ ] **Postgres / Timescale** → bonne pour jointures complexes, overkill pour du daily.
- [ ] **Feather / Arrow IPC** → rapide à lire, moins portable.

## 4. Fréquence de refresh

- [ ] EOD une fois par jour vers 23h ET → cron `daily_refresh.sh`.
- [ ] 2× par jour (morning / evening) ?
- [ ] Intraday horaire ?
- [ ] On-demand uniquement ?

## 5. Tolérance de latence sur la donnée

| Source | Latence naturelle | Acceptable ? |
|---|---|---|
| FRED | T+1 business day | à valider |
| CFTC COT | Vendredi 15:30 ET pour snapshot mardi | oui |
| GLD holdings | T+1 | à valider |
| COMEX stocks | T+1 | oui |
| SGE | T+1 | oui |
| GDELT | 15 min | oui |
| Wikipedia | T+1 à T+2 | oui |
| Yahoo / Stooq | T+1 EOD | oui |

## 6. Bibliothèque Python cible

- [x] pandas (par défaut, schéma canonique)
- [ ] polars (si perf importante, lecture parquet ~10x plus rapide)
- [ ] modin / dask (big data; pas nécessaire ici)

Impact : si les quants codent en Julia ou R, Parquet reste lisible, pas de souci.

## 7. Text / NLP

- [ ] On livre le texte brut (raw news, posts forums) et les quants scorent eux-mêmes ?
- [x] On livre des **scores agrégés** (VADER daily, GDELT tone) et les features dérivées ?
- [ ] On utilise un LLM (FinBERT / mistral-7b) côté data pipeline ? _(coût cpu/gpu à considérer si on veut batch 100k+ articles)_

## 8. Qualité / freshness monitoring

- [ ] Simple log + alerte email si un connecteur fail 2 runs consécutifs ?
- [ ] Dashboard Streamlit / Grafana ?
- [ ] Alertes Slack / Discord ?

## 9. Backfill history

Pour chaque source, combien d'historique les quants veulent-ils ?

- FRED : 1980+ (ils ont 50 ans disponibles)
- CFTC COT : 2006+ (Disaggregated) / 1986+ (Legacy) ?
- GLD : 2004+
- Yahoo : max disponible
- Historical long (Stooq) : 1968+
- GDELT : 2015+
- ~~Reddit~~ : retiré du pipeline (API non utilisée par l’équipe).

## 10. Couverture géographique

On a du US-centric et de l'EM (Chine, Inde, Turquie). Manque à creuser si les quants veulent exploiter :

- [ ] LBMA Gold Forwards / lease rates
- [ ] Shanghai-London arb
- [ ] Dubai DGCX premiums
- [ ] Turkish BIST gold futures

---

## Livrables à planifier avec le fund manager

1. **Contrat de données** : schéma canonique = source de vérité. Changement de schéma = PR + review quant.
2. **SLA freshness** : on s'engage sur quoi ? (ex : EOD +1h, 99% uptime).
3. **Pipeline DevOps** : quand on passera sur Docker, choisir entre cron host / Prefect Cloud / GitHub Actions.
4. **Accès** : partage via S3/R2 (public bucket read-only) ou via un share NAS local ?
