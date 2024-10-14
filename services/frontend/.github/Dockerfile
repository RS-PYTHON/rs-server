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
FROM python:3.11-slim-bookworm AS builder

# Install dependencies
RUN apt update && apt install -y libpq-dev gcc

# Update pip version
RUN pip install --no-cache-dir --upgrade pip

# The CI builds the wheel packages, downloads them into ./whl/, then builds this Dockerfile from ./whl/,
# so the .whl files are under ./*.whl
# We copy them into a /tmp directory that we can clean at the end.
RUN mkdir -p /tmp/whl
ADD ./*.whl /tmp/whl

# Install the wheel packages in the right order (dependencies first).
# This also installs all the sub-dependencies e.g. fastapi etc ...
RUN cd /tmp/whl && pip install --no-cache-dir rs_server_frontend-*.whl

# Final stage. Don't use alpine, it's too different from the build stage.
FROM python:3.11-slim-bookworm

# Copy the python installation from the build stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Set env var to the aggregated openapi.json released in the .whl package
ENV RSPY_OPENAPI_FILE=/usr/local/lib/python3.11/site-packages/resources/openapi.json

# Copy the script that will be run as this image entrypoint
RUN mkdir -p /scripts
ADD ./entrypoint_frontend.sh /scripts

# Allow the user to execute and modify these files.
RUN chmod ugo+x /scripts/entrypoint_frontend.sh
# Give write permissions to the parent directory so sed can work.
RUN chmod -R ugo+w $(dirname "${RSPY_OPENAPI_FILE}")

# Clean everything
RUN rm -rf /tmp/whl /root/.cache/pip /var/cache/apt/archives /var/lib/apt/lists/*

# Add a default user
RUN useradd -m user
USER user
WORKDIR /home/user

# The CI/CD will replace this tag in debug mode or else remove it
# [DEBUG_MODE_COMMANDS]

# After this, make sure we're still non-root
USER user

ENTRYPOINT [ "/bin/bash", "-c", "set -x; /scripts/entrypoint_frontend.sh [DEBUG_MODE_RELOAD_FRONTEND]" ]
