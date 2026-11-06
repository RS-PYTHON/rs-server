# Copyright 2023-2026 Airbus, CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Common fixtures for provider tests."""

import pathlib
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
def test_resources_folder() -> Path:
    """Folder containing all the test resources.

    :return: the path containing all the test resources.
    """
    # We don't use test resources here
    # because they want to launch the unit tests from another python project.
    return pathlib.Path(__file__).parent.parent.parent / "testresources"


@pytest.fixture(scope="package", name="eodag_config_folder")
def eodag_config_folder_fixture(test_resources_folder):  # pylint: disable=W0621
    """
    Pytest fixture to provide the path to the EODAG configuration folder.

    This fixture concatenates the given root path for resources with a specific
    'eodag' subdirectory, effectively pointing to where EODAG configuration
    files are expected to be located. It is scoped at the package level, ensuring
    that it is executed once per test session for a given test package.

    Args:
        test_resources_folder: pytest fixture providing the path to the test resources root directory.
    Returns:
        Path: The full path to the 'eodag' configuration directory within the test
              resources directory.

    Note:
        This fixture is intended to be used in pytest test functions or other fixtures
        that require access to the EODAG configuration files during testing.
    """

    return test_resources_folder / "eodag"


@pytest.fixture(scope="package")
def cadip_config(eodag_config_folder) -> EodagConfiguration:
    """
    Pytest fixture to provide an EodagConfiguration object for CADIP.

    This fixture creates and returns an EodagConfiguration instance specifically
    configured for CADIP, using a configuration file located within the provided
    EODAG configuration folder. It is scoped at the package level, ensuring that
    it is only executed once per test session for a given test package.

    Args:
        eodag_config_folder (Path): The path to the EODAG configuration folder,
                                    typically provided by the `eodag_config_folder` fixture.

    Returns:
        EodagConfiguration: An instance of EodagConfiguration configured for CADIP,
                            initialized with the path to the 'cadip.yaml' configuration file.
    """
    return EodagConfiguration("cadip", eodag_config_folder / "cadip.yaml")


@pytest.fixture
def not_found_config(tmp_path) -> EodagConfiguration:
    """Use an unknown provider and a missing config path to test initialization failure.

    EODAG may create a fallback config at this path, so keep it in the test's temporary directory.
    """
    return EodagConfiguration("WRONG", tmp_path / "not_found.yml")
