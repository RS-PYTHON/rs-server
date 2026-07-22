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

"""Tasks used in processors."""

import json
import logging
import os
from urllib.parse import urlparse

from opentelemetry import context, propagate, trace
from rs_server_common.authentication.authentication_to_external import (
    ServiceNotFound,
    load_external_auth_config_by_domain,
)
from rs_server_common.authentication.external_authentication_config import (
    ExternalAuthenticationConfig,
    S3ExternalAuthenticationConfig,
)
from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_bucket_name_from_config,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3_MAX_RETRIES,
    S3_RETRY_TIMEOUT,
    S3StorageHandler,
)
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import S3Credentials
from rs_server_staging.utils.asset_info import (
    AssetInfo,
    IncompleteAssetError,
    IncompleteFeatureError,
)
from rs_server_staging.utils.rspy_models import Feature

logger = Logging.default(__name__)


def _asset_size_from_metadata(asset_content: dict, asset_name: str) -> int | None:
    """Return the STAC file:size value when it is available and valid."""
    asset_size = asset_content.get("file:size")
    if asset_size is None:
        return None
    if isinstance(asset_size, bool):
        raise ValueError(f"Invalid file:size value for asset {asset_name}: {asset_size!r}")
    try:
        size_bytes = int(asset_size)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid file:size value for asset {asset_name}: {asset_size!r}") from exc
    if size_bytes < 0:
        raise ValueError(f"Invalid negative file:size value for asset {asset_name}: {asset_size!r}")
    return size_bytes


def _report_streaming_progress(progress_queue, asset_key: str, message: dict, logger_dask: logging.Logger):
    """Best-effort progress report from a Dask worker to the staging monitor."""
    if progress_queue is None:
        return
    try:
        progress_queue.put({"asset": asset_key, **message})
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger_dask.warning("Failed to report staging progress for %s: %s", asset_key, exc)


def restore_context_from_env():
    """Restore an OpenTelemetry context propagated through environment variables.

    This function reads the ``OTEL_TRACE_CONTEXT`` environment variable,
    which is expected to contain a JSON-encoded carrier produced by
    ``opentelemetry.propagate.inject`` in a parent process. The context
    is extracted and attached to the current execution context so that
    spans created in this process continue the existing trace.
    """
    carrier_json = os.environ.get("OTEL_TRACE_CONTEXT")
    if not carrier_json:
        return
    context.attach(propagate.extract(json.loads(carrier_json)))


def streaming_task(task_env: dict[str, str], *args, **kwargs):
    """
    This method is run from the dask pod.
    Init the opentelemetry context before calling the main task method.

    Attributes:
        task_env: env variables coming from the caller
    """
    # Copy env vars from the caller
    keys = [
        "OTEL_SERVICE_NAME",
        "OTEL_TRACE_CONTEXT",
        "TEMPO_ENDPOINT",
        "TRACEPARENT",
        "TRACESTATE",
    ]

    # Copy our environment variables
    for key in keys:
        if value := task_env.get(key):
            os.environ[key] = value
    # Copy all OpenTelemetry environment variables
    for key, value in task_env.items():
        if key.startswith("OTEL_"):
            os.environ[key] = value

    # Debug gRPC Connectivity
    # https://opentelemetry.io/docs/zero-code/python/troubleshooting/#grpc-connectivity
    # os.environ["GRPC_VERBOSITY"] = "debug"
    # os.environ["GRPC_TRACE"] = "http,call_error,connectivity_state"

    # Never trace http response body, because it's the downloaded streamed content
    # and it's probably too big to be traced in otel
    os.environ["OTEL_PYTHON_REQUESTS_TRACE_BODY"] = "0"

    # Init opentelemetry
    init_opentelemetry.init_traces(None, os.environ["OTEL_SERVICE_NAME"])

    # Restore OpenTelemetry context
    restore_context_from_env()

    # Call the main task method from an opentelemetry span
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("streaming_task"):
        return _streaming_task_otel(*args, **kwargs)


def _streaming_task_otel(  # pylint: disable=R0913, R0917
    asset_info: AssetInfo,
    config: ExternalAuthenticationConfig | None,
    auth: str | None,
    s3_credentials: S3Credentials,
    progress_queue=None,
):
    """
    This method is run from the dask pod.

    Streams a file from a product URL and uploads it to an S3-compatible storage.

    This function downloads a file from the specified `product_url` using provided
    authentication and uploads it to an S3 bucket using a streaming mechanism.
    If no S3 handler is provided, it initializes a default `S3StorageHandler` using
    environment variables for credentials.

    Args:

        asset_info (AssetInfo): Object containing the essential informations about the product
            to download, such as its URL, the destination bucket name and the destination path/key
            in the S3 bucket where the file will be uploaded.
        config (ExternalAuthenticationConfig): Optional authentification configuration containing
            the list of trusted domains
        auth (str): Optional station token. This has to be refreshed from the caller
        s3_credentials: S3 object storage credentials
        progress_queue: Optional Dask queue used to report streamed byte increments.
    Returns:
        str: The S3 file path where the file was uploaded.

    Raises:
        ValueError: If the streaming process fails, raises a ValueError with details of the failure.

    Retry Mechanism:
        - Retries occur for network-related errors (`RequestException`) or S3 client errors
        (`ClientError`, `BotoCoreError`).
        - The function waits S3_RETRY_TIMEOUT seconds before retrying
        - It keeps trying for S3_MAX_RETRIES times

    Logging:
        - `info` records task lifecycle and source/destination identifiers.
        - `debug` records retry attempts and non-sensitive routing details.
        Credential values are intentionally never logged.
    """

    logger_dask = logging.getLogger(__name__)

    product_url = asset_info.product_url
    s3_file = asset_info.s3_file
    bucket = asset_info.s3_bucket
    logger_dask.info("The streaming task started for %s -> s3://%s/%s", product_url, bucket, s3_file)
    logger_dask.debug(
        "Streaming task input: origin_service=%s, domain=%s, trusted_domains=%s",
        asset_info.origin_service,
        asset_info.domain,
        asset_info.trusted_domains,
    )
    # get the retry timeout
    s3_retry_timeout = int(os.environ.get("S3_RETRY_TIMEOUT", S3_RETRY_TIMEOUT))
    # get the number of retries in case of failure
    max_retries = int(os.environ.get("S3_MAX_RETRIES", S3_MAX_RETRIES))
    # set counter for retries
    attempt = 0
    while attempt < max_retries:
        try:
            _report_streaming_progress(progress_queue, s3_file, {"reset": True}, logger_dask)

            def download_progress_callback(bytes_amount: int):
                _report_streaming_progress(
                    progress_queue,
                    s3_file,
                    {"bytes": int(bytes_amount)},
                    logger_dask,
                )

            # Create the handler inside the retry loop because failed streaming
            # attempts can leave connections in an uncertain state.
            logger_dask.debug("%s: Creating the s3_handler (attempt %d/%d)", s3_file, attempt + 1, max_retries)
            s3_handler = S3StorageHandler(s3_credentials)
            if product_url.startswith("s3://"):
                # External S3-to-catalog S3 copies use credentials resolved from
                # the feature storage scheme, not the station token flow.
                logger_dask.info("Streaming external S3 asset to s3://%s/%s", bucket, s3_file)
                s3_handler.s3_streaming_from_s3(
                    product_url,
                    asset_info.external_s3_endpoint_url,
                    asset_info.external_s3_access_key,
                    asset_info.external_s3_secret_key,
                    bucket,
                    s3_file,
                    asset_info.trusted_domains,
                    download_progress_callback,
                )
            else:
                # HTTP/FTP-like sources rely on the station auth config and
                # optional token prepared by the parent staging workflow.
                logger_dask.info("Streaming HTTP asset to s3://%s/%s", bucket, s3_file)
                s3_handler.s3_streaming_from_http(
                    product_url,
                    config.trusted_domains if config else [],
                    auth,
                    bucket,
                    s3_file,
                    config.max_requests_per_minute if config else None,
                    download_progress_callback,
                )

            s3_handler.disconnect_s3()
            logger_dask.debug("Disconnected S3 handler after streaming %s", s3_file)
            break
        except ConnectionError as e:
            attempt += 1
            if attempt < max_retries:
                # Connection failures are considered transient at the S3 layer,
                # so wait using the storage handler retry policy before retrying.
                s3_handler.disconnect_s3()
                logger_dask.error(f"S3 level failed to stream. Retrying in {s3_retry_timeout} seconds.")
                s3_handler.wait_timeout(s3_retry_timeout)
                continue
            logger_dask.exception(f"S3 level failed to stream. Tried for {max_retries} times, giving up")
            raise ValueError(
                f"Dask task failed to stream file from {product_url} to s3://{bucket}/{s3_file}. Reason: {e}",
            ) from e
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


def prepare_streaming_tasks(
    catalog_collection: str,
    feature: Feature,
    staging_user: str,
    named_assets=False,
) -> list[AssetInfo] | None:
    """Prepare Dask streaming task inputs for all assets of a STAC feature.

    This function also rewrites each asset href in the feature to the final
    catalog S3 location. That mutation is intentional: once streaming succeeds,
    the same feature object is published to the catalog with staged asset paths.

    Args:
        catalog_collection (str): Name of the catalog collection.
        feature: The feature containing assets to download.
        staging_user (str): The user for whom to stage the assets.
        named_assets (bool): If True, prefer asset `file:local_path` as the
            destination asset name when present.

    Returns:
        A list of AssetInfo objects used by Dask, or None when an asset is
        missing the minimum href/name information.
    """
    # Bucket selection depends on logical ownership, collection and optional
    # EOPF type; this keeps staging aligned with catalog storage partitioning.
    owner = feature.properties.get("owner", staging_user)
    eopf_type = feature.properties.get("eopf:type", "")
    s3_bucket_name = get_bucket_name_from_config(owner, catalog_collection, eopf_type)
    logger.info(
        "Preparing streaming tasks for feature %s in collection %s; bucket=%s",
        feature.id,
        catalog_collection,
        s3_bucket_name,
    )
    logger.debug(
        "Feature %s task preparation input: owner=%s, eopf_type=%s, asset_names=%s, named_assets=%s",
        feature.id,
        owner,
        eopf_type,
        list(feature.assets.keys()),
        named_assets,
    )

    assets_info: list[AssetInfo] = []

    for original_asset_name, asset_content in list(feature.assets.items()):
        asset_name = original_asset_name
        if not asset_content.href or not asset_name:
            logger.error("Missing href or title in asset dictionary")
            return None

        asset_metadata = asset_content.to_dict()

        # The final object key is deterministic and includes the staging user,
        # collection, item id and asset name so cleanup and catalog publication can
        # reconstruct the same object identity from logs.
        if named_assets:
            # if named_assets is True and file:local_path exists in the asset content,
            # use it as asset name instead of the key in the assets dict
            # otherwise, the asset name will be the key in the assets dict, as before
            asset_name = asset_metadata.get("file:local_path", asset_name)
        s3_obj_path = f"{staging_user}/{catalog_collection}/{feature.id.rstrip('/')}/{asset_name}"

        origin_service = urlparse(asset_content.href).scheme
        logger.debug(
            "Preparing asset %s for feature %s; origin_service=%s, destination=s3://%s/%s",
            asset_name,
            feature.id,
            origin_service,
            s3_bucket_name,
            s3_obj_path,
        )
        if origin_service == "s3":
            # S3 origins need extra credentials/trusted-domain metadata extracted
            # from STAC storage extensions before the Dask task can run.
            asset_info = create_asset_info_with_s3_auth(
                feature,
                asset_name,
                asset_metadata,
                s3_obj_path,
                s3_bucket_name,
            )
        else:
            # Non-S3 origins are streamed through the station auth path.
            asset_info = AssetInfo(product_url=asset_content.href, s3_file=s3_obj_path, s3_bucket=s3_bucket_name)

        asset_info.size_bytes = _asset_size_from_metadata(asset_metadata, asset_name)
        assets_info.append(asset_info)
        # Mutate the feature in place so the later catalog POST/PUT references
        # the object that the Dask task is about to create.
        asset_content.href = f"s3://{s3_bucket_name}/{s3_obj_path}"
        if asset_name != original_asset_name:
            # The asset was renamed to its file:local_path: drop the original
            # key so the asset is not published twice under both names.
            del feature.assets[original_asset_name]
        feature.assets[asset_name] = asset_content
    logger.info("Prepared %d streaming task(s) for feature %s", len(assets_info), feature.id)
    return assets_info


def create_asset_info_with_s3_auth(
    feature: Feature,
    asset_name: str,
    asset_content: dict,
    s3_file: str,
    s3_bucket: str,
) -> AssetInfo:
    """Build AssetInfo for an asset staged from an external S3 bucket.

    The function reads the STAC `storage:refs` and `storage:schemes` fields,
    finds the first referenced scheme that has a matching external S3
    authentication configuration, and copies only the required credentials into
    the AssetInfo passed to Dask. Credential values are not logged.

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
    feature_id = getattr(feature, "id", None)
    logger.info("Resolving external S3 credentials for feature %s asset %s", feature_id, asset_name)
    if "storage:refs" not in asset_content.keys():
        raise IncompleteAssetError(f"Missing field 'storage:refs' in asset {asset_name}.")
    if "storage:schemes" not in feature.properties.keys():
        raise IncompleteFeatureError(f"Missing field 'storage:schemes' in feature {feature.id}.")

    storage_refs = asset_content["storage:refs"]
    storage_schemes: dict = feature.properties.get("storage:schemes")
    s3_authentication_config = None
    logger.debug(
        "External S3 credential lookup for feature %s asset %s; refs=%s",
        feature.id,
        asset_name,
        storage_refs,
    )

    # Try refs in STAC order and stop at the first scheme that resolves to usable
    # credentials. This lets products advertise several storage locations while
    # keeping task preparation deterministic.
    for ref in storage_refs:
        logger.debug("Checking storage ref %s for feature %s asset %s", ref, feature.id, asset_name)
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
        size_bytes=_asset_size_from_metadata(asset_content, asset_name),
    )


def find_credentials_for_external_s3_storage(
    storage_scheme: dict,
    storage_scheme_name: str,
) -> S3ExternalAuthenticationConfig:
    """Resolve external S3 credentials from a STAC storage scheme.

    The storage scheme `platform` field is parsed as a domain and matched
    against the external authentication configuration. Only S3 auth
    configurations are accepted.

    Args:
        storage_scheme (dict): storage_scheme from the feature.
        storage_scheme_name (str): Name of the storage scheme.

    Returns:
        S3ExternalAuthenticationConfig when credentials exist, otherwise None.
    """
    domain = storage_scheme.get("platform", "")
    logger.debug("Looking up external S3 authentication config for storage scheme %s", storage_scheme_name)

    if not domain:
        logger.warning(
            f"Could not retrieve external S3 credentials, storage scheme {storage_scheme_name} "
            "doesn't have field 'platform'.",
        )
        return None
    domain = urlparse(domain).hostname
    logger.debug("Resolved storage scheme %s to domain %s", storage_scheme_name, domain)

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
