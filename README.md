# Market Data Platform

A high-throughput market data pipeline for Indian equities and options, built to handle **10M+ ticks/day** with real-time streaming, historical replay, and OHLCV aggregation.

---

## Architecture

```
Ingestion Layer
  DMA Feed (tick-by-tick)  ──┐
  Snapshot Feed (backup)   ──┴──► asyncio Workers ──► [raw_ticks] Kafka Topic

Processing Layer
  [raw_ticks] ──► Normalize ──► Deduplicate ──► SequenceTracker ──► [normalized_ticks]

Persistence & Serving Layer
  [normalized_ticks] ──► TimescaleDB  ──► Continuous Aggregates (1m / 5m OHLCV)
                     ──► Redis        ──► Ring Buffer (WebSocket backfill)
                     ──► S3 / Parquet ──► Cold storage (archival)

  TimescaleDB / Redis ──► Historical REST API
  [normalized_ticks]  ──► WebSocket Publisher

Replay Engine
  TimescaleDB ──► Min-Heap Merge ──► [raw_ticks] Kafka Topic
```

---

## Components

| File | Role |
|---|---|
| `main.py` | Entry point — wires infrastructure and starts the processor |
| `processor.py` | Central pipeline — normalize → deduplicate → track → persist/distribute |
| `normalize.py` | Maps raw feed packets to `InternalTick` Pydantic model |
| `deDuplicator.py` | Redis SETNX-based idempotency across DMA and snapshot feeds |
| `sequenceTracker.py` | Per-symbol sequence gap detection; marks ticks `LIVE` or `STALE` |
| `BackfillRingBuffer.py` | Bounded Redis list (RPUSH + LTRIM) for WebSocket T₀→T backfill |
| `db_layer.py` | TimescaleDB schema, hypertables, continuous aggregates, and tick persistence |
| `ReplayEngine.py` | Keyset-paginated async generators + min-heap k-way merge for replay |

---

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL with TimescaleDB extension
- Redis
- Kafka / Redpanda

### Install dependencies

```bash
pip install asyncpg aioredis aiokafka pydantic
```

### Configure infrastructure

Update connection strings in `main.py`:

```python
# PostgreSQL / TimescaleDB
db_pool = await asyncpg.create_pool(
    user='postgres', password='password',
    database='market_data', host='127.0.0.1'
)

# Redis
redis_client = aioredis.from_url("redis://localhost", decode_responses=True)

# Kafka
consumer = AIOKafkaConsumer('raw_ticks', bootstrap_servers='localhost:9092', group_id="processing_group")
producer = AIOKafkaProducer(bootstrap_servers='localhost:9092')
```

### Run

```bash
python main.py
```

On startup, the platform will:
1. Initialize the TimescaleDB hypertable and indexes
2. Create continuous aggregate views for 1m and 5m OHLCV candles
3. Begin consuming from the `raw_ticks` Kafka topic

---

## Data Model

### `ticks` (TimescaleDB Hypertable)

```sql
CREATE TABLE ticks (
    exchange_ts      TIMESTAMPTZ NOT NULL,   -- partition key
    instrument_token INT         NOT NULL,
    price            NUMERIC     NOT NULL,
    volume           BIGINT      NOT NULL,
    sequence_id      BIGINT      NOT NULL,
    status           VARCHAR(10) NOT NULL,   -- LIVE | STALE
    PRIMARY KEY (exchange_ts, instrument_token)
);
```

### `instruments` (Relational)

```sql
CREATE TABLE instruments (
    instrument_token INT         PRIMARY KEY,
    tradingsymbol    VARCHAR(50) NOT NULL,
    exchange         VARCHAR(10) NOT NULL,   -- NSE | BSE | NFO
    asset_class      VARCHAR(20) NOT NULL,   -- EQ | FUT | OPT
    tick_size        NUMERIC     NOT NULL
);
```

### Continuous Aggregates

```sql
-- Auto-computed in the background; served directly by the Historical API
candles_1m  →  time_bucket('1 minute',  exchange_ts) → OHLCV
candles_5m  →  time_bucket('5 minutes', exchange_ts) → OHLCV
```

---

## API

Base URL: `https://<host>/api/v1`

| Endpoint | Method | Description |
|---|---|---|
| `/instruments/search?query=RELIANCE` | GET | Resolve symbol → `instrument_token` |
| `/historical/ticks` | GET | Raw tick-by-tick data for a time range |
| `/historical/candles` | GET | OHLCV candles (`interval=1m` or `5m`) |

### WebSocket

```
wss://<host>/ws
```

**Subscribe:**
```json
{ "action": "subscribe", "tokens": [12345, 67890] }
```

**Backfill (server → client, on connect):**
```json
{ "type": "backfill", "instrument_token": 12345, "data": [...] }
```

**Live tick:**
```json
{ "type": "tick", "instrument_token": 12345, "price": 2500.50, "volume": 100, "status": "LIVE" }
```

`status` is `LIVE` under normal conditions and `STALE` when a sequence gap is detected upstream.

---

## Replay

Replay any historical trading day across one or more symbols at variable speed:

```python
engine = ReplayEngine(db_pool, kafka_producer)

await engine.start_replay(
    symbols=["RELIANCE", "NIFTY25JANFUT"],
    target_date="2026-01-15",
    speed=10.0   # 1.0 = real-time | 10.0 = 10x | float('inf') = burst
)
```

Replay events are injected into `raw_ticks` and traverse the identical processing pipeline as live data — normalization, deduplication, sequence tracking, and persistence all apply.

**Implementation:** Async generators per symbol with keyset pagination (`exchange_ts > last_seen_ts`) feed a min-heap that guarantees global chronological ordering across symbols.

---

## Failure Handling

| Failure | Response |
|---|---|
| Packet loss / sequence gap | Tick flagged `STALE`; pipeline continues without blocking |
| Duplicate packets (DMA + Snapshot overlap) | Filtered by Redis `SETNX` before processing |
| Worker crash | Kafka offset not committed → automatic redelivery on restart |
| DB duplicate on redelivery | `ON CONFLICT DO NOTHING` absorbs replayed writes safely |
| Slow WebSocket consumer | Bounded outbound queue; oldest messages evicted, latest ticks prioritized |

---

