"""Tool registry."""
from .cancel_reservation import cancel_reservation
from .check_availability import check_availability
from .create_reservation import create_reservation
from .draft_cancel_reservation import draft_cancel_reservation
from .draft_modify_reservation import draft_modify_reservation
from .draft_reservation import draft_reservation
from .get_hours import get_hours
from .modify_reservation import modify_reservation
from .registry import registry
from .send_message import send_message

# Register all built-in tools
registry.register(check_availability)
registry.register(draft_reservation)
registry.register(draft_modify_reservation)
registry.register(draft_cancel_reservation)
registry.register(get_hours)
registry.register(create_reservation)
registry.register(modify_reservation)
registry.register(cancel_reservation)
registry.register(send_message)

__all__ = ["registry"]