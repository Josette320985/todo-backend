"""Shared date-range rules for tasks.

The same rule is checked in two places: the request schema (before the
endpoint runs) and the service (against the values already stored, on a
partial update). Keeping it in one function guarantees both messages and
comparisons stay identical.
"""

from datetime import date
from typing import Final

DATE_RANGE_ERROR: Final[str] = (
    "La fecha de término no puede ser anterior a la fecha de inicio"
)


def date_range_error(start: date | None, end: date | None) -> str | None:
    """
    Return the validation message when ``end`` is before ``start``.

    Args:
        start (date | None): Start date, if any.
        end (date | None): End date, if any.

    Returns:
        str | None: The message to show, or None when the range is valid
        (or one of the dates is missing).
    """
    if start is not None and end is not None and end < start:
        return DATE_RANGE_ERROR
    return None
