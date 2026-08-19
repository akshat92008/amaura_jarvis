"""Amaura Studio company operating system, governed by JARVIS."""

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import ApprovalStatus, RiskLevel, TaskState
from jarvis.amaura.semantic_core import install_semantic_core
from jarvis.amaura.semantic_frontend import install_semantic_frontend
from jarvis.amaura.supervisor import AmauraSupervisor
from jarvis.amaura.telemetry import OperationalTelemetry
from jarvis.amaura.v7_mission_repairs import install_v7_mission_repairs
from jarvis.amaura.v7_semantic_precedence import (
    capture_canonical_semantic_parser,
    install_v7_semantic_precedence,
)
from jarvis.amaura.v7_semantic_repairs import install_v7_semantic_repairs

# ARCH semantic execution boundary.
# There is exactly one active language front-end above the typed request graph.
# v7 qualification repairs may decorate planner/workflow/helper boundaries, but
# the canonical semantic front-end keeps parser precedence.  We capture it
# immediately after installation, then restore it with only narrow proven
# fallbacks after the v7 repair decorators have installed.
install_semantic_core()
install_semantic_frontend()
capture_canonical_semantic_parser()
install_v7_semantic_repairs()
install_v7_semantic_precedence()
install_v7_mission_repairs()

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
