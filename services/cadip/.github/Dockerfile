
# Don't use alpine because it lacks the gcc compiler needed to pip install shapely.
FROM python:3.11-slim-bookworm

# The CI builds the wheel packages, downloads them into ./whl/, then builds this Dockerfile from ./whl/,
# so the .whl files are under ./*.whl
# We copy them into a /tmp directory that we can clean at the end.
RUN mkdir -p /tmp/whl
ADD ./*.whl /tmp/whl

# Update pip version
RUN pip install --no-cache-dir --upgrade pip

# Install the wheel packages in the right order (dependencies first).
# This also installs all the sub-dependencies e.g. fastapi ect ...
RUN cd /tmp/whl && pip install --no-cache-dir rs_server_common-*.whl rs_server-*.whl rs_server_cadip-*.whl

# Clean everything
RUN rm -rf /tmp/whl /root/.cache/pip

# Add a default user
RUN useradd -m user
USER user
WORKDIR /home/user
