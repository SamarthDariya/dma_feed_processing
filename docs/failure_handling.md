# Error Handling & Failure Mitigations

In a high-throughput market data platform processing tens of millions of ticks per day, transient failures — including packet loss, feed disconnections, component crashes, and slow consumers — are treated as normal operating conditions.

The system follows a fail-forward philosophy, prioritizing:

- Data integrity
- Idempotent processing
- High availability
- Deterministic recovery

---

## 1. Packet Loss & Data Integrity (Sequence Gaps)

Market data feeds, particularly UDP or multicast-based streams, are inherently unreliable and susceptible to packet loss.

**Detection**

A dedicated SequenceTracker monitors `sequence_id` progression on a per-instrument basis.

Gap condition:

incoming_seq > last_seq + 1

---

**Containment Strategy**

The platform does not block or halt on gap detection.

Instead:

- The affected tick is marked with `status = STALE`
- Processing continues normally

---

**Downstream Safety Guarantees**

- STALE status is attached to real-time events
- Consumers may implement defensive logic
- Prevents incorrect assumptions of perfect market state

---

## 2. Feed Redundancy & Duplicate Packets

High availability is achieved via redundant data sources (primary DMA feed + backup snapshot/recovery feed).

Redundancy naturally introduces duplicate packets.

**Idempotency Mechanism**

Duplicates are filtered using a Redis-backed deduplication key:

SETNX seen:{instrument_token}:{sequence_id}

Behavior:

- Key exists → Duplicate → Drop
- Key absent → First observation → Process

---

## 3. Component Crashes & Persistence Guarantees

Worker crashes, OOM conditions, or node restarts are expected events.

**Delivery Semantics**

Kafka consumers disable auto-commit. Offsets are committed only after successful processing.

Guarantee:

- Crash before commit → Reprocessing occurs
- No data loss

---

**Idempotent Storage Safeguard**

To tolerate replayed events:

ON CONFLICT (instrument_token, sequence_id) DO NOTHING

Prevents duplicate row insertion.

---

## 4. Network Backpressure & Slow Consumers

Market bursts can exceed client consumption capacity.

**Backpressure Strategy**

Each WebSocket connection maintains a bounded outbound queue.

On overflow:

- Oldest messages evicted
- Latest ticks prioritized

---

**Design Rationale**

Real-time consumers prioritize:

- Latest price state
- Actionable data freshness

Over complete historical delivery.

This prevents:

- Server memory bloat
- System-wide latency amplification