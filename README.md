# jupyter-gpu

Lab-standard Jupyter stack with CPU baseline, optional CUDA variants, and IJulia support.

## Why this layout

- CPU image is the common baseline for classes and shared notebooks.
- CUDA images are derived variants for GPU servers.
- IJulia can be enabled or disabled with a build argument.

## Directory layout

```text
.
├── docker
│   ├── cpu
│   │   └── Dockerfile.cpu-standard
│   ├── gpu
│   │   ├── Dockerfile.cuda11.8-standard
│   │   └── Dockerfile.cuda12.2-standard
│   └── flavors
│       ├── Dockerfile.cv
│       └── Dockerfile.dl
├── requirements
│   ├── julia
│   │   └── Project.toml
│   └── python
│       ├── common.txt
│       ├── cpu.txt
│       └── gpu.txt
├── scripts
│   ├── install_ijulia.jl
│   └── smoke_test.sh
├── Makefile
└── README.md
```

## Build examples

Build CPU standard image with IJulia enabled:

```bash
make build STACK=cpu WITH_IJULIA=1
```

Build CUDA 12.2 standard image:

```bash
make build STACK=cuda12.2 WITH_IJULIA=1
```

Build CUDA 11.8 standard image without IJulia:

```bash
make build STACK=cuda11.8 WITH_IJULIA=0
```

Push all standard images:

```bash
make push-all
```

## Tags

The default pushed tag format is:

```text
<registry>/<organization>/<image>:<stack><-ijulia>-<image_tag>
```

Example:

```text
ghcr.io/rellab/jupyter-gpu:cuda12.2-ijulia-2026.04.01
```

## Notes

- GPU images use NVIDIA official base images.
- Use explicit version tags in production.
- For strict Julia reproducibility, generate and commit a pinned `requirements/julia/Manifest.toml`.
