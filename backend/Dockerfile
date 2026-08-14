FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rmw-cyclonedds-cpp \
        python3-pip \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 22.04's system pip (22.0.2) silently mis-resolves PEP 621
# `[project]` metadata for an in-tree pyproject.toml build - every
# install succeeds but the package installs itself as a bogus
# "UNKNOWN-0.0.0" distribution with none of its actual source files,
# so `import multisens_sdk` 404s at container startup. Reproduced and
# confirmed directly (identical pyproject.toml installs correctly under
# a current pip on the host) - not a guess. Upgrading pip once, before
# installing anything else, fixes it completely.
RUN pip3 install --no-cache-dir --upgrade pip

# Build context is the repo root (see docker-compose.yml) specifically so
# this can reach the sibling sdk/ package - multisens_sdk is a real pip
# dependency, not vendored into backend/ (v0.9, Phase 93). Copied and
# installed before backend/requirements.txt so an unrelated backend
# dependency change doesn't invalidate this layer's cache. Not an
# editable (`-e`) install: PEP 660 editable-install support needs a
# newer setuptools than this image ships by default, and a plain
# install is all a Docker image build needs - local dev iteration
# against a live sdk/ checkout uses PYTHONPATH instead (see backend/tests'
# own docker run invocations).
COPY sdk /sdk
RUN pip3 install --no-cache-dir /sdk

WORKDIR /app
COPY backend/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY backend/app ./app

COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
