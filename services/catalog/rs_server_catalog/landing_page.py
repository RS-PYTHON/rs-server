# Copyright 2023-2025 Airbus, CS Group
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

"""Contains all functions for the landing page."""


from rs_server_catalog.user_handler import CATALOG_PREFIX


def add_prefix_link_landing_page(content: dict, url: str):
    """add the CATALOG_PREFIX if it is not present

    Args:
        content (dict): the landing page
        url (str): the url
    """
    for link in content["links"]:
        if "href" in link and CATALOG_PREFIX not in link["href"]:
            href = link["href"]
            url_size = len(url)
            link["href"] = href[:url_size] + CATALOG_PREFIX + href[url_size:]
    return content
