"""Amaura Studio company operating system, governed by JARVIS."""

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import ApprovalStatus, RiskLevel, TaskState
from jarvis.amaura.semantic_adapters import install_semantic_adapters
from jarvis.amaura.semantic_core import install_semantic_core
from jarvis.amaura.semantic_path_normalization import install_semantic_path_normalization
from jarvis.amaura.semantic_release_contracts import install_semantic_release_contracts
from jarvis.amaura.semantic_write_compat import install_semantic_write_compat
from jarvis.amaura.supervisor import AmauraSupervisor
from jarvis.amaura.telemetry import OperationalTelemetry

# Phase 9 semantic execution boundary.
# Normalize semantic entities immediately after installing the core, then layer
# only public-grammar compatibility on top of the same typed request graph.
install_semantic_core()
install_semantic_path_normalization()
install_semantic_adapters()
install_semantic_write_compat()
install_semantic_release_contracts()

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
