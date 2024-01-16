"""This module is used to share common functions between apis endpoints"""
from datetime import datetime

from fastapi import status
from fastapi.responses import JSONResponse
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)


def is_valid_date_format(date: str) -> bool:
    """Check if a string adheres to the expected date format "YYYY-MM-DDTHH:MM:SS.sssZ".

    Parameters
    ----------
    date : str
        The string to be validated for the specified date format.

    Returns
    -------
    bool
        True if the input string adheres to the expected date format, otherwise False.

    Example
    -------
    >>> is_valid_date_format("2023-01-01T12:00:00.000Z")
    True

    >>> is_valid_date_format("2023-01-01 12:00:00")
    False
    """
    try:
        datetime.strptime(date, "%Y-%m-%dT%H:%M:%S.%fZ")
        return True
    except ValueError:
        return False


def validate_inputs_format(start_date, stop_date):
    """Docstring will be here."""
    if (not is_valid_date_format(start_date)) or (not is_valid_date_format(stop_date)):
        logger.error("Invalid start/stop in endpoint call!")
        return False, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="Invalid request, invalid start/stop format",
        )
    return True, None
