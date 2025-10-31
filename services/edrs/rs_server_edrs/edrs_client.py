import yaml
from edrs_connector import EDRSConnector
import os
from pathlib import Path
import os.path as osp

DEFAULT_EDRS_STATIONS_CONFIG = ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "edrs_stations.yaml"
EDRS_STATIONS_CONFIG = os.environ.get("EDRS_STATIONS_CONFIG_YAML", DEFAULT_EDRS_STATIONS_CONFIG)

def load_station_config(config_path: str, station_name: str) -> dict:
    """Load connection parameters for a specific station from YAML config."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Handle case where stations are provided as a YAML string under one key
    stations_data = config.get("stations")
    if isinstance(stations_data, str):
        stations = yaml.safe_load(stations_data)
    else:
        stations = stations_data

    if not stations or station_name not in stations:
        raise ValueError(f"Station '{station_name}' not found in configuration file: {config_path}")

    station = stations[station_name]
    auth = station.get("authentication", {})
    service = station.get("service", {})
    # Map configuration to EDRSConnector expected args
    connection_params = {
        "host": service.get("url"),
        "port": service.get("port"),
        "login": auth.get("username"),
        "password": auth.get("password"),
        "ca_cert": auth.get("ca_crt"),
        "client_cert": auth.get("client_crt"),
        "client_key": auth.get("client_key"),
    }

    # Validate required fields
    missing = [k for k, v in connection_params.items() if v is None]
    if missing:
        raise ValueError(f"Missing required fields in config for '{station_name}': {', '.join(missing)}")
    return connection_params

if __name__ == "__main__":
    STATION_NAME = "bedc"
    client = EDRSConnector(**load_station_config(EDRS_STATIONS_CONFIG, STATION_NAME))

    client.connect()
    print("\n=== LIST version ===")
    print(client.list_satellite_files_list("S1A"))

    print("\n=== MLSD version ===")
    print(client.list_satellite_files_mlsd("S1A"))

    client.close()
