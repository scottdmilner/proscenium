#include "diagnostics.h"

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

void AppendUnique(const Diagnostics& from, Diagnostics& to) {
  // As the bridge's UniqueAppender: the fields a captured diagnostic sets, the others being empty.
  using Key = std::tuple<DiagnosticCode, SdfPath, std::string>;
  std::set<Key> seen;
  for (const Diagnostic& diagnostic : to) seen.emplace(diagnostic.code, diagnostic.source, diagnostic.message);
  for (const Diagnostic& diagnostic : from)
    if (seen.emplace(diagnostic.code, diagnostic.source, diagnostic.message).second) to.push_back(diagnostic);
}

void HarvestErrors(const TfErrorMark& mark, const SdfPath& source, Diagnostics& out) {
  for (const TfError& error : mark)
    out.push_back({DiagnosticCode::kUsdError, source, error.GetCommentary(), {}, {}, {}});
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

Diagnostics TfDiagnosticCollector::Take() {
  Diagnostics taken;
  const std::scoped_lock lock(mutex_);
  taken.swap(diagnostics_);
  return taken;
}

void TfDiagnosticCollector::Add(DiagnosticCode code, const std::string& message) {
  SdfPath source = currentSource ? *currentSource : SdfPath();
  const std::scoped_lock lock(mutex_);
  diagnostics_.push_back({code, std::move(source), message, {}, {}, {}});
}

TfDiagnosticCollector::ScopedSource::ScopedSource(const SdfPath& source) : previous_(currentSource) {
  currentSource = &source;
}

TfDiagnosticCollector::ScopedSource::~ScopedSource() { currentSource = previous_; }

}  // namespace proscenium
