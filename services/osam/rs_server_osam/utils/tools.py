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

"""Various and diverse tools functions"""

DEFAULT_DESCRIPTION_TEMPLATE = "## linked to keycloak user %keycloak-user%"


def create_description_from_template(keycloak_user: str, template: str=DEFAULT_DESCRIPTION_TEMPLATE) -> str:
    """Applies the given Keycloak user name in the description, using the given template.
    The template must have a '%keycloak-user%' placeholder.
    
    Args:
        keycloak_user (str): Keycloak user to set in the description.
        template (str, optionnal): Template to use. Default is '## linked to keycloak user %keycloak-user%'.

    Returns:
        str: Description with correct user name.
    """
    user_placeholder = "%keycloak-user%"
    return template.replace(user_placeholder, keycloak_user)


def get_keycloak_user_from_description(description: str, template: str=DEFAULT_DESCRIPTION_TEMPLATE) -> str:
    """Returns the Keycloak user name included in the given description using its template.
    The template must have a '%keycloak-user%' placeholder.

    Args:
        description (str): Description containing a Keycloak user name.
        template (str, optionnal): Template to use. Default is '## linked to keycloak user %keycloak-user%'.

    Returns:
        str: Keycloak user name.    
    """
    user_placeholder = "%keycloak-user%"
    template = template.replace(user_placeholder, '')
    return description.replace(template, '')
