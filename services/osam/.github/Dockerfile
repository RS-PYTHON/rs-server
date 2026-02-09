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
# ghcr.io/rs-python/operational-services-osam
#

ARG PYTHON_VERSION=3.13.11

# Don't use alpine, it's too different from the build stage.
FROM ghcr.io/rs-python/python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY ./layer-cleanup.sh ./restore-apt.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh

# Install dependencies for compilation
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
    rs_server_common-*.whl rs_server_osam-*.whl && \
    layer-cleanup.sh

# Final stage. Don't use alpine, it's too different from the build stage.
FROM ghcr.io/rs-python/python:${PYTHON_VERSION}-slim-bookworm

COPY ./layer-cleanup.sh ./restore-apt.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh

# Reinstall git since this is a new image layer
RUN restore-apt.sh && apt update && apt install -y git && layer-cleanup.sh

# Copy the whole /usr/local dir (that contains the python installation) from the build stage
COPY --from=builder /usr/local /usr/local

# Install opentelemetry instrumentation packages for dependencies
RUN opentelemetry-bootstrap -a install && layer-cleanup.sh

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
    "python", "-m", "uvicorn", "osam.main:app", \
    "--host", "0.0.0.0", "--port", "8000", "[DEBUG_MODE_RELOAD]" ]

LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/operational-services"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/services/osam/.github/Dockerfile"
