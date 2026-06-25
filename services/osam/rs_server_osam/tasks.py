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

"""Main tasks executed by OSAM service."""

import copy
import json
import logging
import os

# pylint: disable = wrong-import-order
from collections.abc import Sequence
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from cachetools import TTLCache, cached
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import run_in_threads
from rs_server_osam.utils.cloud_provider_api_handler import OVHApiHandler
from rs_server_osam.utils.keycloak_handler import KeycloakHandler
from rs_server_osam.utils.tools import (
    DESCRIPTION_TEMPLATE,
    LIST_CHECK_OVH_DESCRIPTION,
    create_description_from_template,
    get_keycloak_user_from_description,
    load_configmap_data,
    match_roles,
    parse_role,
)

# Cache size (number of cached Keycloak usernames) for the /storage/account/credentials endpoint
OSAM_CREDENTIALS_CACHE_SIZE = int(os.environ.get("OSAM_CREDENTIALS_CACHE_SIZE", 1024))

# Cache TTL (time to live) in seconds for the /storage/account/credentials endpoint
OSAM_CREDENTIALS_CACHE_TTL = int(os.environ.get("OSAM_CREDENTIALS_CACHE_TTL", 7200))  # 2 hours

# Maximum number of parallel calls to the keycloak and obs apis
MAX_THREAD_COUNT = 5

OVH_ROLE_FOR_NEW_USERS = "objectstore_operator"
STRKEY_ACCESS_RIGHT_READ_LIST = "read"
STRKEY_ACCESS_RIGHT_READ_DWN_LIST = "read_download"
STRKEY_ACCESS_RIGHT_WRITE_DWN_LIST = "write_download"

# Templates for s3 access rights final lists
S3_ACCESS_RIGHTS_TEMPLATE = {"Version": "%date%", "Statement": list[dict[str, Sequence[str]]]}
WILDCARD_CHAR = "*"

BLOCK_LIST_BUCKETS = {
    "Sid": "ListBucketSentinel",
    "Effect": "Allow",
    "Action": ["s3:ListBucket"],
    "Resource": "arn:aws:s3:::%bucketholder%",
    "Condition": {"StringLike": {"s3:prefix": list[str]}},
}

BLOCK_LIST_READ_TEMPLATE = {
    "Effect": "Allow",
    "Action": ["s3:ListMultipartUploadParts"],
    "Resource": "arn:aws:s3:::%placeholder%*",
}

BLOCK_LIST_READ_DOWNLOAD_TEMPLATE = {
    "Effect": "Allow",
    "Action": [
        "s3:GetObject",
        "s3:ListMultipartUploadParts",
    ],
    "Resource": "arn:aws:s3:::%placeholder%*",
}

BLOCK_LIST_WRITE_DOWNLOAD_TEMPLATE = {
    "Effect": "Allow",
    "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListMultipartUploadParts",
        "s3:AbortMultipartUpload",
    ],
    "Resource": "arn:aws:s3:::%placeholder%*",
}

BLOCK_BUCKET_LEVEL_ACTIONS_TEMPLATE = {
    "Sid": "BucketLevelActions",
    "Effect": "Allow",
    "Action": ["s3:GetBucketLocation", "s3:ListBucketMultipartUploads"],
    "Resource": "arn:aws:s3:::%placeholder%",
}

logger = Logging.default(__name__)
logger.setLevel(logging.DEBUG)


# Get keycloak/ovh handler (it doesn't creates duplicates)
def get_keycloak_handler():
    """Used to get a copy of Keycloak handler"""
    return KeycloakHandler()


def get_ovh_handler():
    """Used to get a copy of Ovh handler"""
    return OVHApiHandler()


# Decorator to trace functions
def traced_function(name=None):
    """
    Decorator to trace the execution of a function using OpenTelemetry spans.

    Args:
        name (str, optional): Custom name for the span. Defaults to the function's name.

    Returns:
        Callable: A wrapped function with tracing enabled.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            span_name = name or func.__name__
            with init_opentelemetry.start_span(__name__, span_name) as span:
                span.set_attribute("function.name", func.__name__)
                return func(*args, **kwargs)

        return wrapper

    return decorator


def build_users_data_map() -> dict[str, Any]:
    """
    Builds a dictionary mapping usernames to their associated user data.

    For each user retrieved from Keycloak, this function gathers:
      - Custom attributes from Keycloak
      - Assigned Keycloak roles

    Returns:
        dict: A dictionary where each key is a username and the value is another
              dictionary containing:
                - "keycloak_attribute": Custom user attribute from Keycloak
                - "keycloak_roles": List of roles assigned to the user
    """

    def build_user(kc_user: dict) -> tuple[str, dict]:
        """Process one user in a multithreaded context"""
        return (
            kc_user["username"],
            {
                "keycloak_attribute": get_keycloak_handler().get_obs_user_from_keycloak_user(kc_user),
                "keycloak_roles": [
                    role["name"] for role in get_keycloak_handler().get_keycloak_user_roles(kc_user["id"])
                ],
            },
        )

    kc_users = [(kc_user,) for kc_user in get_keycloak_handler().get_keycloak_users()]
    users_info = run_in_threads(build_user, kc_users, MAX_THREAD_COUNT, raise_exceptions=True)
    return dict(users_info)


@traced_function()
def link_rspython_users_and_obs_users():
    """
    Coordinates linking between Keycloak users and OVH object storage (OBS) users.

    - Retrieves Keycloak and OBS users.
    - Optionally links or removes users based on whether mappings exist.

    Note:
        The linking/unlinking logic is currently commented out and should be implemented
        based on specific integration rules.
    """
    logger.info("Checking the link between keycloak users and ovh accounts. Creating ovh accounts if missing")

    # Get all OVH users and their IDs for quick lookup
    obs_users = get_ovh_handler().get_all_users()
    obs_user_ids = {str(obs_user["id"]) for obs_user in obs_users}

    def create_user(kc_user):
        """Create one user in a multithreaded context"""
        # For each Keycloak user, check if there's an associated OBS user
        obs_user_id = get_keycloak_handler().get_obs_user_from_keycloak_user(kc_user)
        obs_user_id = obs_user_id[0] if isinstance(obs_user_id, list) and obs_user_id else obs_user_id
        # If no associated OBS user or if the associated OBS user ID is not in OVH, create a new OBS user account
        if not obs_user_id or obs_user_id not in obs_user_ids:
            logger.info(f"Creating a new ovh account linked to keycloak user '{kc_user}'")
            create_obs_user_account_for_keycloak_user(kc_user)

    kc_users = [(kc_user,) for kc_user in get_keycloak_handler().get_keycloak_users()]
    run_in_threads(create_user, kc_users, MAX_THREAD_COUNT, raise_exceptions=True)

    # Refresh state after potential creations
    # After we create OBS account and update keycloak attributes, we need to refresh the keycloak_users and
    # obs_users lists to have the updated data for the deletion step
    kc_users = get_keycloak_handler().get_keycloak_users()
    obs_users = [(obs_user,) for obs_user in get_ovh_handler().get_all_users()]

    # If the cloud provider user is not linked with a keycloak account, remove it.
    def delete_user(obs_user: dict):
        """Delete one user in a multithreaded context"""
        delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, kc_users)

    run_in_threads(delete_user, obs_users, MAX_THREAD_COUNT, raise_exceptions=True)


@traced_function()
def create_obs_user_account_for_keycloak_user(
    keycloak_user: dict,
):
    """
    Creates an OBS user and links it to a Keycloak user.

    Args:
        keycloak_user (dict): A dictionary representing the Keycloak user.

    Returns:
        None
    """
    new_user_description = create_description_from_template(keycloak_user["username"], template=DESCRIPTION_TEMPLATE)
    new_user = get_ovh_handler().create_user(description=new_user_description, role=OVH_ROLE_FOR_NEW_USERS)
    get_keycloak_handler().set_obs_user_in_keycloak_user(keycloak_user, new_user["id"])


@traced_function()
def delete_obs_user_account_if_not_used_by_keycloak_account(
    obs_user: dict,
    keycloak_users: list[dict],
):
    """
    Deletes an OBS user if it is not linked to any Keycloak user.

    Args:
        obs_user (dict): Dictionary representing the OBS user.
        keycloak_users (list[dict]): List of Keycloak user dictionaries.

    Returns:
        None
    """
    if not all(val in obs_user["description"] for val in LIST_CHECK_OVH_DESCRIPTION):
        logger.info(f"The ovh user '{obs_user['username']}' is not created by osam service. Skipping....")
        return
    logger.info(f"Getting the keycloak username from ovh description '{obs_user['description']}'")
    logger.debug(f"DESCRIPTION_TEMPLATE = {DESCRIPTION_TEMPLATE}")
    keycloak_user_id = get_keycloak_user_from_description(obs_user["description"], template=DESCRIPTION_TEMPLATE)
    if not keycloak_user_id:
        logger.info(
            f"Failed to find keycloak username in the description ({obs_user['description']}) for ovh user "
            f"{obs_user['username']}. Skipping....",
        )
        return
    logger.debug(f"Keycloak username = {keycloak_user_id}")
    does_user_exist = False
    for keycloak_user in keycloak_users:
        if keycloak_user["username"] == keycloak_user_id:
            does_user_exist = True
            logger.debug(
                f"The keycloak user '{keycloak_user['username']}' does exist in keycloak, skipping the deletion in ovh",
            )
            break

    if not does_user_exist:
        # NOTE: this may seem strange considering that we retrieve the keycloak_user_id from
        # get_keycloak_user_from_description, but when the original description doesn't match
        # the template, get_keycloak_user_from_description returns the full description
        expected_description = create_description_from_template(keycloak_user_id, template=DESCRIPTION_TEMPLATE)
        logger.debug(f"Expected description: '{expected_description}'")
        if obs_user["description"] == expected_description:
            logger.info(
                f"Removal of the OVH user '{obs_user['username']}' with id {obs_user['id']} linked with a "
                f"removed keycloak user '{keycloak_user_id}'",
            )
            get_ovh_handler().delete_user(obs_user["id"])
        else:
            logger.info(
                f"The OVH user '{obs_user['username']}' with description '{obs_user['description']}' was not "
                f"created by using the current template '{DESCRIPTION_TEMPLATE}'. Skipping....",
            )


@cached(cache=TTLCache(maxsize=OSAM_CREDENTIALS_CACHE_SIZE, ttl=OSAM_CREDENTIALS_CACHE_TTL))
def get_user_s3_credentials(kc_user: str) -> dict:
    """
    Retrieves the S3 access and secret keys for a given user.

    Args:
        kc_user (str): The Keycloak username for whom to retrieve S3 credentials.

    Returns:
        dict: A dictionary containing 'access_key', 'secret_key', 'endpoint', 'region'
        for the user's S3 storage.
    """
    try:
        obs_user = get_keycloak_handler().get_obs_user_from_keycloak_username(kc_user)

        if not obs_user:
            raise RuntimeError(f"No s3 credentials associated with {kc_user}")

        if not (access_key := get_ovh_handler().get_user_s3_access_key(obs_user)):
            raise RuntimeError(f"Error reading user {kc_user} from OVH.")

        secret_key = get_ovh_handler().get_user_s3_secret_key(obs_user, access_key)
        return {
            "access_key": access_key,
            "secret_key": secret_key,
            # NOTE: maybe get the endpoint url and region from another request ?
            # maybe: /cloud/project/{self.ovh_service_name}/storage/access")
            "endpoint": os.environ["S3_ENDPOINT"],
            "region": os.environ["S3_REGION"],
        }

    except Exception as exc:  # pylint: disable = broad-exception-caught
        try:
            obs_user_info = f" / OVH user id: {obs_user!r}"
        except NameError:
            obs_user_info = ""
        raise RuntimeError(
            f"Error while getting s3 credentials for Keycloak user id: {kc_user!r}{obs_user_info}",
        ) from exc


def apply_user_access_policy(user, current_rights):
    """
    Apply access policy over an user in ovh
    """
    msg = ""
    try:
        obs_user = get_keycloak_handler().get_obs_user_from_keycloak_username(user)
        if obs_user:
            get_ovh_handler().apply_user_access_policy(obs_user, current_rights)
            return True, {
                "detail": f"S3 access policy applied for the OVH account associated with the Keycloak user {user}",
            }
    except Exception as exc:  # pylint: disable = broad-exception-caught
        logger.error(f"Error while applying access policy for OVH user id {obs_user}. {exc}")
        msg = str(exc)
    return False, {
        "detail": "Failed to apply the access policy to the OVH account "
        f"associated with the Keycloak account {user}. {msg}",
    }


def add_default_bucket_access(
    bucket: str,
    user: str,
    read_set: set[str],
    write_set: set[str],
    download_set: set[str],
) -> None:
    """
    Adds a default wildcard access path for a user within a specific S3 bucket.

    This function constructs a standardized path of the form:

        <bucket>/<user>/*/

    and ensures that it is present in the provided access control sets
    (read, write, and download). The path is added only if it does not
    already exist in each respective set.

    Args:
        bucket (str): The S3 bucket name.
        user (str): The user identifier used to scope access within the bucket.
        read_set (set[str]): Set of paths with read permissions.
        write_set (set[str]): Set of paths with write permissions.
        download_set (set[str]): Set of paths with download permissions.

    Returns:
        None
    """
    path = os.path.join(bucket.strip(), user, "*") + "/"

    if path not in read_set:
        read_set.add(path)
    if path not in write_set:
        write_set.add(path)
    if path not in download_set:
        download_set.add(path)


@traced_function()
def build_s3_rights(user, user_info):  # pylint: disable=too-many-locals
    """
    Builds the S3 access rights structure for a user based on their Keycloak roles.

    This function classifies roles into read, write, and download operations, then computes
    the corresponding access rights by matching them against a configmap.

    Args:
        user_info (dict): Dictionary containing user attributes, specifically the "keycloak_roles" key
                          with a list of role strings.

    Returns:
        dict: A dictionary with three keys:
              - "read": List of read-only access paths.
              - "read_download": List of read+download access paths.
              - "write_download": List of write+download access paths.
    """
    # Step 1: Parse roles
    read_roles = []
    write_roles = []
    download_roles = []

    for role in user_info["keycloak_roles"]:
        parsed = parse_role(role)
        if not parsed:
            continue
        owner, collection, op = parsed
        if op == "read":
            read_roles.append((owner, collection))
        elif op == "write":
            write_roles.append((owner, collection))
        elif op == "download":
            download_roles.append((owner, collection))

    # Step 2: Match against configmap
    read_set = match_roles(read_roles)
    write_set = match_roles(write_roles)
    download_set = match_roles(download_roles)
    # add the default roles with * for owner, collection and product type, if there is a
    # bucket defined in the configmap. these roles will be assigned to the current
    # user account on ovh when the  /storage/account/{user}/update endpoint is called
    for cfg_owner, cfg_collection, product_type, _, bucket in load_configmap_data():
        if cfg_owner == WILDCARD_CHAR and cfg_collection == WILDCARD_CHAR and product_type == WILDCARD_CHAR:
            logger.debug(f"Adding default bucket access for {bucket.strip()}/{user.strip()}")
            add_default_bucket_access(bucket, user, read_set, write_set, download_set)

    # Step 3: Merge access
    read_only = read_set - download_set - write_set
    read_download = download_set
    write_download = write_set

    # Step 4: Output
    output = {
        STRKEY_ACCESS_RIGHT_READ_LIST: sorted(read_only),
        STRKEY_ACCESS_RIGHT_READ_DWN_LIST: sorted(read_download),
        STRKEY_ACCESS_RIGHT_WRITE_DWN_LIST: sorted(write_download),
    }

    logger.info(json.dumps(output, indent=2))
    return output


@traced_function()
def update_s3_rights_lists(s3_rights):  # pylint: disable=too-many-locals
    """
    Constructs the final user S3 access policy document for ovh based on the provided access rights.

    This function takes access permissions derived from a user's Keycloak roles and configmap and builds
    a structured S3 access policy document. The policy includes separate blocks for read,
    read+download, and write+download permissions, formatted according to OVH-compatible
    bucket and object prefixes.

    The function generates individual policy statements for each type of permission:
      - It constructs bucket-level statements with prefix conditions (e.g., s3:prefix).
      - It generates exact resource permissions using expanded ARN-based paths.
      - It ensures that duplicated prefixes are not added redundantly.
      - Invalid or malformed paths are ignored with a logged warning.

    Args:
        s3_rights (dict): A dictionary of categorized access paths per permission type.
            Expected keys include:
                - 'read': list of paths with read-only access.
                - 'read_download': list of paths with read + download access.
                - 'write_download': list of paths with write + download access.

    Returns:
        dict: A complete S3 access policy document including version and statements,
              ready to be applied to an OVH S3 user.
    """

    # fields from the s3 access rights lists
    access_rights_list_keys = [
        (STRKEY_ACCESS_RIGHT_READ_LIST, BLOCK_LIST_READ_TEMPLATE),
        (STRKEY_ACCESS_RIGHT_READ_DWN_LIST, BLOCK_LIST_READ_DOWNLOAD_TEMPLATE),
        (STRKEY_ACCESS_RIGHT_WRITE_DWN_LIST, BLOCK_LIST_WRITE_DOWNLOAD_TEMPLATE),
    ]
    statements: list[dict[str, Any]] = []

    # Block for bucket level actions
    template_bucketlevelactions: dict[str, Any] = copy.deepcopy(BLOCK_BUCKET_LEVEL_ACTIONS_TEMPLATE)
    template_bucketlevelactions["Resource"] = []

    for key, block in access_rights_list_keys:  # pylint: disable=too-many-nested-blocks
        if not s3_rights.get(key):
            continue
        resources = []
        for access in s3_rights[key]:
            # get the bucket, owner and collection
            parts = access.strip().split("/")
            # protection against a wrong obs access policy
            if len(parts) < 3:
                logger.warning(f"Wrong obs policy access found: {access}")
                continue
            bucket = f"arn:aws:s3:::{parts[0]}"
            owner_collection = f"{parts[1]}/{parts[2]}"

            # Add the bucket to the bucket level actions statement
            if bucket not in template_bucketlevelactions["Resource"]:
                template_bucketlevelactions["Resource"].append(bucket)

            # check in the current statements
            found_in_template_bucket = False
            for stmt in statements:
                if bucket == stmt["Resource"]:
                    found_in_template_bucket = True
                    if owner_collection not in stmt["Condition"]["StringLike"]["s3:prefix"]:
                        stmt["Condition"]["StringLike"]["s3:prefix"].append(owner_collection)
                    break
            if not found_in_template_bucket:
                template_bucket: dict[str, Any] = copy.deepcopy(BLOCK_LIST_BUCKETS)
                template_bucket["Resource"] = bucket
                template_bucket["Condition"]["StringLike"]["s3:prefix"] = [owner_collection]
                statements.append(template_bucket)

            template: dict[str, Any] = copy.deepcopy(block)
            resource = f"{template['Resource'].replace('%placeholder%', access)}"
            # find the first "all" (*) and remove everything after it, because it's useless, and
            # moreover, ovh will not recognize the syntax
            # there should be at least one * char, the last one, see the template['Resource'], last char
            # so no need for protection in case the * char is not found
            resources.append(resource[: resource.find("*") + 1])

        template["Resource"] = resources
        statements.append(template)

    # Final list of statements to be added to the final policy
    final_statements: list[dict[str, Any]] = []

    # NOTE: in the following code, the keys of the dictionary are originally lists
    # (the value of stmt["Condition"]["StringLike"]["s3:prefix"]), BUT, since lists
    # cannot be used as dictionary keys, we convert them to tuples, after applying sort()
    # to ensure that the order of elements does not affect the key.
    merged_statements: dict[tuple, dict] = {}

    # Postprocessing of the statements list to compress it
    for stmt in statements:
        # Check if the statement is ListBucket, and if so compute its key
        stmt_listbucket_key = None
        if stmt["Action"] == BLOCK_LIST_BUCKETS["Action"]:
            # stmt_listbucket_key = tuple(stmt["Condition"]["StringLike"]["s3:prefix"].sort())
            stmt_listbucket_key = tuple(sorted(stmt["Condition"]["StringLike"]["s3:prefix"]))

        # Case 1: another statement than ListBucket => directly add it to the final statements list
        if not stmt_listbucket_key:
            final_statements.append(stmt)
        # Case 2: a ListBucket statement with the same condition already exists => we add its resources to the existing statement
        elif stmt_listbucket_key in merged_statements:
            if not isinstance(merged_statements[stmt_listbucket_key]["Resource"], list):
                merged_statements[stmt_listbucket_key]["Resource"] = [
                    merged_statements[stmt_listbucket_key]["Resource"],
                ]
            merged_statements[stmt_listbucket_key]["Resource"].append(stmt["Resource"])
        # Case 3: a ListBucket statement with a new condition => new entry to the merged_statements dict
        else:
            merged_statements[stmt_listbucket_key] = stmt

    # Add the merged "ListBucket" statements to the final statements list
    final_statements.extend(merged_statements.values())

    # Add the bucket level actions statement
    final_statements.append(template_bucketlevelactions)

    # Fill in main access policy template
    final_policy = copy.deepcopy(S3_ACCESS_RIGHTS_TEMPLATE)
    final_policy["Version"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    final_policy["Statement"] = final_statements
    logger.info(json.dumps(final_policy, indent=2))
    return final_policy
