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

"""Tasks used in processors."""

import logging
import os
from urllib.parse import urlparse

from rs_server_common.authentication.authentication_to_external import (
    S3ExternalAuthenticationConfig,
    ServiceNotFound,
    StationExternalAuthenticationConfig,
    load_external_auth_config_by_domain,
)
from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_bucket_name_from_config,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3_MAX_RETRIES,
    S3_RETRY_TIMEOUT,
    S3StorageHandler,
)
from rs_server_common.utils.logging import Logging
from rs_server_staging.utils.asset_info import (
    AssetInfo,
    IncompleteAssetError,
    IncompleteFeatureError,
)
from rs_server_staging.utils.rspy_models import Feature

logger = Logging.default(__name__)


def streaming_task(  # pylint: disable=R0913, R0917
    asset_info: AssetInfo,
    config: StationExternalAuthenticationConfig | S3ExternalAuthenticationConfig,
    auth: str,
):
    """
    Streams a file from a product URL and uploads it to an S3-compatible storage.

    This function downloads a file from the specified `product_url` using provided
    authentication and uploads it to an S3 bucket using a streaming mechanism.
    If no S3 handler is provided, it initializes a default `S3StorageHandler` using
    environment variables for credentials.

    Args:
        asset_info (AssetInfo): Object containing the essential informations about the product
            to download, such as its URL, the destination bucket name and the destination path/key
            in the S3 bucket where the file will be uploaded.
        config (StationExternalAuthenticationConfig | S3ExternalAuthenticationConfig): Authentification
            configuration containing the list of trusted domains
        auth: The station token. This has to be refreshed from the caller
    Returns:
        str: The S3 file path where the file was uploaded.

    Raises:
        ValueError: If the streaming process fails, raises a ValueError with details of the failure.

    Retry Mechanism:
        - Retries occur for network-related errors (`RequestException`) or S3 client errors
        (`ClientError`, `BotoCoreError`).
        - The function waits before retrying, with the delay time increasing exponentially
        (based on the `backoff_factor`).
        - The backoff formula is `backoff_factor * (2 ** (attempt - 1))`, allowing progressively
        longer wait times between retries.
    """

    logger_dask = logging.getLogger(__name__)
    logger_dask.info("The streaming task started")

    product_url = asset_info.product_url
    s3_file = asset_info.s3_file
    bucket = asset_info.s3_bucket
    # time.sleep(5)
    # get the retry timeout
    s3_retry_timeout = int(os.environ.get("S3_RETRY_TIMEOUT", S3_RETRY_TIMEOUT))
    # get the number of retries in case of failure
    max_retries = int(os.environ.get("S3_MAX_RETRIES", S3_MAX_RETRIES))
    # set counter for retries
    attempt = 0
    while attempt < max_retries:
        try:
            logger_dask.debug(f"{s3_file}: Creating the s3_handler")
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )

            if not auth:
                s3_handler.s3_streaming_from_s3(
                    product_url,
                    asset_info.external_s3_endpoint_url,
                    asset_info.external_s3_access_key,
                    asset_info.external_s3_secret_key,
                    bucket,
                    s3_file,
                    asset_info.trusted_domains,
                )
            else:
                s3_handler.s3_streaming_from_http(product_url, config.trusted_domains, auth, bucket, s3_file)

            s3_handler.disconnect_s3()
            break
        except ConnectionError as e:
            attempt += 1
            if attempt < max_retries:
                # keep retrying
                s3_handler.disconnect_s3()
                logger_dask.error(f"S3 level failed to stream. Retrying in {s3_retry_timeout} seconds.")
                s3_handler.wait_timeout(s3_retry_timeout)
                continue
            logger_dask.exception(f"S3 level failed to stream. Tried for {max_retries} times, giving up")
            raise ValueError(
                f"Dask task failed to stream file from {product_url} to s3://{bucket}/{s3_file}. Reason: {e}",
            ) from e
        except KeyError as key_exc:
            logger_dask.exception(f"KeyError exception in streaming_task for {s3_file}: {key_exc}")
            raise ValueError(f"Cannot create s3 connector object. Reason: {key_exc}") from key_exc
        except RuntimeError as e:
            logger_dask.exception(f"RuntimeError exception in streaming_task for {s3_file} : {e}")
            raise ValueError(
                f"Dask task failed to stream file from {product_url} to s3://{bucket}/{s3_file}. Reason: {e}",
            ) from e
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger_dask.exception(f"Unhandled exception in streaming_task for {s3_file} : {e}")
            raise ValueError(
                f"Unhandled exception in streaming_task : {e}",
            ) from e
    logger_dask.info(f"The streaming task finished. Returning name of the streamed file {s3_file}")
    return s3_file


def prepare_streaming_tasks(catalog_collection: str, feature: Feature, staging_user: str) -> list[AssetInfo] | None:
    """Prepare tasks for the given feature to the Dask cluster.

    Args:
        catalog_collection (str): Name of the catalog collection.
        feature: The feature containing assets to download.

    Returns:
        True if the info has been constructed, False otherwise
    """
    # Get infos from feature to retrieve S3 bucket name from configuration
    owner = feature.properties.get("owner", "*")
    eopf_type = feature.properties.get("eopf:type", "*")
    s3_bucket_name = get_bucket_name_from_config(owner, catalog_collection, eopf_type)

    assets_info: list[AssetInfo] = []

    for asset_name, asset_content in feature.assets.items():
        if not asset_content.href or not asset_name:
            logger.error("Missing href or title in asset dictionary")
            return None
        # Add the user_collection as main directory, as soon as the authentication will be
        # implemented in this staging process
        s3_obj_path = f"{staging_user}/{catalog_collection}/{feature.id.rstrip('/')}/{asset_name}"

        origin_service = urlparse(asset_content.href).scheme
        if origin_service == "s3":
            asset_info = create_asset_info_with_s3_auth(
                feature,
                asset_name,
                asset_content.model_dump(),
                s3_obj_path,
                s3_bucket_name,
            )
        else:
            asset_info = AssetInfo(product_url=asset_content.href, s3_file=s3_obj_path, s3_bucket=s3_bucket_name)

        assets_info.append(asset_info)
        # update the s3 path, this will be checked in the rs-server-catalog in the
        # publishing phase
        asset_content.href = f"s3://rtmpop/{s3_obj_path}"
        feature.assets[asset_name] = asset_content
    return assets_info


def create_asset_info_with_s3_auth(
    feature: Feature,
    asset_name: str,
    asset_content: dict,
    s3_file: str,
    s3_bucket: str,
) -> AssetInfo:
    """Specific to assets being staged from an external S3 bucket.
    This function returns an AssetInfo with credentials for the S3 bucket.

    Args:
        feature (Feature): The feature containing asset to download.
        asset_name (str): Name of the asset to find credentials for.
        asset_content (dict): STAC description of the asset.
        s3_file (str): S3 file path where the file will be uploaded.
        s3_bucket (str): S3 bucket where the file will be uploaded.

    Returns:
        AssetInfo with credentials for the external S3 bucket.

    Raises:
        IncompleteAssetError: If the asset misses a necessary field.
        IncompleteFeatureError: If the feature misses a necessary field.
        RuntimeError: When no credentials were found for any reason.
    """
    if "storage:refs" not in asset_content.keys():
        raise IncompleteAssetError(f"Missing field 'storage:refs' in asset {asset_name}.")
    if "storage:schemes" not in feature.properties.keys():
        raise IncompleteFeatureError(f"Missing field 'storage:schemes' in feature {feature.id}.")

    storage_refs = asset_content["storage:refs"]
    storage_schemes: dict = feature.properties.get("storage:schemes")
    s3_authentication_config = None

    # Find the first storage ref of the asset that is linked to a storage scheme in the feature,
    # for which credentials exist
    for ref in storage_refs:
        if ref not in storage_schemes.keys():
            logger.warning(f"No storage scheme found for storage ref '{ref}' in feature {feature.id}.")
        else:
            scheme = storage_schemes.get(ref)
            if isinstance(scheme, dict):
                s3_authentication_config = find_credentials_for_external_s3_storage(scheme, ref)
                if s3_authentication_config:
                    logger.info(f"Found credentials to storage ref {ref} for asset {asset_name}.")
                    break
            else:
                logger.warning(
                    f"Storage scheme found for storage ref '{ref}' in feature {feature.id}, "
                    "but has type {type(storage_schemes.get(ref))} instead of dict.",
                )

    if not s3_authentication_config:
        raise RuntimeError(
            f"Could not find credentials for any of the external S3 buckets from this list: {storage_refs}.",
        )

    return AssetInfo(
        product_url=asset_content["href"],
        s3_file=s3_file,
        s3_bucket=s3_bucket,
        origin_service="s3",
        external_s3_endpoint_url=s3_authentication_config.service_url,
        external_s3_access_key=s3_authentication_config.access_key,
        external_s3_secret_key=s3_authentication_config.secret_key,
        trusted_domains=s3_authentication_config.trusted_domains,
    )


def find_credentials_for_external_s3_storage(
    storage_scheme: dict,
    storage_scheme_name: str,
) -> S3ExternalAuthenticationConfig:
    """Uses the platform field of the storage scheme to get credentials from configuration if they exist.

    Args:
        storage_scheme (dict): storage_scheme from the feature.
        storage_scheme_name (str): Name of the storage scheme.

    Returns:
        Access key and secret key or empty strings if no credentials were found.
    """
    domain = storage_scheme.get("platform", "")

    if not domain:
        logger.warning(
            f"Could not retrieve external S3 credentials, storage scheme {storage_scheme_name} "
            "doesn't have field 'platform'.",
        )
        return None
    domain = urlparse(domain).hostname

    try:
        authentication_config = load_external_auth_config_by_domain(domain)
    except ServiceNotFound:
        logger.warning(
            f"Did not find S3 authentication configuration for domain {domain}: configuration does not exist.",
        )
        return None

    if not isinstance(authentication_config, S3ExternalAuthenticationConfig):
        logger.warning(f"Did not find S3 authentication configuration for domain {domain}: wrong configuration format.")
        return None

    logger.info(f"Credentials found for storage scheme {storage_scheme_name} (domain: {domain}).")

    return authentication_config
