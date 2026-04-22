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
# ghcr.io/rs-python/rs-server-adgs
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
