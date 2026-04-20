"""Tile lifecycle monitoring — decay, ghost alerts, health checks, batch operations."""
import time
from dataclasses import dataclass, field
from collections import deque
from typing import Optional

@dataclass
class WatchEvent:
    event_type: str
    tile_id: str
    message: str
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)

@dataclass
class TileHealth:
    tile_id: str
    health: float = 1.0
    decay_rate: float = 0.99
    watched_at: float = field(default_factory=time.time)
    last_boost: float = 0.0
    boost_count: int = 0
    alert_sent: bool = False

class TileWatcher:
    def __init__(self, default_decay: float = 0.99, ghost_threshold: float = 0.05,
                 alert_threshold: float = 0.15):
        self.default_decay = default_decay
        self.ghost_threshold = ghost_threshold
        self.alert_threshold = alert_threshold
        self._tiles: dict[str, TileHealth] = {}
        self._events: deque = deque(maxlen=1000)
        self._alerts: list[WatchEvent] = []
        self._ghosted: list[WatchEvent] = []
        self._tick_count: int = 0

    def watch(self, tile_id: str, health: float = 1.0, decay_rate: float = 0.0):
        rate = decay_rate if decay_rate > 0 else self.default_decay
        self._tiles[tile_id] = TileHealth(tile_id=tile_id, health=health, decay_rate=rate)
        self._events.append(WatchEvent("watch", tile_id, f"Started watching (decay={rate})"))

    def watch_batch(self, tiles: list[dict]) -> int:
        count = 0
        for t in tiles:
            self.watch(t.get("id", ""), t.get("health", 1.0), t.get("decay_rate", 0.0))
            count += 1
        return count

    def unwatch(self, tile_id: str) -> bool:
        removed = self._tiles.pop(tile_id, None)
        if removed:
            self._events.append(WatchEvent("unwatch", tile_id, "Stopped watching"))
            return True
        return False

    def unwatch_batch(self, tile_ids: list[str]) -> int:
        return sum(1 for tid in tile_ids if self.unwatch(tid))

    def tick(self) -> list[WatchEvent]:
        events = []
        self._tick_count += 1
        to_ghost = []

        for tid, th in self._tiles.items():
            old_health = th.health
            th.health *= th.decay_rate

            # Alert threshold crossed
            if th.health < self.alert_threshold and not th.alert_sent and old_health >= self.alert_threshold:
                evt = WatchEvent("alert", tid,
                               f"Health dropped to {th.health:.4f} (threshold: {self.alert_threshold})",
                               data={"old_health": old_health, "new_health": th.health})
                self._events.append(evt)
                self._alerts.append(evt)
                th.alert_sent = True
                events.append(evt)

            # Ghost threshold crossed
            if th.health < self.ghost_threshold:
                evt = WatchEvent("ghost", tid,
                               f"Ghosted at {th.health:.5f} (after {self._tick_count} ticks)",
                               data={"final_health": th.health, "ticks": self._tick_count})
                self._events.append(evt)
                self._ghosted.append(evt)
                to_ghost.append(tid)
                events.append(evt)

        for tid in to_ghost:
            self._tiles.pop(tid, None)

        return events

    def boost(self, tile_id: str, amount: float = 0.3) -> bool:
        th = self._tiles.get(tile_id)
        if not th:
            return False
        th.health = min(1.0, th.health + amount)
        th.last_boost = time.time()
        th.boost_count += 1
        th.alert_sent = False  # Reset alert after boost
        self._events.append(WatchEvent("boost", tile_id,
                                      f"Boosted by {amount} to {th.health:.4f} (boost #{th.boost_count})",
                                      data={"amount": amount, "new_health": th.health}))
        return True

    def boost_batch(self, tile_ids: list[str], amount: float = 0.3) -> int:
        return sum(1 for tid in tile_ids if self.boost(tid, amount))

    def health_of(self, tile_id: str) -> float:
        return self._tiles[tile_id].health if tile_id in self._tiles else 0.0

    def health_report(self) -> list[dict]:
        report = []
        for tid, th in self._tiles.items():
            status = "healthy" if th.health >= self.alert_threshold else ("warning" if th.health >= self.ghost_threshold else "critical")
            report.append({"tile_id": tid, "health": round(th.health, 4),
                          "decay_rate": th.decay_rate, "status": status,
                          "boost_count": th.boost_count,
                          "age_s": round(time.time() - th.watched_at)})
        report.sort(key=lambda x: x["health"])
        return report

    def set_decay(self, tile_id: str, rate: float) -> bool:
        th = self._tiles.get(tile_id)
        if th:
            th.decay_rate = rate
            return True
        return False

    @property
    def active_tiles(self) -> int:
        return len(self._tiles)

    @property
    def recent_events(self, n: int = 10) -> list[WatchEvent]:
        return list(self._events)[-n:]

    @property
    def stats(self) -> dict:
        health_ranges = {"healthy": 0, "warning": 0, "critical": 0}
        for th in self._tiles.values():
            if th.health >= self.alert_threshold: health_ranges["healthy"] += 1
            elif th.health >= self.ghost_threshold: health_ranges["warning"] += 1
            else: health_ranges["critical"] += 1
        return {"watching": len(self._tiles), "events": len(self._events),
                "alerts": len(self._alerts), "ghosted": len(self._ghosted),
                "ticks": self._tick_count, "health_distribution": health_ranges}
