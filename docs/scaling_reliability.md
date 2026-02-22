# Scaling and Reliability

## 1. Horizontal Scalability

The architecture is designed to scale across multiple CPU cores and servers to handle high-frequency market data workloads typical of Indian equities and derivatives markets.

**Partitioned Consumption**

Kafka consumer groups distribute workload automatically across multiple instances of the MarketDataProcessor, enabling elastic scaling and fault tolerance.

**Parallel Processing**

The system leverages `asyncio.gather` to execute independent I/O operations concurrently, such as:

- Database persistence (TimescaleDB)
- Redis ring buffer updates

This prevents downstream bottlenecks during periods of peak market activity (e.g., market open).

**Stateless Workers**

Processing nodes are designed to be stateless, with state externalized to Redis and TimescaleDB. This allows:

- Rapid horizontal scaling
- Safe restarts and failover
- Simplified orchestration

---

## 2. Storage Optimization (TimescaleDB)

Handling tens of millions of tick records requires a storage engine optimized for time-series workloads.

**Hypertables**

The `ticks` table is implemented as a TimescaleDB hypertable partitioned on `exchange_ts`, ensuring:

- Bounded index growth
- Efficient time-range scans
- Predictable query performance


**Continuous Aggregation**

OHLCV candles (1-minute and 5-minute intervals) are computed via continuous aggregates, shifting heavy computation away from the API layer.

**Optimized Indexing**

A composite index on:

(instrument_token, exchange_ts ASC)

aligns with dominant access patterns:

- Historical queries
- Replay engine scans
- Time-range lookups

---

## 3. Data Integrity and Reliability

Reliability is achieved through deterministic processing, idempotent storage, and proactive anomaly detection.

**Real-time Gap Detection**

The SequenceTracker monitors per-instrument `sequence_id` progression. Missing sequences result in ticks being flagged as `STALE`.

**Feed Idempotency**

Duplicate packets arising from redundant feeds are filtered using Redis-backed deduplication keys.

**Database Safety Net**

Persistence logic uses idempotent writes:

ON CONFLICT DO NOTHING

ensuring Kafka retries or worker restarts do not introduce duplicate rows.

**Memory Efficiency**

The ReplayEngine employs:

- Async generators
- Chunked database reads (e.g., 5000 rows)

This maintains flat memory usage even when replaying large datasets.

---

## 4. Backpressure and Flow Control

To protect the system from slow consumers and volatile traffic bursts, the platform enforces bounded resource usage.

**WebSocket Ring Buffer**

Recent ticks required for T₀ → T client synchronization are served from a Redis-backed ring buffer, avoiding expensive database reads.

**Eviction Policy**

Each WebSocket connection maintains a bounded outbound queue. On overflow:

- Oldest messages are evicted
- Latest ticks are prioritized

**Freshness Priority**

The system prioritizes liveness and price freshness over perfect completeness, reflecting real-world trading system requirements.
