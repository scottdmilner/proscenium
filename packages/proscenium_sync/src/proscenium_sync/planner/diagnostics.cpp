#include "diagnostics.h"

#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// The prim the current thread is reading; null when it reads none. Per-thread by design: the diagnostic delegate has
// no other way to know which prim a warning came from.
thread_local const SdfPath* currentSource = nullptr;  // NOLINT(cppcoreguidelines-avoid-non-const-global-variables)

}  // namespace

const char* DiagnosticCodeName(DiagnosticCode code) {
  switch (code) {
    case DiagnosticCode::kProjectiveTransform:
      return "projective-transform";
    case DiagnosticCode::kUnsupportedInstancing:
      return "unsupported-instancing";
    case DiagnosticCode::kInvalidInstancer:
      return "invalid-instancer";
    case DiagnosticCode::kUsdWarning:
      return "usd-warning";
    case DiagnosticCode::kUsdError:
      return "usd-error";
    case DiagnosticCode::kUntranslatedType:
      return "untranslated-type";
    case DiagnosticCode::kApproximatedGeometry:
      return "approximated-geometry";
  }
  throw std::invalid_argument("Not a diagnostic code");
}

void AppendUniqueDiagnostics(const Diagnostics& from, Diagnostics& to) {
  // As the bridge's UniqueAppender: the fields a captured diagnostic sets, the others being empty.
  using Key = std::tuple<DiagnosticCode, SdfPath, std::string>;
  std::set<Key> seen;
  for (const Diagnostic& diagnostic : to) seen.emplace(diagnostic.code, diagnostic.sourcePath, diagnostic.message);
  for (const Diagnostic& diagnostic : from)
    if (seen.emplace(diagnostic.code, diagnostic.sourcePath, diagnostic.message).second) to.push_back(diagnostic);
}

namespace {

// Words what `diagnostic` covers into its message.
void AppendDiagnosticContext(Diagnostic& diagnostic) {
  if (diagnostic.drawnCopyCount > 1)
    diagnostic.message +=
        " (for its " + std::to_string(diagnostic.drawnCopyCount) + " drawn copies; the first in source order is named)";
  if (!diagnostic.hydraPrimPath.IsEmpty())
    diagnostic.message += " (Hydra prim " + diagnostic.hydraPrimPath.GetString() + ")";
}

}  // namespace

void SummarizeRepeatedDiagnostics(Diagnostics& diagnostics) {
  if (diagnostics.empty()) return;

  struct ProblemReports {
    std::size_t first;
    std::size_t count = 0;
    std::vector<std::size_t> listedIndices;
  };
  std::vector<ProblemReports> groups;
  const auto sourceLess = [&diagnostics](std::size_t left, std::size_t right) {
    return std::tie(diagnostics[left].sourcePath, left) < std::tie(diagnostics[right].sourcePath, right);
  };
  {
    // Keys borrow the input's strings, so this map dies before any message is moved or given context.
    using Problem = std::tuple<DiagnosticCode, std::string_view, SdfPath, std::string_view, std::string_view>;
    std::map<Problem, std::size_t> groupIndices;
    for (std::size_t diagnosticIndex = 0; diagnosticIndex < diagnostics.size(); ++diagnosticIndex) {
      const Diagnostic& diagnostic = diagnostics[diagnosticIndex];
      const Problem problem{diagnostic.code, diagnostic.message, diagnostic.propertyPath, diagnostic.assetIdentifier,
                            diagnostic.fallbackDescription};
      const auto [found, inserted] = groupIndices.emplace(problem, groups.size());
      if (inserted) groups.push_back({diagnosticIndex, 0, {}});
      ProblemReports& group = groups[found->second];
      ++group.count;
      if (group.count == 1) continue;
      if (group.count == 2) {
        group.listedIndices.reserve(kListedPerProblem);
        group.listedIndices.push_back(group.first);
      }
      // The first kListedPerProblem in source order, whatever order Hydra reported them in.
      auto& listed = group.listedIndices;
      if (listed.size() == kListedPerProblem) {
        if (!sourceLess(diagnosticIndex, listed.back())) continue;
        listed.pop_back();
      }
      listed.insert(std::lower_bound(listed.begin(), listed.end(), diagnosticIndex, sourceLess), diagnosticIndex);
    }
  }

  Diagnostics summarized;
  for (const ProblemReports& group : groups) {
    if (group.count == 1) {
      AppendDiagnosticContext(diagnostics[group.first]);
      summarized.push_back(std::move(diagnostics[group.first]));
      continue;
    }
    // Copy the unadorned problem before moving any of its retained reports.
    Diagnostic count{};
    if (group.count > kListedPerProblem) {
      count = diagnostics[group.first];
      count.sourcePath = {};
      count.hydraPrimPath = {};
      count.drawnCopyCount = 0;
      count.message +=
          " (and " + std::to_string(group.count - kListedPerProblem) + " more with the same problem, not listed)";
    }
    for (const std::size_t diagnosticIndex : group.listedIndices) {
      AppendDiagnosticContext(diagnostics[diagnosticIndex]);
      summarized.push_back(std::move(diagnostics[diagnosticIndex]));
    }
    if (group.count > kListedPerProblem) summarized.push_back(std::move(count));
  }
  diagnostics = std::move(summarized);
}

void HarvestErrors(const TfErrorMark& mark, const SdfPath& source, Diagnostics& out) {
  for (const TfError& error : mark)
    out.push_back({DiagnosticCode::kUsdError, source, error.GetCommentary(), {}, {}, {}, {}, 0});
  mark.Clear();
}

TfDiagnosticCollector::TfDiagnosticCollector() { TfDiagnosticMgr::GetInstance().AddDelegate(this); }

TfDiagnosticCollector::~TfDiagnosticCollector() { TfDiagnosticMgr::GetInstance().RemoveDelegate(this); }

void TfDiagnosticCollector::IssueError(const TfError& error) { Add(DiagnosticCode::kUsdError, error.GetCommentary()); }

// A fatal error ends the process whatever a delegate does, so there is nothing to record it into.
void TfDiagnosticCollector::IssueFatalError(const TfCallContext&, const std::string&) {}

void TfDiagnosticCollector::IssueStatus(const TfStatus&) {}

void TfDiagnosticCollector::IssueWarning(const TfWarning& warning) {
  Add(DiagnosticCode::kUsdWarning, warning.GetCommentary());
}

Diagnostics TfDiagnosticCollector::TakeDiagnostics() {
  Diagnostics taken;
  const std::scoped_lock lock(mutex_);
  taken.swap(diagnostics_);
  return taken;
}

void TfDiagnosticCollector::Add(DiagnosticCode code, const std::string& message) {
  SdfPath source = currentSource ? *currentSource : SdfPath();
  const std::scoped_lock lock(mutex_);
  diagnostics_.push_back({code, std::move(source), message, {}, {}, {}, {}, 0});
}

TfDiagnosticCollector::ScopedSource::ScopedSource(const SdfPath& source) : previous_(currentSource) {
  currentSource = &source;
}

TfDiagnosticCollector::ScopedSource::~ScopedSource() { currentSource = previous_; }

}  // namespace proscenium
