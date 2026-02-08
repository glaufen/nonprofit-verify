"""State charity registration checks.

Re-exports check_all_states from the state_scrapers package.
"""

from app.services.state_scrapers import check_all_states

__all__ = ["check_all_states"]
