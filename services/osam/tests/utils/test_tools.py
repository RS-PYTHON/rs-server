# Copyright 2025 CS Group
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

"""Test file for tools functions."""

from osam.utils.tools import create_description_from_template, get_keycloak_user_from_description


def test_create_description_from_template():
    """Test for create_description_from_template"""

    test_template = "Test template user name: %keycloak-user%"
    test_user = "copernicus"

    test_description = create_description_from_template(test_user, test_template)

    assert test_description == "Test template user name: copernicus"


def test_get_keycloak_user_from_description():
    """Test for get_keycloak_user_from_description"""

    test_template = "Test template user name: %keycloak-user%"
    test_description = "Test template user name: copernicus"

    test_user = get_keycloak_user_from_description(test_description, test_template)

    assert test_user == "copernicus"
