"""Amaura Studio company operating system, governed by JARVIS."""

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import ApprovalStatus, RiskLevel, TaskState
from jarvis.amaura.semantic_core import install_semantic_core
from jarvis.amaura.semantic_frontend import install_semantic_frontend
from jarvis.amaura.semantic_phase9 import install_semantic_phase9
from jarvis.amaura.supervisor import AmauraSupervisor
from jarvis.amaura.telemetry import OperationalTelemetry

# ARCH semantic execution boundary.
# There is exactly one active language front-end above the typed request graph.
# Phase 9 hardening extends that boundary with span/role/postcondition contracts;
# historical compatibility modules remain inert and do not form a parser stack.
install_semantic_core()
install_semantic_frontend()
install_semantic_phase9()

__all__ = [
    "AmauraControlPlane",
    "AmauraSupervisor",
    "ApprovalStatus",
    "EvidenceVault",
    "OperationalTelemetry",
    "ProviderReceipt",
    "RiskLevel",
    "TaskState",
]
