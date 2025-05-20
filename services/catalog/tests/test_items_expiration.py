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

"""Tests to check if the correct retention time is set for various items uploaded in the catalog.
The tests follow the specs of this issue: https://pforge-exchange2.astrium.eads.net/jira/browse/RSPY-468
The test items are defined in the file resources/expiration_delays_test_data.json.
The test configuration used is in resources/s3/expiration_bucket.csv.
The items are not inserted one by one but all at once in a fixture to keep things simple.
"""

# pylint: disable=unused-argument

from datetime import datetime

DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def test_item_tc001_has_correct_exp_date(client, expiration_delays_test_data):
    """Test case 1 - Expected lifespan: 10 days"""
    test_owner = "copernicus"
    test_collection = "s1-l1"
    test_item = "TC-001"

    item = client.get(f"catalog/collections/{test_owner}:{test_collection}/items/{test_item}").json()

    published_date = datetime.strptime(item["properties"]["published"], DATE_FORMAT)
    expiration_date = datetime.strptime(item["properties"]["expires"], DATE_FORMAT)
    date_diff = expiration_date.date() - published_date.date()

    assert date_diff.days == 10


def test_item_tc002_has_correct_exp_date(client, expiration_delays_test_data):
    """Test case 2 - Expected lifespan: 30 days"""
    test_owner = "ANY"
    test_collection = "s1-l1"
    test_item = "TC-002"

    item = client.get(f"catalog/collections/{test_owner}:{test_collection}/items/{test_item}").json()

    published_date = datetime.strptime(item["properties"]["published"], DATE_FORMAT)
    expiration_date = datetime.strptime(item["properties"]["expires"], DATE_FORMAT)
    date_diff = expiration_date.date() - published_date.date()

    assert date_diff.days == 30


def test_item_tc003_has_correct_exp_date(client, expiration_delays_test_data):
    """Test case 2 - EOPF type: XXX - Expected lifespan: 40 days"""
    test_owner = "copernicus"
    test_collection = "s1-aux"
    test_item = "TC-003"

    item = client.get(f"catalog/collections/{test_owner}:{test_collection}/items/{test_item}").json()

    published_date = datetime.strptime(item["properties"]["published"], DATE_FORMAT)
    expiration_date = datetime.strptime(item["properties"]["expires"], DATE_FORMAT)
    date_diff = expiration_date.date() - published_date.date()

    assert date_diff.days == 40


def test_item_tc004_has_correct_exp_date(client, expiration_delays_test_data):
    """Test case 2 - EOPF type: orbsct - Expected lifespan: 30 days"""
    test_owner = "copernicus"
    test_collection = "s1-aux"
    test_item = "TC-004"

    item = client.get(f"catalog/collections/{test_owner}:{test_collection}/items/{test_item}").json()

    published_date = datetime.strptime(item["properties"]["published"], DATE_FORMAT)
    expiration_date = datetime.strptime(item["properties"]["expires"], DATE_FORMAT)
    date_diff = expiration_date.date() - published_date.date()

    assert date_diff.days == 7300
