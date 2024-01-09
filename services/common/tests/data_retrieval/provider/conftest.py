"""Common fixtures for provider tests."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from rs_server_common.data_retrieval.provider import Product


@dataclass
class EodagConfiguration:
    """Eodag configuration - For test purpose only"""

    provider: str
    file: Path


def a_product(with_id: str) -> Product:
    """Create a dummy product for tests.

    The product has 2 metadata :
    * its id as given
    * its name as file_<id>

    :param with_id: id of the product
    :return: the product
    """
    return Product(
        with_id,
        {
            "id": with_id,
            "name": f"file_{with_id}",
        },
    )


@pytest.fixture(scope="package")
def eodag_config_folder(resource_path_root):
    return resource_path_root / "eodag"


@pytest.fixture(scope="package")
def cadip_config(eodag_config_folder) -> EodagConfiguration:
    return EodagConfiguration("CADIP", eodag_config_folder / "cadip.yaml")


@pytest.fixture(scope="package")
def not_found_config(eodag_config_folder) -> EodagConfiguration:
    return EodagConfiguration("WRONG", eodag_config_folder / "not_found.yml")
