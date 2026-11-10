#include "diagnostics.h"

#include <map>
#include <set>
#include <stdexcept>
#include <string>
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
  for (const Diagnostic& diagnostic : to) seen.emplace(diagnostic.code, diagnostic.source, diagnostic.message);
  for (const Diagnostic& diagnostic : from)
    if (seen.emplace(diagnostic.code, diagnostic.source, diagnostic.message).second) to.push_back(diagnostic);
}

namespace {

// Words what `diagnostic` covers into its message.
void AppendDiagnosticContext(Diagnostic& diagnostic) {
  if (diagnostic.copies > 1)
    diagnostic.message +=
        " (for its " + std::to_string(diagnostic.copies) + " drawn copies; the first in source order is named)";
  if (!diagnostic.hydraPrim.IsEmpty()) diagnostic.message += " (Hydra prim " + diagnostic.hydraPrim.GetString() + ")";
}

}  // namespace

void SummarizeRepeatedDiagnostics(Diagnostics& diagnostics) {
  using Problem = std::tuple<DiagnosticCode, std::string, SdfPath, std::string, std::string>;
  std::map<Problem, std::size_t> reported;  // each problem's diagnostics, listed or not
  std::map<Problem, std::size_t> counting;  // the position of each problem's count, in summarized
  Diagnostics summarized;
  for (Diagnostic& diagnostic : diagnostics) {
    const Problem problem{diagnostic.code, diagnostic.message, diagnostic.property, diagnostic.asset,
                          diagnostic.fallback};
    const std::size_t before = reported[problem]++;
    if (before < kListedPerProblem) {
      AppendDiagnosticContext(diagnostic);
      summarized.push_back(std::move(diagnostic));
    } else if (before == kListedPerProblem) {
      counting.emplace(problem, summarized.size());
      summarized.push_back(
          {diagnostic.code, {}, diagnostic.message, diagnostic.property, diagnostic.asset, diagnostic.fallback, {}, 0});
    }
  }
  for (const auto& [problem, position] : counting)
    summarized[position].message +=
        " (and " + std::to_string(reported[problem] - kListedPerProblem) + " more with the same problem, not listed)";
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
