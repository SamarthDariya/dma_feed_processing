import asyncio
import aioredis
import asyncpg
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

# Importing our custom-built modules
from normalize import normalize_event
from deDuplicator import Deduplicator #
from sequenceTracker import SequenceTracker #
from db_layer import DatabaseLayer 
from processor import MarketDataProcessor

async def main():
    # 1. Initialize Infrastructure Connections
    # TimescaleDB / Postgres Connection Pool
    db_pool = await asyncpg.create_pool(
        user='postgres', password='password',
        database='market_data', host='127.0.0.1'
    )
    
    # Redis Client for Deduplication and Backfill
    redis_client = aioredis.from_url("redis://localhost", decode_responses=True)

    # Kafka Consumer (Reading raw feed) and Producer (Writing normalized data)
    consumer = AIOKafkaConsumer(
        'raw_ticks',
        bootstrap_servers='localhost:9092',
        group_id="processing_group"
    )
    producer = AIOKafkaProducer(bootstrap_servers='localhost:9092')

    # 2. Start Services
    await consumer.start()
    await producer.start()

    try:
        # 3. Initialize the Processor and DB Schema
        processor = MarketDataProcessor(
            kafka_consumer=consumer,
            kafka_producer=producer,
            redis_client=redis_client,
            db_pool=db_pool
        )

        # Ensure TimescaleDB hypertables and OHLCV aggregates are ready
        #
        print("Initializing Database Schemas...")
        await processor.db_layer.initialize_schema()
        await processor.db_layer.create_candle_aggregates()

        # 4. Launch the Real-Time Processing Loop
        print("Market Data Processor is LIVE. Consuming raw_ticks...")
        await processor.run()

    finally:
        # Graceful Shutdown
        await consumer.stop()
        await producer.stop()
        await db_pool.close()
        await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())