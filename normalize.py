from pydantic import BaseModel
from enum import Enum
from datetime import datetime

class FeedStatus(Enum):
    LIVE = "LIVE"
    STALE = "STALE"

class InternalTick(BaseModel):
    instrument_token: int
    symbol: str
    price: float
    volume: int
    sequence_id: int
    exchange_ts: datetime
    status: FeedStatus = FeedStatus.LIVE

def normalize_event(raw_packet, feed_type):
    """
    Mandatory: Converts raw binary/JSON into a standard InternalTick.
    """
    # Logic to map raw_packet fields to InternalTick
    # Example for a binary DMA feed
    return InternalTick(
        instrument_token=raw_packet['t'],
        symbol=raw_packet['s'],
        price=raw_packet['lp'],
        volume=raw_packet['v'],
        sequence_id=raw_packet['seq'],
        exchange_ts=datetime.fromtimestamp(raw_packet['ts']),
        status=FeedStatus.LIVE
    )