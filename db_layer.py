"""
================================================================================
DATABASE LAYER: POSTGRESQL + TIMESCALEDB INTEGRATION
================================================================================
This module handles persistence for 10M+ ticks/day by combining relational
metadata (Postgres) with optimized time-series storage (TimescaleDB).

Key Features:
1. Hypertables: Partitioning raw ticks by time for efficient disk I/O.
2. Continuous Aggregates: Automatic background calculation of OHLCV candles.
3. Composite Indexing: Optimized for Historical API and Replay Engine queries.
================================================================================
"""

import asyncio

class DatabaseLayer:
    """
    Encapsulates schema creation and data persistence logic.
    """
    def __init__(self, db_pool):
        self.db = db_pool

    async def initialize_schema(self):
        """
        Sets up the hybrid schema for the Market Data Platform.
        """
        # 1. Relational Metadata (Postgres)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                instrument_token INT PRIMARY KEY,
                tradingsymbol VARCHAR(50) NOT NULL,
                exchange VARCHAR(10) NOT NULL,
                asset_class VARCHAR(20) NOT NULL,
                tick_size NUMERIC NOT NULL
            );
        """)

        # 2. Time-Series Storage (TimescaleDB Ready)
        # Includes status field from SequenceTracker
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                exchange_ts TIMESTAMPTZ NOT NULL,
                instrument_token INT NOT NULL,
                price NUMERIC NOT NULL,
                volume BIGINT NOT NULL,
                sequence_id BIGINT NOT NULL,
                status VARCHAR(10) NOT NULL,
                PRIMARY KEY (exchange_ts, instrument_token)
            );
        """)

        # 3. Convert to Hypertable (TimescaleDB Optimization)
        await self.db.execute("""
            SELECT create_hypertable('ticks', 'exchange_ts', if_not_exists => TRUE);
        """)

        # 4. Optimized Index for Replay Engine Keyset Pagination
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_token_time 
            ON ticks (instrument_token, exchange_ts ASC);
        """)

    async def create_candle_aggregates(self):
        """
        Handles the automatic calculation of 1-minute and 5-minute OHLCV buckets.
        """
        # 1-Minute Continuous Aggregate
        await self.db.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS candles_1m
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', exchange_ts) AS bucket,
                   instrument_token,
                   first(price, exchange_ts) as open,
                   max(price) as high,
                   min(price) as low,
                   last(price, exchange_ts) as close,
                   sum(volume) as volume
            FROM ticks
            GROUP BY bucket, instrument_token;
        """)

        # 5-Minute Continuous Aggregate (Mandatory Requirement)
        await self.db.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS candles_5m
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('5 minutes', exchange_ts) AS bucket,
                   instrument_token,
                   first(price, exchange_ts) as open,
                   max(price) as high,
                   min(price) as low,
                   last(price, exchange_ts) as close,
                   sum(volume) as volume
            FROM ticks
            GROUP BY bucket, instrument_token;
        """)

    async def save_tick(self, tick):
        """
        Persists a normalized InternalTick to the database.
        Uses ON CONFLICT as a secondary safety net for deduplication.
        """
        # to do check query
        query = """
            INSERT INTO ticks (exchange_ts, instrument_token, price, volume, sequence_id, status)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (exchange_ts, instrument_token) DO NOTHING;
        """
        await self.db.execute(
            query, 
            tick.exchange_ts, 
            tick.instrument_token,  
            tick.price, 
            tick.volume, 
            tick.sequence_id, 
            tick.status.value 
        )