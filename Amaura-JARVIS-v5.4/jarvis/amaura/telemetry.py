"""Durable metrics, traces, alerts, and Prometheus rendering."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from jarvis.amaura.store import CompanyStore

_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


def _labels_key(labels: dict[str, str]) -> str:
    return ",".join(f"{key}={labels[key]}" for key in sorted(labels))


@dataclass(slots=True)
class TraceContext:
    trace_id: str
    operation: str
    started: float
    attributes: dict[str, Any]


class OperationalTelemetry:
    def __init__(self, store: CompanyStore):
        self.store = store

    def increment(
        self,
        name: str,
        *,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not _METRIC_NAME.fullmatch(name):
            raise ValueError(f"Invalid metric name: {name}")
        return self.store.record_metric(
            name=name,
            labels=labels or {},
            value=float(value),
        )

    def alert(
        self,
        *,
        severity: str,
        code: str,
        message: str,
        resource_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.create_alert(
            {
                "id": f"alert_{uuid.uuid4().hex[:16]}",
                "severity": severity,
                "code": code,
                "message": message,
                "resource_id": resource_id,
                "details": details or {},
            }
        )

    @contextmanager
    def trace(
        self,
        operation: str,
        **attributes: Any,
    ) -> Iterator[TraceContext]:
        context = TraceContext(
            trace_id=f"trace_{uuid.uuid4().hex[:16]}",
            operation=operation,
            started=time.perf_counter(),
            attributes=attributes,
        )
        outcome = "ok"
        error = ""
        try:
            yield context
        except Exception as exc:
            outcome = "error"
            error = type(exc).__name__
            raise
        finally:
            duration_ms = (time.perf_counter() - context.started) * 1000
            self.store.record_trace(
                {
                    "id": context.trace_id,
                    "operation": operation,
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "attributes": attributes,
                    "error": error,
                }
            )
            self.increment(
                "amaura_operation_total",
                labels={"operation": operation, "outcome": outcome},
            )
            self.increment(
                "amaura_operation_duration_ms_total",
                value=duration_ms,
                labels={"operation": operation},
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "metrics": self.store.list_metrics(),
            "alerts": self.store.list_alerts(status="open"),
            "recent_traces": self.store.list_traces(limit=100),
        }

    def prometheus(self) -> str:
        lines = [
            "# HELP amaura_build_info Amaura internal workforce build information.",
            "# TYPE amaura_build_info gauge",
            'amaura_build_info{version="1.2.0"} 1',
        ]
        for metric in self.store.list_metrics():
            name = metric["name"]
            labels = metric["labels"]
            rendered_labels = ""
            if labels:
                pairs = ",".join(
                    f'{key}="{str(value).replace(chr(34), chr(92) + chr(34))}"'
                    for key, value in sorted(labels.items())
                )
                rendered_labels = "{" + pairs + "}"
            lines.append(f"{name}{rendered_labels} {metric['value']}")
        open_alerts = self.store.list_alerts(status="open", limit=5000)
        lines.extend(
            [
                "# HELP amaura_open_alerts Current durable operational alerts.",
                "# TYPE amaura_open_alerts gauge",
                f"amaura_open_alerts {len(open_alerts)}",
            ]
        )
        return "\n".join(lines) + "\n"


__all__ = ["OperationalTelemetry", "TraceContext"]
