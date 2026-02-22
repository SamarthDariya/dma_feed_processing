from normalize import FeedStatus, InternalTick


class SequenceTracker:
    """
    Tracks sequence IDs per symbol to detect missing packets.
    """
    def __init__(self):
        self.last_seen_seq = {}

    def process_and_flag(self, tick: InternalTick) -> InternalTick:
        prev_seq = self.last_seen_seq.get(tick.symbol)
        
        if prev_seq is not None:
            # If current seq is not the immediate next number, we have a gap
            if tick.sequence_id != prev_seq + 1:
                tick.status = FeedStatus.STALE 
                # Log gap for recovery service
            self.last_seen_seq[tick.symbol] = max(tick.sequence_id,prev_seq)
        else:
            self.last_seen_seq[tick.symbol] = tick.sequence_id
        return tick