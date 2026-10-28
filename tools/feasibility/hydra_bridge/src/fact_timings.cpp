#include "fact_timings.h"

#include <array>
#include <atomic>
#include <tuple>

namespace hydra_bridge {
namespace {

constexpr size_t kKinds = static_cast<size_t>(FactTiming::Count);
const std::array<const char *, kKinds> kNames = {
    "build",           "bindings",           "strong purposes",     "family verdict",   "dropped attributes",
    "computed extent", "plan: run",          "plan: read prims",    "plan: build mesh", "plan: objects",
    "mesh: validate",  "mesh: usd validate", "mesh: deleted faces", "mesh: layout",     "mesh: slots",
    "mesh: primvars",  "copy bindings"};

struct Counter {
    std::atomic<uint64_t> calls{0};
    std::atomic<int64_t> nanoseconds{0};
};
// Process-wide by design: every thread adds to the same counters, and TakeFactTimings drains them.
std::array<Counter, kKinds> counters;  // NOLINT(cppcoreguidelines-avoid-non-const-global-variables)

}  // namespace

void AddFactTiming(FactTiming kind, std::chrono::steady_clock::duration elapsed) {
    Counter &counter = counters[static_cast<size_t>(kind)];
    counter.calls.fetch_add(1, std::memory_order_relaxed);
    counter.nanoseconds.fetch_add(std::chrono::duration_cast<std::chrono::nanoseconds>(elapsed).count(),
                                  std::memory_order_relaxed);
}

std::vector<std::tuple<std::string, uint64_t, double>> TakeFactTimings() {
    std::vector<std::tuple<std::string, uint64_t, double>> result;
    result.reserve(kKinds);
    for (size_t i = 0; i < kKinds; ++i)
        result.emplace_back(kNames[i], counters[i].calls.exchange(0),
                            static_cast<double>(counters[i].nanoseconds.exchange(0)) * 1e-9);
    return result;
}

}  // namespace hydra_bridge
