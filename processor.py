import asyncio
from BackfillRingBuffer import RedisBackfillRingBuffer
from normalize import normalize_event, InternalTick #
from deDuplicator import Deduplicator #
from sequenceTracker import SequenceTracker #
from db_layer import DatabaseLayer # New Database Layer

class MarketDataProcessor:
    """
    The central coordination worker for the Market Data Platform.
    Integrates normalization, deduplication, sequence tracking, and persistence.
    """
    def __init__(self, kafka_consumer, kafka_producer, redis_client, db_pool):
        self.consumer = kafka_consumer
        self.producer = kafka_producer
        
        # Initialize Logic Components
        self.deduplicator = Deduplicator(redis_client) #
        self.sequence_tracker = SequenceTracker() #
        
        # Initialize Storage Components
        self.db_layer = DatabaseLayer(db_pool) # Optimized Persistence Layer
        self.backfill_buffer = RedisBackfillRingBuffer(redis_client) # T0 -> T Cache

    async def run(self):
        """
        Main execution loop for the 7-day sprint deliverable.
        Consumes raw feed events and applies the full processing stack.
        """
        # Ensure database schemas/hypertables are ready before processing
        await self.db_layer.initialize_schema()
        await self.db_layer.create_candle_aggregates()

        async for message in self.consumer:
            raw_packet = message.value
            
            # 1. Normalization: Map raw feed to internal Pydantic model
            tick: InternalTick = normalize_event(raw_packet, feed_type="DMA")

            # 2. Deduplication: Filter out redundant snapshot feed events
            if await self.deduplicator.is_duplicate(tick):
                continue

            # 3. Sequence Tracking: Flag gaps and mark status as LIVE or STALE
            tick = self.sequence_tracker.process_and_flag(tick)

            # 4. Storage & Distribution (Parallel Execution)
            await asyncio.gather(
                self.db_layer.save_tick(tick),      # Persist to TimescaleDB
                self.update_distribution(tick)      # Update Redis and Kafka
            )

    async def update_distribution(self, tick: InternalTick):
        """
        Handles real-time distribution tasks simultaneously.
        """
        # Update Redis Ring Buffer for instant WebSocket backfills
        await self.backfill_buffer.add_tick(tick.symbol, tick.dict())
        
        # Push to 'normalized_ticks' Kafka topic for the WebSocket Publisher
        await self.producer.send("normalized_ticks", tick.json())