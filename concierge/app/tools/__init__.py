"""Tool registry."""
from .check_availability import check_availability
from .draft_reservation import draft_reservation
from .get_hours import get_hours
from .registry import registry

# Register all built-in tools
registry.register(check_availability)
registry.register(draft_reservation)
registry.register(get_hours)

__all__ = ["registry"]