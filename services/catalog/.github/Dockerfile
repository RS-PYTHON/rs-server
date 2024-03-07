
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
RUN cd /tmp/whl && pip install --no-cache-dir rs_server_common-*.whl rs_server_catalog-*.whl

# Final stage. Don't use alpine, it's too different from the build stage.
FROM python:3.11-slim-bookworm

# Install dependencies necessary for execution (e.g. libpq) not compilation (gcc)
RUN \
    apt update && \
    apt install -y libpq-dev && \
    rm -rf /var/cache/apt/archives /var/lib/apt/lists/*

# Copy the python installation from the build stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Clean everything
RUN rm -rf /tmp/whl /root/.cache/pip /var/cache/apt/archives /var/lib/apt/lists/*

# Add a default user
RUN useradd -m user
USER user
WORKDIR /home/user

# See: rs_server_catalog/main.py
# uvicorn.run(
#     "stac_fastapi.pgstac.app:app",
#     host=settings.app_host,
#     port=settings.app_port,
#     log_level="info",
#     reload=settings.reload,
#     root_path=os.getenv("UVICORN_ROOT_PATH", ""),
ENTRYPOINT [ "python", "-m", "rs_server_catalog.main" ]
