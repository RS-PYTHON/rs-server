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

#
# Target Docker image name:
# ghcr.io/rs-python/rs-server-catalog
#

ARG PYTHON_VERSION=3.13.12

# Don't use alpine, it's too different from the build stage.
FROM ghcr.io/rs-python/python:${PYTHON_VERSION}-slim-bookworm

COPY ./layer-cleanup.sh ./restore-apt.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh

# Install git to install dependencies from forked repositories
RUN restore-apt.sh && apt update && apt upgrade -y && apt install -y git && layer-cleanup.sh

# Update pip version
RUN pip install --no-cache-dir --upgrade pip && layer-cleanup.sh

# The CI builds the wheel packages, downloads them into ./whl/, then builds this Dockerfile from ./whl/,
# so the .whl files are under ./*.whl
# We copy them into a /tmp directory that we can clean at the end.
RUN mkdir -p /tmp/whl
ADD ./*.whl /tmp/whl

# Install the wheel packages in the right order (dependencies first).
# This also installs all the sub-dependencies e.g. fastapi etc ...
# https://home.rs-python.eu/local-pypi is used for additional dependencies, see: https://github.com/RS-PYTHON/local-pypi
RUN cd /tmp/whl && pip install --no-cache-dir \
    --extra-index-url=https://home.rs-python.eu/local-pypi/ \
    rs_server_common-*.whl rs_server_catalog-*.whl && \
    layer-cleanup.sh

# Install opentelemetry instrumentation packages for dependencies
RUN opentelemetry-bootstrap -a install && layer-cleanup.sh

# Remove dependencies that are need only for compilation, not execution
RUN apt autoremove -y git && layer-cleanup.sh

# Add a default user
ARG USER=user
RUN useradd -m $USER
USER $USER
WORKDIR /home/$USER

# The CI/CD will replace this tag in debug mode or else remove it
# [DEBUG_MODE_COMMANDS]

# [DEBUG_MODE_RELOAD_CATALOG]

# Remove custom scripts
USER root
RUN rm -f /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh
USER $USER

# See: rs_server_catalog/main.py
# uvicorn.run(
#     "stac_fastapi.pgstac.app:app",
#     host=settings.app_host,
#     port=settings.app_port,
#     log_level="info",
#     reload=settings.reload,
#     root_path=os.getenv("UVICORN_ROOT_PATH", ""),
ENTRYPOINT [ "python", "-m", "rs_server_catalog.main" ]

# Set labels based on the Open Containers Initiative (OCI):
# https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys
#
LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/rs-server"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/services/catalog/.github/Dockerfile"
