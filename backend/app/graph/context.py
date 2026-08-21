"""Per-request execution context for graph invocations."""
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    """Keeps tenant identity, checkpoint identity, and event delivery together."""

    user_id: str
    trip_id: str
    request_id: str
    event_sink: Any | None = None

    @classmethod
    def create(cls, user_id: str, event_sink: Any | None = None) -> "RequestContext":
        return cls(
            user_id=user_id,
            trip_id=str(uuid4()),
            request_id=str(uuid4()),
            event_sink=event_sink,
        )

    @property
    def checkpoint_config(self) -> dict:
        return {
            "configurable": {
                "thread_id": self.trip_id,
                "checkpoint_ns": self.user_id,
                "event_sink": self.event_sink,
            }
        }


def event_sink_from_config(config: dict | None) -> Any | None:
    return (config or {}).get("configurable", {}).get("event_sink")
