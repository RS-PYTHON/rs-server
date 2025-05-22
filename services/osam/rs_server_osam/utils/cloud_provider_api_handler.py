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

import os

import ovh


class OVHApiHandler:

    def __init__(self):
        self.ovh_client = self.__open_ovh_connection()
        # Get ovh name dinamically
        self.ovh_service_name = self.ovh_client.get("/cloud/project")[0]

    def __open_ovh_connection(self) -> ovh.Client:

        ovh_endpoint = os.environ["OVH_ENDPOINT"]
        ovh_application_key = os.environ["OVH_APPLICATION_KEY"]
        ovh_application_secret = os.environ["OVH_APPLICATION_SECRET"]
        ovh_consumer_key = os.environ["OVH_CONSUMER_KEY"]

        try:
            ovh_client = ovh.Client(
                endpoint=ovh_endpoint,
                application_key=ovh_application_key,
                application_secret=ovh_application_secret,
                consumer_key=ovh_consumer_key,
            )
        except ovh.APIError as error:
            raise RuntimeError(f"Error connecting with OVH to '{ovh_endpoint}'.") from error

        return ovh_client

    def get_all_users(self) -> dict:
        # TODO ça retourne quoi ce truc ?
        return self.ovh_client.get(f"/cloud/project/{self.ovh_service_name}/user")

    def create_user(self, description: str | None = None, role=None, roles=None) -> dict:
        return self.ovh_client.post(
            f"/cloud/project/{self.ovh_service_name}/user",
            description=description,
            role=role,
            roles=roles,
        )

    def delete_user(self, user_id=str):
        return self.ovh_client.delete(f"/cloud/project/{self.ovh_service_name}/user/{user_id}")
