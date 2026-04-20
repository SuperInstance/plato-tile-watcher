"""Tile lifecycle monitoring."""
import time
from dataclasses import dataclass, field
from collections import deque

@dataclass
class WatchEvent:
    event_type: str
    tile_id: str
    message: str
    timestamp: float = field(default_factory=time.time)

class TileWatcher:
    def __init__(self, decay_rate: float = 0.99, ghost_threshold: float = 0.05,
                 alert_threshold: float = 0.15, check_interval: float = 60.0):
        self.decay_rate = decay_rate
        self.ghost_threshold = ghost_threshold
        self.alert_threshold = alert_threshold
        self.check_interval = check_interval
        self._tiles: dict[str, float] = {}
        self._events: deque = deque(maxlen=500)
        self._alerts: list[WatchEvent] = []

    def watch(self, tile_id: str, health: float = 1.0): self._tiles[tile_id] = health
    def unwatch(self, tile_id: str): self._tiles.pop(tile_id, None)

    def tick(self) -> list[WatchEvent]:
        events = []
        to_ghost = []
        for tid, health in self._tiles.items():
            old = health
            new = health * self.decay_rate
            self._tiles[tid] = new
            if new < self.alert_threshold and old >= self.alert_threshold:
                evt = WatchEvent("alert", tid, f"Health {new:.3f} below threshold")
                self._events.append(evt); self._alerts.append(evt); events.append(evt)
            if new < self.ghost_threshold: to_ghost.append(tid)
        for tid in to_ghost:
            evt = WatchEvent("ghost", tid, f"Ghosted at {self._tiles[tid]:.4f}")
            self._events.append(evt); events.append(evt); self._tiles.pop(tid, None)
        return events

    def boost(self, tile_id: str, amount: float = 0.3):
        if tile_id in self._tiles:
            self._tiles[tile_id] = min(1.0, self._tiles[tile_id] + amount)
            self._events.append(WatchEvent("boost", tile_id, f"Boosted by {amount}"))

    @property
    def active_tiles(self) -> int: return len(self._tiles)
    @property
    def recent_events(self, n: int = 10) -> list[WatchEvent]: return list(self._events)[-n:]
    @property
    def stats(self) -> dict:
        return {"watching": len(self._tiles), "events": len(self._events),
                "alerts": len(self._alerts), "decay": self.decay_rate}
