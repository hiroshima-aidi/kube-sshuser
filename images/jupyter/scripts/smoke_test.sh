#!/usr/bin/env bash
set -euo pipefail

echo "[smoke-test] Python version"
python3 --version

echo "[smoke-test] Jupyter version"
jupyter --version

echo "[smoke-test] Julia version"
julia --version

echo "[smoke-test] Python imports"
python3 - <<'PY'
import numpy
import pandas
import matplotlib
import scipy
print("Python scientific stack OK")
PY

echo "[smoke-test] Julia + IJulia"
JULIA_ENV="@v$(julia -e 'print(VERSION.major, ".", VERSION.minor)')"
julia --project="${JULIA_ENV}" -e 'using IJulia; using Plots; println("IJulia + Plots OK")'

echo "[smoke-test] All checks passed"
