"""Tool registry."""

from .get_hours import get_hours
from .registry import registry

# Register all built-in tools
registry.register(get_hours)

__all__ = ["registry"]