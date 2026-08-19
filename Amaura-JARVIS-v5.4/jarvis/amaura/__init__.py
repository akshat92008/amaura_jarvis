"""Amaura Studio company operating system, governed by JARVIS."""

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import ApprovalStatus, RiskLevel, TaskState
from jarvis.amaura.review_diversity import install_review_diversity
from jarvis.amaura.semantic_core import install_semantic_core
from jarvis.amaura.semantic_frontend import install_semantic_frontend
from jarvis.amaura.telemetry import OperationalTelemetry
from jarvis.amaura.v7_mission_repairs import install_v7_mission_repairs
from jarvis.amaura.v7_semantic_precedence import (
    capture_canonical_semantic_parser,
    install_v7_semantic_precedence,
)
from jarvis.amaura.v7_semantic_repairs import install_v7_semantic_repairs


def _load_supervisor_class():
    # Reviewer diversity must be installed before supervisor.py binds its
    # default reviewer_factory at import time.
    from jarvis.amaura.supervisor import AmauraSupervisor as _AmauraSupervisor

    return _AmauraSupervisor


# Install the hosted-only reviewer diversity decorator before importing the
# supervisor, so every default reviewer factory sees the guarded class.
install_review_diversity()
AmauraSupervisor = _load_supervisor_class()

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
