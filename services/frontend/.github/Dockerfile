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
FROM python:3.11-slim-bookworm as builder

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
# This also installs all the sub-dependencies e.g. fastapi ect ...
RUN cd /tmp/whl && pip install --no-cache-dir rs_server_frontend-*.whl

# Final stage. Don't use alpine, it's too different from the build stage.
FROM python:3.11-slim-bookworm

# Copy the python installation from the build stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Clean everything
RUN rm -rf /tmp/whl /root/.cache/pip /var/cache/apt/archives /var/lib/apt/lists/*

# Add a default user
RUN useradd -m user
USER user
WORKDIR /home/user

# Set env var to the aggregated openapi.json released in the .whl package
ENV RSPY_OPENAPI_FILE=/usr/local/lib/python3.11/site-packages/resources/openapi.json

ENTRYPOINT [ "python", "-m", "uvicorn", "--factory", "rs_server_frontend.main:start_app", "--host", "0.0.0.0", "--port", "8000" ]
