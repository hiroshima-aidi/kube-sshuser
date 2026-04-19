# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repo produces Docker images for a lab-standard Jupyter stack. There are three standard base images (CPU, CUDA 11.8, CUDA 12.2) and two flavor images (cv, dl) that layer on top of a standard image.

## Common commands

```bash
# Build locally
make build STACK=cpu WITH_IJULIA=1
make build STACK=cuda12.2 WITH_IJULIA=1

# Build with buildx (multiarch, load to local Docker)
make buildx STACK=cuda12.2

# Push single image to ghcr.io
make push STACK=cuda12.2 IMAGE_TAG=2026.04

# Push all standard images (cpu, cuda12.2, cuda11.8 with IJulia)
make push-all

# Build a flavor image on top of a local standard image
make build-flavor STACK=cuda12.2 FLAVOR=cv

# Push flavor images
make push-flavor STACK=cpu FLAVOR=dl IMAGE_TAG=2026.04
make push-flavor-all

# Run locally
make run  # uses LOCAL_IMAGE (e.g. jupyter-gpu:cuda12.2-ijulia)

# Clean buildx cache
make clean
```

Credentials for `push` targets come from `GITHUB_USER` and `GITHUB_TOKEN`, which can be placed in a `.env` file at the repo root (auto-loaded by the Makefile).

## Image architecture

### Build layers

```
standard image  (docker/cpu/ or docker/gpu/)
    └── flavor image (docker/flavors/)
```

Standard images are standalone; flavor images use `ARG BASE_IMAGE` and must be built on top of a standard image. For `push-flavor`, `BASE_IMAGE` is set to the already-pushed `PUSH_IMAGE` (registry tag), not the local tag.

### Python requirements split

- `requirements/python/common.txt` — installed in all images (JupyterLab, numpy, pandas, etc.)
- `requirements/python/cpu.txt` — CPU-only extras
- `requirements/python/gpu.txt` — GPU-specific extras (PyTorch for CUDA is installed inline in the GPU Dockerfiles with the CUDA index URL, not via this file)

### Julia setup

- Julia binary version is controlled by `ARG JULIA_VERSION` (default `1.10.11`) in each standard Dockerfile.
- `scripts/install_ijulia.jl` runs as user `jovyan` (UID 1000) and installs the IJulia kernel pointing at the global `@vX.Y` environment so notebooks can import preinstalled packages without a local project.
- `scripts/install_reliab_julia_packages.jl` installs reliability-lab packages from GitHub; it runs in the flavor Dockerfiles.
- `WITH_IJULIA=0` skips the Julia kernel install but Julia itself is always installed.

### Tag format

```
ghcr.io/<IMAGE_ORGANIZATION>/<IMAGE_NAME>:<STACK>[-ijulia]-<IMAGE_TAG>
# e.g. ghcr.io/rellab/jupyter-gpu:cuda12.2-ijulia-2026.04
```

## Smoke test

Run `scripts/smoke_test.sh` inside the container to verify Python scientific stack, Jupyter, Julia, and IJulia/Plots imports all work.
