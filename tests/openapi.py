"""Utility module for openapi specification manipulation."""

import argparse
import json
from pathlib import Path

from fastapi.openapi.utils import get_openapi

from tests.app import init_app

app = init_app()


def extract_openapi_specification(to_folder: Path) -> None:
    """Extract the openapi specification to the given folder.

    Retrieve the openapi specification from the FastAPI instance in json format
    and write it in the given folder in a file named openapi.json.

    :param to_folder: the folder where the specification is written
    :return: None
    """
    with open(to_folder / "openapi.json", "w", encoding="utf-8") as f:
        json.dump(
            get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                description=app.description,
                routes=app.routes,
            ),
            f,
        )


def _parse_output_folder() -> Path:
    """Parse the input parameters to retrieve the output folder.

    We are expected only one mandatory parameter : the ouput folder.

    :return: the ouput folder parsed.
    """
    parser = argparse.ArgumentParser(
        prog="get_openapi",
        description="Export the openapi spec to the given folder",
    )
    parser.add_argument("output")
    args = parser.parse_args()
    return Path(args.output)


if __name__ == "__main__":
    output_folder = _parse_output_folder()
    extract_openapi_specification(output_folder)
