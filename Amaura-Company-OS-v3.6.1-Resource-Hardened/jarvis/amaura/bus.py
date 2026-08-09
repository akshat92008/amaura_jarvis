"""The Command Bus for the Amaura kernel. Enforces atomic execution of typed commands."""

from __future__ import annotations

from typing import Any

from jarvis.amaura.commands import Command
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError


class CommandBus:
    """Dispatches typed commands to domain handlers within atomic store transactions."""

    def __init__(self, control_plane: AmauraControlPlane):
        self.control_plane = control_plane

    def execute(self, command: Command) -> Any:
        """Execute a typed command atomically."""
        # Resolve the domain handler
        domain = command.domain
        handler_name = command.handler
        
        if domain == "control_plane":
            handler_obj = self.control_plane
        elif domain == "acquisition":
            handler_obj = self.control_plane.acquisition
        elif domain == "content_factory":
            handler_obj = self.control_plane.content_factory
        else:
            raise GovernanceError(f"Unknown command domain: {domain}")

        handler = getattr(handler_obj, handler_name, None)
        if not handler:
            raise GovernanceError(f"Handler {handler_name} not found on {domain}")

        # Extract arguments from the Pydantic command
        kwargs = command.model_dump(by_alias=True)

        try:
            # Wrap execution in an atomic block at the store level
            # This ensures any mid-flight failures or governance rejections roll back the entire state
            with self.control_plane.store.atomic_block():
                return handler(**kwargs)
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
