# IBKR L2 — pipeline d'ingestion à construire (roadmap)

Ce doc est un squelette. L'ingestion IBKR est séparée des connecteurs Python
publics car :
1. elle exige une session TWS / IB Gateway active,
2. elle produit un volume de données TRÈS différent (tick-by-tick order book),
3. elle doit tourner sur une machine "toujours allumée".

## Stack proposée

```
TWS ou IB Gateway (port 4002 / 7497)
        │
        ▼
   ib_insync (Python)
        │  subscribe MKT_DEPTH + TICK_BY_TICK for GC, SI
        ▼
   collector.py   (asyncio, buffer en mémoire 1s)
        │
        ▼
   Parquet shards (15min) sur disque local
        │
        ▼
   rsync / job quotidien → `data/raw/ibkr_l2/<date>/...`
        │
        ▼
   consolidation nightly → `data/processed/ibkr_l2/<contract>/<date>.parquet`
```

## Abonnements IBKR à activer

- **ICE Futures US Gold and Silver (L2)** → Gold GC, Silver SI order book complet (levels 1..10).
- **Trading Central Technical Insight** → archive les signaux quotidiens via l'API IBKR (`reqFundamentalData`).
- **TipRanks Basic** → scraper les ratings depuis l'iframe (HTML stable).
- **Wall Street Horizon** → events via `reqHistoricalNews` ou `reqNewsArticle`.
- **Reflexivity Basic / Acuity iFrame** → à étudier, iframe URLs à récupérer depuis DevTools.

## Contrats à pull en priorité

| Symbole | Expiry | Exchange | Notes |
|---|---|---|---|
| GC (Gold) | front-month | NYMEX | 100 oz |
| MGC (Micro Gold) | front | NYMEX | 10 oz (liquidité retail) |
| SI (Silver) | front | NYMEX | 5000 oz |
| GLD | — | ARCA | ETF, pour référence intraday |
| GDX | — | ARCA | Miners ETF |

## Sketch de code (à écrire Sprint 2)

```python
# quantflow_gold/connectors/ibkr/l2_streamer.py  (À FAIRE)
from ib_insync import IB, Future, util
import pandas as pd
from pathlib import Path

def stream_gold_book(out_dir: Path):
    ib = IB()
    ib.connect("127.0.0.1", 4002, clientId=7)
    gc = Future("GC", exchange="NYMEX")
    ib.qualifyContracts(gc)
    ib.reqMktDepth(gc, numRows=10)
    ib.reqTickByTickData(gc, "AllLast", 0, False)
    # buffer + flush every 15 min to parquet
    ...
```

Points d'attention :
- **Market data limits** : IBKR limite à 100 tickers simultanés par session gratuit. Pour un seul fund, c'est large mais à surveiller si on ajoute les silver miners.
- **Timezone** : forcer tout en UTC côté ingestion, pas de local time.
- **Reconnect** : TWS se restart chaque nuit par défaut, gérer l'auto-reconnect.
- **Disque** : le L2 Gold fait ~200-500 Mo/jour brut. 1 an ≈ 100 Go → prévoir du stockage.

## Archivage des analytics IBKR

Plus simple que le L2 :

- `reqFundamentalData(contract, "ReportSnapshot")` → renvoie XML Reuters (via abo IBKR).
- Wall Street Horizon events : `reqHistoricalNews(conId, providerCodes="WSH", ...)` → liste d'events datés.
- TipRanks : récupérer l'iframe URL dans TWS API, parser HTML.

Ces trois sont archivables dans `data/raw/ibkr_analytics/<date>/<provider>/*.json` sans contraintes de latence serrées.

---

**État actuel** : pas commencé. À planifier Sprint 2 après validation des formats Parquet par les quants.
