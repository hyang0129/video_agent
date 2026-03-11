FROM mcr.microsoft.com/devcontainers/python:1-3.10-bullseye

# System dependencies
# Remove stale Yarn repo whose GPG key has expired (breaks apt-get update)
RUN rm -f /etc/apt/sources.list.d/yarn.list
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    export DEBIAN_FRONTEND=noninteractive \
    && apt-get update && apt-get -y install --no-install-recommends \
        ffmpeg \
        git \
        curl

# Pre-install Python dependencies for faster container startup
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
