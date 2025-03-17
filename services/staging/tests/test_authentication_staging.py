# Copyright 2024 CS Group
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

"""Test staging endpoint authentication."""

import pytest
from starlette.status import HTTP_401_UNAUTHORIZED

@pytest.mark.unit
def test_processes(staging_client_auth):
    # The current staging_client_auth contains all the roles needed to handle staging resource.
    resource = "staging"
    assert staging_client_auth.get(f"/processes/{resource}").status_code != HTTP_401_UNAUTHORIZED
    
    # When setting resource to other value, check that UAC does not allow since roles are not updated.
    resource = "other_staging"
    unauthorized_resource_response = staging_client_auth.get(f"/processes/{resource}")
    assert unauthorized_resource_response.status_code == HTTP_401_UNAUTHORIZED
    assert unauthorized_resource_response.json() == {'message': 'Missing RS_PROCESSES_OTHER_STAGING_READ authorization role'}