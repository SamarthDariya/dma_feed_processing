from normalize import InternalTick

class Deduplicator:
    """
    Uses Redis to ensure idempotency across DMA and Snapshot feeds.
    """
    def __init__(self, redis_client):
        self.redis = redis_client
        self.ttl = 60  # Cache for 60 seconds

    async def is_duplicate(self, tick: InternalTick) -> bool:
        # Create a unique key for every event
        key = f"seen:{tick.symbol}:{tick.sequence_id}"
        
        # setnx (set if not exists) returns 1 if new, 0 if exists
        is_new = await self.redis.setnx(key, "1")
        if is_new:
            await self.redis.expire(key, self.ttl)
            return False
        return True