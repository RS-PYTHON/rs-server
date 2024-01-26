"""Docstring will be added here"""
import json
import os
import os.path as osp
from pathlib import Path

DEFAULT_STATION_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config" / "stations_cfg.json"


def station_to_server_url(station: str) -> str | None:
    """Retrieve the configuration data (webserver address) for a CADU station based on its identifier.

    Parameters
    ----------
    station : str
        Identifier for the CADU station.

    Returns
    -------
    str or None
        A str containing the webserver address for the specified station,
        or None if the station identifier is not found.

    Example
    -------
    >>> station_to_server_url("station123")
    'https://station123.example.com'

    Notes
    -----
    - The station identifier is case-insensitive and is converted to uppercase for matching.
    - The function reads the station configuration data from a JSON file.
    - If the station identifier is not found in the configuration data, the function returns None.
    """

    # Check if the config file path is overriden in the environment variables
    station_config = os.environ.get("RSPY_STATION_CONFIG", DEFAULT_STATION_CONFIG)

    try:
        with open(station_config, encoding="utf-8") as jfile:
            stations_data = json.load(jfile)
            return stations_data.get(station.upper(), None)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        # logger to be added.
        raise ValueError from exc
