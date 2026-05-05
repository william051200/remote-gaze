"""Data models for recorded events and recordings."""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class RecordedEvent:
    step: int
    type: str  # "mouse_click" | "type_text" | "key_press" | "hotkey"
    timestamp: float  # seconds since recording start
    delay_from_previous: float
    screenshot: str  # hash key referencing Recording.screenshots
    x: Optional[int] = None
    y: Optional[int] = None
    button: Optional[str] = None  # "left", "right", "middle"
    key: Optional[str] = None
    text: Optional[str] = None  # for "type_text" events: the buffered text run
    # Modifier keys held when the event fired. Used by:
    #   - "hotkey":      modifiers + key form the chord (e.g. ctrl + s)
    #   - "mouse_click": modifiers held during the click (e.g. shift+click)
    # Canonical names: ctrl, alt, shift, win.
    modifiers: Optional[list] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "RecordedEvent":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Recording:
    name: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    events: list = field(default_factory=list)
    screenshots: dict = field(default_factory=dict)  # hash → base64 PNG
    # Optional metadata describing the monitor that was recorded. Lets the
    # player (eventually) re-target a different display, and lets us warn
    # if the geometry has changed since recording. Backward-compatible:
    # older recordings without this field load with monitor=None.
    monitor: Optional[dict] = None
    # Model B (laptop drives a remote-app session window) metadata. When
    # window_relative is True, every mouse_click event's (x, y) is
    # relative to the session window's top-left at PLAYBACK time, not an
    # absolute screen coordinate. Older recordings load with these unset
    # and replay with the legacy absolute behavior.
    window_relative: bool = False
    window_title_contains: Optional[str] = None
    window_size_at_record: Optional[list] = None  # [width, height]

    def to_json(self) -> str:
        payload = {
            "name": self.name,
            "created_at": self.created_at,
            "screenshots": self.screenshots,
            "events": [e.to_dict() for e in self.events],
        }
        if self.monitor is not None:
            payload["monitor"] = self.monitor
        if self.window_relative:
            payload["window_relative"] = True
            if self.window_title_contains is not None:
                payload["window_title_contains"] = self.window_title_contains
            if self.window_size_at_record is not None:
                payload["window_size_at_record"] = self.window_size_at_record
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "Recording":
        data = json.loads(json_str)
        events = [RecordedEvent.from_dict(e) for e in data.get("events", [])]
        return cls(
            name=data["name"],
            created_at=data["created_at"],
            events=events,
            screenshots=data.get("screenshots", {}),
            monitor=data.get("monitor"),
            window_relative=data.get("window_relative", False),
            window_title_contains=data.get("window_title_contains"),
            window_size_at_record=data.get("window_size_at_record"),
        )
