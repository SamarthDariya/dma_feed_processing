"""
================================================================================
DESIGN DECISIONS & ENGINEERING TRADE-OFFS: REPLAY ENGINE
================================================================================
This module satisfies the requirements to replay any historical day, 
preserve chronological ordering, and perform multi-symbol replay 
using a heap.

Given the scale of 10M+ ticks/day, the following engineering 
trade-offs were made to balance memory, CPU, and Network I/O:

1. Database Pagination (Keyset vs. OFFSET):
   - Anti-Pattern avoided: Using `LIMIT X OFFSET Y` forces the database to scan 
     and discard Y rows before returning the result, leading to an O(N^2) 
     time complexity degradation as the replay moves deeper into the day.
   - Chosen approach: "Keyset Pagination" (exchange_ts > last_seen_ts). By 
     combining this with a composite index on (instrument_token, exchange_ts), 
     the database performs an O(1) index lookup to fetch the next batch instantly.

2. Network Latency (Chunking vs. Single Fetch):
   - Fetching ticks one-by-one would result in millions of network round-trips 
     to the database, creating massive I/O bottlenecks.
   - Fetching the entire day into memory would cause the Python worker to crash 
     due to Out-Of-Memory (OOM) errors.
   - Chosen approach: Chunking. We fetch batches of 5000 ticks per symbol. This 
     keeps the memory footprint flat and predictable while drastically reducing 
     TCP overhead.
     NOTE: 5000 is an arbitary number can be chosen based on performance needs

3. State Management (Async Generators vs. In-Memory Deques):
   - Manually managing buffer arrays requires complex tracking of offsets and 
     frequent DB checks inside the main event loop.
   - Chosen approach: Async Generators (yield). Generators lazily evaluate 
     and encapsulate their own state (last_seen_ts). The main heap consumer 
     simply calls anext() without knowing the underlying fetch logic.

4. Chronological Ordering (Min-Heap k-way Merge):
   - To replay multiple symbols simultaneously, we must guarantee global 
     chronological ordering. 
   - Chosen approach: A Min-Heap. By pushing the tuple (timestamp, symbol, tick) 
     into heapq, the root of the heap is mathematically guaranteed to always 
     yield the globally earliest tick.
================================================================================
"""

import asyncio
import heapq
import time
from typing import List

class ReplayEngine:
    def __init__(self, db_pool, kafka_producer):
        self.db = db_pool
        self.producer = kafka_producer
        self.chunk_size = 5000
        self.raw_topic = "raw_ticks"

    async def tick_generator(self, symbol: str, target_date: str):
        """
        Async generator that yields one tick at a time, 
        fetching from the DB in batches of 5000 using Keyset Pagination.
        """
        last_seen_ts = None
        
        while True:
            # 1. Fetch a chunk using keyset pagination on indexed timestamp
            query = f"SELECT * FROM ticks WHERE instrument_token='{symbol}' AND DATE(exchange_ts)='{target_date}'"
            if last_seen_ts:
                query += f" AND exchange_ts > '{last_seen_ts}'"
            query += f" ORDER BY exchange_ts ASC LIMIT {self.chunk_size}"
            
            chunk = await self.db.fetch_rows(query)
            
            # 2. Stop when no more data is found for the symbol on that day
            if not chunk:
                break
                
            # 3. Yield ticks one by one to the consumer
            for tick in chunk:
                last_seen_ts = tick['exchange_ts']
                yield tick 

    async def start_replay(self, symbols: List[str], target_date: str, speed: float = 1.0):
        """
        Main replay loop. Manages the Min-Heap and variable speed control.
        :param symbols: List of symbol strings to replay.
        :param target_date: String date (YYYY-MM-DD).
        :param speed: Multiplier (1.0 = Real-time, 10.0 = 10x, float('inf') = Burst).
        """
        min_heap = []
        
        # Initialize generators for each symbol
        generators = {sym: self.tick_generator(sym, target_date) for sym in symbols}

        # 1. Initialize the heap with the first tick from each symbol's generator
        for sym, gen in generators.items():
            try:
                first_tick = await anext(gen)  
                # Heap stores: (timestamp, symbol_name, tick_data)
                heapq.heappush(min_heap, (first_tick['exchange_ts'], sym, first_tick))
            except StopAsyncIteration:
                pass # Symbol had no activity for the given date

        last_market_time = None
        last_system_time = None

        # 2. Global Chronological Replay Loop
        while min_heap:
            ts, sym, tick = heapq.heappop(min_heap)
            
            # --- Speed Control Logic ---
            if speed != float('inf'):  
                if last_market_time is not None:
                    # Calculate original time gap in market data
                    market_delta = (ts - last_market_time).total_seconds()
                    
                    # Calculate scaled delay based on requested speed
                    target_wait = market_delta / speed
                    
                    # Subtract processing overhead already consumed by the system
                    time_since_last_tick = time.time() - last_system_time
                    
                    sleep_duration = target_wait - time_since_last_tick
                    if sleep_duration > 0:
                        await asyncio.sleep(sleep_duration)

            # Update timing trackers BEFORE publishing to maintain relative accuracy
            last_market_time = ts
            last_system_time = time.time()

            # 3. Inject back into Kafka (replays hit the same path as live DMA)
            await self.producer.send(self.raw_topic, tick)

            # 4. Refill the heap with the next tick from the popped symbol's generator
            try:
                next_tick = await anext(generators[sym])
                heapq.heappush(min_heap, (next_tick['exchange_ts'], sym, next_tick))
            except StopAsyncIteration:
                # Generator exhausted for this symbol; it is removed from the heap
                pass

        print(f"Successfully completed replay for {len(symbols)} symbols for date {target_date}.")