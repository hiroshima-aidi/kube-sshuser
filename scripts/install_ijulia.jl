# Requirements:
#   - Run as a non-root user (e.g. jovyan)
#   - JULIA_DEPOT_PATH is writable by the runtime user

import Pkg

# Prevent IJulia build from creating the default --project=@. kernel.
ENV["IJULIA_NODEFAULTKERNEL"] = "1"

Pkg.update()
Pkg.add([
    "BenchmarkTools",
    "CSV",
    "DataFrames",
    "Distributions",
    "IJulia",
    "JLD2",
    "JSON3",
    "Optim",
    "OrdinaryDiffEq",
    "Plots",
    "ProgressMeter",
    "Revise",
    "Roots",
])
Pkg.precompile()

using IJulia

# Make the notebook kernel use the global Julia environment (@vX.Y)
# so preinstalled packages can be imported without local project setup.
const julia_env = "@v$(VERSION.major).$(VERSION.minor)"
IJulia.installkernel("Julia", "--project=$(julia_env)")

println("IJulia kernel installation completed")