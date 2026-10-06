# syntax=docker/dockerfile:1
# App and test image (RUN-001). Python 3.12 + PyTorch CUDA wheels; the NVIDIA driver
# comes from Docker Desktop (RUN-001.D3).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/hf \
    HF_HUB_OFFLINE=1

# exiftool for metadata stripping (R-SAN-2).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libimage-exiftool-perl \
 && rm -rf /var/lib/apt/lists/*

# R-RUN-5: the RTX 5080 (Blackwell, sm_120) needs a PyTorch build for CUDA >= 12.8.
ARG TORCH_VERSION=2.14.1
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu130
RUN pip install "torch==${TORCH_VERSION}" --index-url "${TORCH_INDEX}"

# git for the unit tests that exercise the git hooks in a throwaway repo (RUN-002.10.4).
# Placed after torch so adding it doesn't invalidate the multi-GB torch layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY classifier ./classifier
# Editable: in compose the repo is bind-mounted over /app, so code changes need no rebuild.
RUN pip install -e ".[dev]"

CMD ["classifier", "--help"]
