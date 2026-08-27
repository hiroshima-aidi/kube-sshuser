using Pkg

Pkg.add(PackageSpec(url="https://github.com/JuliaReliab/ZeroOrigin.jl.git"))
Pkg.add(PackageSpec(url="https://github.com/JuliaReliab/DEQuadrature.jl.git"))
Pkg.add(PackageSpec(url="https://github.com/JuliaReliab/NMarkov.jl.git"))
Pkg.add(url="https://github.com/JuliaReliab/PhaseTypeDistributions.jl")

Pkg.precompile()

println("Reliability lab Julia packages installation completed")