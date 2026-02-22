# Market Data Platform -- API & Streaming Contract

## 1. Overview

This document defines the external interfaces of the Market Data
Platform.

The platform provides:

-   Instrument discovery APIs
-   Historical tick & candle retrieval
-   Real-time streaming via WebSocket
-   Backpressure & integrity semantics
-   Replay compatibility guarantees

All APIs use JSON encoding and ISO-8601 timestamps (UTC).

Base URL:

https://`<host>`{=html}/api/v1

WebSocket Endpoint:

wss://`<host>`{=html}/ws

------------------------------------------------------------------------

## 2. REST API Contracts

### 2.1 Instrument Search

Endpoint: GET /instruments/search

Purpose: Resolves user queries into canonical instrument identifiers
(`instrument_token`).

Query Parameters:

-   query (string, required)

Example Request:

GET /api/v1/instruments/search?query=RELIANCE

Response:

{ "data": \[ { "instrument_token": 12345, "exchange": "NSE",
"tradingsymbol": "RELIANCE", "instrument_type": "EQ" } \] }

------------------------------------------------------------------------

### 2.2 Historical Ticks

Endpoint: GET /historical/ticks

Purpose: Fetches raw tick-by-tick events from the hot time-series store.

Query Parameters:

-   instrument_token (integer, required)
-   from (ISO-8601 timestamp, required)
-   to (ISO-8601 timestamp, required)

Response:

{ "data": \[ { "exchange_ts": "2026-02-20T09:15:01.123Z", "price":
2500.50, "volume": 100 } \] }

Notes:

-   Historical responses do not include LIVE / STALE flags
-   Data is assumed finalized

------------------------------------------------------------------------

### 2.3 Historical Candles (OHLCV)

Endpoint: GET /historical/candles

Query Parameters:

-   instrument_token (integer)
-   interval (1m / 5m)
-   from
-   to

Response:

{ "data": \[ { "bucket": "2026-02-20T09:15:00Z", "open": 2498.00,
"high": 2502.50, "low": 2497.50, "close": 2500.50, "volume": 15420 } \]
}

------------------------------------------------------------------------

## 3. WebSocket Protocol

Connection: wss://`<host>`{=html}/ws

### Subscription Request (Client → Server)

{ "action": "subscribe", "tokens": \[12345, 67890\] }

------------------------------------------------------------------------

### Backfill Phase (Server → Client)

{ "type": "backfill", "instrument_token": 12345, "data": \[...\] }

Semantics:

-   Data sourced from Redis Ring Buffer
-   Represents recent ticks only

------------------------------------------------------------------------

### Live Tick Events (Server → Client)

{ "type": "tick", "instrument_token": 12345, "price": 2500.50, "volume":
100, "status": "LIVE" }

Status Values:

-   LIVE → Normal stream
-   STALE → Sequence gap detected

------------------------------------------------------------------------

## 4. Backpressure & Flow Control

REST APIs:

429 Too Many Requests

WebSocket:

-   Bounded outbound queues
-   Oldest messages evicted on overflow

Rationale:

Freshness prioritized over completeness.

------------------------------------------------------------------------

## 5. Replay Compatibility

Replay events are injected into the same Kafka topics as live ingestion.

Guarantees:

-   Identical downstream behavior
-   Deterministic ordering

------------------------------------------------------------------------

## 6. Error Semantics

-   400 Bad Request → Invalid parameters
-   404 Not Found → Unknown instrument
-   429 Too Many Requests → Rate limiting
-   500 Internal Server Error → System failure