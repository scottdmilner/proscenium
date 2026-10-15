// Phase E only: time the source-info filter spends reading USD, summed over the threads that build facts, and
// how planning's time splits.
#pragma once

#include <chrono>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace hydra_bridge {

enum class FactTiming {
    Build,
    Bindings,
    StrongPurposes,
    FamilyVerdict,
    DroppedAttributes,
    ComputedExtent,
    // Planning: the whole run after reading, reading the records (parallel), and the serial work per prim.
    // BuildMesh's parts are nested in PlanBuildMesh; AddObjects includes its diagnostics and materials.
    PlanRun,
    PlanRead,
    PlanBuildMesh,
    PlanObjects,
    MeshValidate,
    MeshUsdValidate,  // nested in MeshValidate: PxOsdMeshTopology::Validate alone
    MeshDeletedFaces,
    MeshLayout,
    MeshSlots,
    MeshPrimvars,
    Count
};

// Adds one timed call of `kind`; threadsafe.
void AddFactTiming(FactTiming kind, std::chrono::steady_clock::duration elapsed);

// (name, calls, seconds) for each kind since the last reset, then resets them.
std::vector<std::tuple<std::string, uint64_t, double>> TakeFactTimings();

// Times its scope as one call of `kind`.
class ScopedFactTiming {
public:
    explicit ScopedFactTiming(FactTiming kind) : kind_(kind), start_(std::chrono::steady_clock::now()) {}
    ~ScopedFactTiming() { AddFactTiming(kind_, std::chrono::steady_clock::now() - start_); }
    ScopedFactTiming(const ScopedFactTiming &) = delete;
    ScopedFactTiming &operator=(const ScopedFactTiming &) = delete;

private:
    FactTiming kind_;
    std::chrono::steady_clock::time_point start_;
};

}  // namespace hydra_bridge
