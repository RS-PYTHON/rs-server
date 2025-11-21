# Copyright 2024 CS Group
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

ARG PYTHON_VERSION=3.13.9

# Build stage for multi stage build.
FROM ghcr.io/rs-python/python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY ./layer-cleanup.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh

# Install dependencies
RUN apt update && apt upgrade -y && apt install -y libpq-dev gcc && layer-cleanup.sh

# Update pip version
RUN pip install --no-cache-dir --upgrade pip && layer-cleanup.sh

# The CI builds the wheel packages, downloads them into ./whl/, then builds this Dockerfile from ./whl/,
# so the .whl files are under ./*.whl
# We copy them into a /tmp directory that we can clean at the end.
RUN mkdir -p /tmp/whl
ADD ./*.whl /tmp/whl

# Install the wheel packages in the right order (dependencies first).
# This also installs all the sub-dependencies e.g. fastapi etc ...
RUN cd /tmp/whl && pip install --no-cache-dir rs_server_frontend-*.whl && layer-cleanup.sh

# Final stage. Don't use alpine, it's too different from the build stage.
FROM ghcr.io/rs-python/python:${PYTHON_VERSION}-slim-bookworm

COPY ./layer-cleanup.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh

# Update dependencies
RUN apt update && apt upgrade -y && layer-cleanup.sh

# Copy the python installation from the build stage
COPY --from=builder /usr/local/lib/python3.*/site-packages /usr/local/lib/python3.*/site-packages

# Set env var to the aggregated openapi.json released in the .whl package
ENV RSPY_OPENAPI_FILE=/usr/local/lib/python3.*/site-packages/resources/openapi.json

# Copy the script that will be run as this image entrypoint
RUN mkdir -p /scripts
ADD ./entrypoint_frontend.sh /scripts

# Allow the user to execute and modify these files.
RUN chmod ugo+x /scripts/entrypoint_frontend.sh
# Give write permissions to the parent directory so sed can work.
RUN chmod -R ugo+w $(dirname "${RSPY_OPENAPI_FILE}")

# Add a default user
ARG USER=user
RUN useradd -m $USER
USER $USER
WORKDIR /home/$USER

# The CI/CD will replace this tag in debug mode or else remove it
# [DEBUG_MODE_COMMANDS]

# Remove apt repository list and custom scripts
USER root
RUN rm -f /etc/apt/sources.list /usr/local/bin/layer-cleanup.sh /usr/local/bin/restore-apt.sh
USER $USER

ENTRYPOINT [ "/bin/bash", "-c", "set -x; /scripts/entrypoint_frontend.sh [DEBUG_MODE_RELOAD_FRONTEND]" ]

# Set labels based on the Open Containers Initiative (OCI):
# https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys
#
LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/rs-server"
LABEL org.opencontainers.image.ref.name="ghcr.io/rs-python/rs-server-frontend"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/services/frontend/.github/Dockerfile"
