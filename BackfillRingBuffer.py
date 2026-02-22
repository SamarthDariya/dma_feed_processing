import json
import redis.asyncio as redis

class RedisBackfillRingBuffer:
    """
    Mandatory: Distributed ring buffer for T0 -> T client backfills using Redis.
    """
    def __init__(self, redis_client: redis.Redis, max_size: int = 10000):
        self.redis = redis_client
        self.max_size = max_size
        self.prefix = "backfill:"  # Namespace to avoid key collisions

    async def add_tick(self, symbol: str, tick: dict):
        key = f"{self.prefix}{symbol}"
        tick_json = json.dumps(tick)
        
        # Use a Redis pipeline to execute push and trim atomically
        async with self.redis.pipeline() as pipe:
            # 1. Append the new tick to the right of the list
            pipe.rpush(key, tick_json)
            
            # 2. Trim the list to only keep the latest `max_size` elements
            # Negative indexing means "keep from the Nth-to-last up to the last (-1)"
            pipe.ltrim(key, -self.max_size, -1)
            
            await pipe.execute()

    async def get_backfill(self, symbol: str) -> list[dict]:
        """
        Fetches the entire buffer instantly when a new client subscribes.
        """
        key = f"{self.prefix}{symbol}"
        
        # LRANGE 0 -1 fetches every element currently in the bounded list
        raw_ticks = await self.redis.lrange(key, 0, -1)
        
        # Deserialize JSON strings back into Python dictionaries
        return [json.loads(tick) for tick in raw_ticks]