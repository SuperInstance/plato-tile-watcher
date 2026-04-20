"""Tile watcher — monitors tile health with trend detection, alert rules, and sliding window analytics."""
import time
import math
from dataclasses import dataclass, field
from typing import Optional, Callable
from collections import defaultdict, deque
from enum import Enum

class HealthStatus(Enum):
    HEALTHY = "healthy"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"
    DEAD = "dead"

class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class TrendDirection(Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    CRASHING = "crashing"

@dataclass
class HealthRecord:
    tile_id: str
    health: float
    confidence: float
    timestamp: float = field(default_factory=time.time)
    room: str = ""

@dataclass
class AlertRule:
    name: str
    condition: str  # "health_below", "health_declining", "confidence_below", "ghost_imminent"
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    cooldown: float = 300.0  # seconds between alerts for same rule
    enabled: bool = True

@dataclass
class Alert:
    rule_name: str
    tile_id: str
    severity: AlertSeverity
    message: str
    value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)
    room: str = ""

@dataclass
class TileHealth:
    tile_id: str
    current_health: float
    current_confidence: float
    status: HealthStatus
    trend: TrendDirection
    trend_rate: float  # health change per hour
    history: deque = field(default_factory=lambda: deque(maxlen=100))
    last_alert: float = 0.0
    alerts_triggered: int = 0

class TileWatcher:
    def __init__(self, watch_interval: float = 60.0, history_window: float = 3600.0):
        self.watch_interval = watch_interval
        self.history_window = history_window
        self._health: dict[str, TileHealth] = {}
        self._rules: list[AlertRule] = []
        self._alerts: deque = deque(maxlen=500)
        self._handlers: list[Callable] = []

    def watch(self, tile_id: str) -> TileHealth:
        if tile_id not in self._health:
            self._health[tile_id] = TileHealth(tile_id=tile_id, current_health=1.0,
                                                current_confidence=1.0,
                                                status=HealthStatus.HEALTHY,
                                                trend=TrendDirection.STABLE)
        return self._health[tile_id]

    def update(self, tile_id: str, health: float, confidence: float, room: str = "") -> list[Alert]:
        th = self.watch(tile_id)
        th.current_health = health
        th.current_confidence = confidence
        th.history.append(HealthRecord(tile_id, health, confidence, room=room))
        th.status = self._classify(health)
        th.trend = self._detect_trend(th)
        th.trend_rate = self._trend_rate(th)
        alerts = self._check_rules(tile_id, th, room)
        for alert in alerts:
            self._alerts.append(alert)
            th.alerts_triggered += 1
            for handler in self._handlers:
                try: handler(alert)
                except: pass
        return alerts

    def add_rule(self, rule: AlertRule):
        self._rules.append(rule)

    def on_alert(self, handler: Callable):
        self._handlers.append(handler)

    def get_health(self, tile_id: str) -> Optional[TileHealth]:
        return self._health.get(tile_id)

    def by_status(self, status: HealthStatus) -> list[TileHealth]:
        return [th for th in self._health.values() if th.status == status]

    def by_room(self, room: str) -> list[TileHealth]:
        return [th for th in self._health.values()
                if th.history and th.history[-1].room == room]

    def critical_tiles(self) -> list[TileHealth]:
        return [th for th in self._health.values()
                if th.status in (HealthStatus.CRITICAL, HealthStatus.DEAD)]

    def alerts(self, severity: str = "", limit: int = 50) -> list[Alert]:
        alerts = list(self._alerts)
        if severity:
            alerts = [a for a in alerts if a.severity.value == severity]
        return alerts[-limit:]

    def dashboard(self) -> dict:
        statuses = defaultdict(int)
        trends = defaultdict(int)
        for th in self._health.values():
            statuses[th.status.value] += 1
            trends[th.trend.value] += 1
        return {"watched": len(self._health), "statuses": dict(statuses),
                "trends": dict(trends), "rules": len(self._rules),
                "recent_alerts": len(self._alerts),
                "critical": len(self.critical_tiles())}

    def _classify(self, health: float) -> HealthStatus:
        if health >= 0.7: return HealthStatus.HEALTHY
        if health >= 0.4: return HealthStatus.WATCH
        if health >= 0.2: return HealthStatus.WARNING
        if health >= 0.05: return HealthStatus.CRITICAL
        return HealthStatus.DEAD

    def _detect_trend(self, th: TileHealth) -> TrendDirection:
        history = list(th.history)
        if len(history) < 3:
            return TrendDirection.STABLE
        recent = history[-3:]
        diff = recent[-1].health - recent[0].health
        if diff > 0.1: return TrendDirection.IMPROVING
        if diff < -0.1: return TrendDirection.DECLINING
        if diff < -0.3: return TrendDirection.CRASHING
        return TrendDirection.STABLE

    def _trend_rate(self, th: TileHealth) -> float:
        history = list(th.history)
        if len(history) < 2:
            return 0.0
        duration = history[-1].timestamp - history[0].timestamp
        if duration <= 0:
            return 0.0
        health_change = history[-1].health - history[0].health
        return health_change / (duration / 3600)  # per hour

    def _check_rules(self, tile_id: str, th: TileHealth, room: str) -> list[Alert]:
        alerts = []
        now = time.time()
        for rule in self._rules:
            if not rule.enabled:
                continue
            if now - th.last_alert < rule.cooldown:
                continue
            triggered = False
            message = ""
            value = th.current_health
            if rule.condition == "health_below" and th.current_health < rule.threshold:
                triggered = True
                message = f"Health {th.current_health:.2f} below threshold {rule.threshold}"
            elif rule.condition == "confidence_below" and th.current_confidence < rule.threshold:
                triggered = True
                value = th.current_confidence
                message = f"Confidence {th.current_confidence:.2f} below threshold {rule.threshold}"
            elif rule.condition == "health_declining" and th.trend_rate < -rule.threshold:
                triggered = True
                value = th.trend_rate
                message = f"Health declining at {th.trend_rate:.3f}/hr"
            elif rule.condition == "ghost_imminent" and th.current_health < rule.threshold:
                triggered = True
                message = f"Ghost imminent: health {th.current_health:.2f}"
            if triggered:
                alerts.append(Alert(rule_name=rule.name, tile_id=tile_id,
                                   severity=rule.severity, message=message,
                                   value=value, threshold=rule.threshold, room=room))
                th.last_alert = now
        return alerts

    @property
    def stats(self) -> dict:
        return self.dashboard()
