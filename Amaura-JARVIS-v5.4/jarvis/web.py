"""Compatibility entry point for the authenticated JARVIS server.

Historically this module created a second unauthenticated FastAPI application.
It now exports the single governed server so every launch path shares the same
network policy, authentication, lifecycle cleanup and API contracts.
"""

from jarvis.server import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
