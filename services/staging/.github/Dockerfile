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


# Build stage for multi stage build.
FROM ghcr.io/rs-python/python:3.11.7-slim-bookworm AS builder

COPY ./layer-cleanup.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh

# Install dependencies for compilation
RUN apt update && apt upgrade -y && apt install -y libpq-dev gcc git && layer-cleanup.sh

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
    rs_server_common-*.whl rs_server_staging-*.whl && \
    layer-cleanup.sh

# Final stage. Don't use alpine, it's too different from the build stage.
FROM ghcr.io/rs-python/python:3.11.7-slim-bookworm

COPY ./layer-cleanup.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/layer-cleanup.sh

# Install dependencies necessary for execution (e.g. libpq) not compilation (gcc)
RUN apt update && apt upgrade -y && \
    apt install -y libpq-dev libexpat1 && \
    layer-cleanup.sh

# Copy the whole /usr/local dir (that contains the python installation) from the build stage
COPY --from=builder /usr/local /usr/local

# Install opentelemetry instrumentation packages for dependencies
RUN opentelemetry-bootstrap -a install && layer-cleanup.sh

# Add a default user
RUN useradd -m user
USER user
WORKDIR /home/user

# The CI/CD will replace this tag in debug mode or else remove it
# [DEBUG_MODE_COMMANDS]

# After this, make sure we're still non-root
USER user

ENTRYPOINT [ \
    "python", "-m", "uvicorn", "rs_server_staging.main:app", \
    "--host", "0.0.0.0", "--port", "8000", "[DEBUG_MODE_RELOAD]" ]

# Set labels based on the Open Containers Initiative (OCI):
# https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys
#
LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/rs-server"
LABEL org.opencontainers.image.ref.name="ghcr.io/rs-python/rs-server-staging"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/services/staging/.github/Dockerfile"
