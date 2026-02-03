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

#
# Target Docker image name:
# ghcr.io/rs-python/rs-server-prip
#

ARG PYTHON_VERSION=3.13.11

# Don't use alpine, it's too different from the build stage.
FROM ghcr.io/rs-python/python:${PYTHON_VERSION}-slim-bookworm

COPY ./layer-cleanup.sh ./restore-apt.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh

# Install git (for dependencies from forks) and system deps for pyproj
RUN restore-apt.sh && \
    apt update && apt upgrade -y && \
    apt install -y git libproj-dev proj-data build-essential && \
    layer-cleanup.sh

# Update pip version
RUN pip install --no-cache-dir --upgrade pip && layer-cleanup.sh

# The CI builds the wheel packages, downloads them into ./whl/, then builds this Dockerfile from ./whl/,
# so the .whl files are under ./*.whl
# We copy them into a /tmp directory that we can clean at the end.
RUN mkdir -p /tmp/whl
ADD ./*.whl /tmp/whl

# Install footprint-facility BEFORE the wheels so that pyproj is present
RUN python -m pip install --no-cache-dir footprint-facility==1.11

# Install the wheel packages in the right order (dependencies first)
RUN cd /tmp/whl && pip install --no-cache-dir \
    --extra-index-url=https://home.rs-python.eu/local-pypi/ \
    rs_server_common-*.whl rs_server_prip-*.whl && \
    layer-cleanup.sh

# Install opentelemetry instrumentation packages for dependencies
RUN opentelemetry-bootstrap -a install && layer-cleanup.sh

# Remove build-only dependencies
RUN apt autoremove -y git build-essential && layer-cleanup.sh

# Add a default user
ARG USER=user
RUN useradd -m $USER
USER $USER
WORKDIR /home/$USER

# The CI/CD will replace this tag in debug mode or else remove it
# [DEBUG_MODE_COMMANDS]

# Remove custom scripts
USER root
RUN rm -f /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh
USER $USER

ENTRYPOINT [ \
    "python", "-m", "uvicorn", "rs_server_prip.fastapi.prip_app:app", \
    "--host", "0.0.0.0", "--port", "8000", "[DEBUG_MODE_RELOAD]" ]

# Set labels based on the Open Containers Initiative (OCI):
# https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys
#
LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/rs-server"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/services/prip/.github/Dockerfile"
