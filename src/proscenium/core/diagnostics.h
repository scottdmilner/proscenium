// The source-side diagnostics the core reports (pipeline.md "Diagnostics"). Each names its problem by a code from
// Python's DiagnosticCode list, which gives it its category and severity, so the core decides neither; Python builds
// the Diagnostic, adding the binding. Tf's own errors and warnings, posted while reading the source, become
// diagnostics too, as the bridge's do, never stderr.
#pragma once

#include <pxr/base/tf/diagnosticMgr.h>
#include <pxr/base/tf/errorMark.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace proscenium {

enum class DiagnosticCode : std::uint8_t {
  kProjectiveTransform,    // a world transform placed by its affine part (XFORM-05)
  kUnsupportedInstancing,  // instancing Hydra gives that the core doesn't translate
  kInvalidInstancer,       // instancing data that can't be resolved
  kUsdWarning,             // a Tf warning USD or Hydra posted while reading the source: mostly something declined
  kUsdError,               // a Tf error USD or Hydra posted while reading the source: content it couldn't read
  kUntranslatedType,       // a prim whose type the core doesn't translate, shown by a placeholder or marker
  kApproximatedGeometry,   // a filter's inexact conversion to a mesh, such as a sphere's (SNAP-16)
};

// Every code the core reports, which Python's list must hold.
inline constexpr std::array kDiagnosticCodes{DiagnosticCode::kProjectiveTransform,
                                             DiagnosticCode::kUnsupportedInstancing,
                                             DiagnosticCode::kInvalidInstancer,
                                             DiagnosticCode::kUsdWarning,
                                             DiagnosticCode::kUsdError,
                                             DiagnosticCode::kUntranslatedType,
                                             DiagnosticCode::kApproximatedGeometry};

// The code's name in Python's list.
const char* DiagnosticCodeName(DiagnosticCode code);

// One reported problem. The fields that don't apply to it are empty (DIAG-02).
struct Diagnostic {
  DiagnosticCode code;
  PXR_NS::SdfPath sourcePath;  // the source entity it concerns, as a composed-stage path; a Hydra path in a snapshot
  std::string message;
  PXR_NS::SdfPath propertyPath;     // the property it concerns
  std::string assetIdentifier;      // the asset it concerns, as authored
  std::string fallbackDescription;  // what is displayed in its place
  // What SummarizeRepeatedDiagnostics words into the message once planning is done:
  PXR_NS::SdfPath hydraPrimPath;   // the Hydra prim one with no source entity concerns; empty for none
  std::size_t drawnCopyCount = 0;  // the total drawn copies of its source covered; zero before source mapping
};

using Diagnostics = std::vector<Diagnostic>;

// Appends `from` to `to`, skipping exact repeats: Hydra may read a value more than once, posting the same warning each
// time (M1b Phase C log).
void AppendUniqueDiagnostics(const Diagnostics& from, Diagnostics& to);

// The most diagnostics one problem gets, each about its own prim, before a last one counts the rest (with the user):
// a problem repeated across thousands of prims, such as curves of one untranslated type, stays a short list.
inline constexpr std::size_t kListedPerProblem = 10;

// Finishes a plan's diagnostics in place. A problem, a diagnostic's code, message, property, asset, and fallback, keeps
// its first kListedPerProblem diagnostics in order; the rest give way to one more, where the first left out was, with
// no source, counting them. Each kept one's message then names its Hydra prim and counts its copies.
void SummarizeRepeatedDiagnostics(Diagnostics& diagnostics);

// Moves the Tf errors posted since `mark` into `out` as usd-error diagnostics about `source`, clearing them.
void HarvestErrors(const PXR_NS::TfErrorMark& mark, const PXR_NS::SdfPath& source, Diagnostics& out);

// Collects Tf warnings, and errors posted outside any TfErrorMark, from every thread while installed. ScopedSource
// attributes them to the prim the posting thread is reading; the rest have no source.
class TfDiagnosticCollector final : public PXR_NS::TfDiagnosticMgr::Delegate {
 public:
  TfDiagnosticCollector();
  ~TfDiagnosticCollector() override;
  TfDiagnosticCollector(const TfDiagnosticCollector&) = delete;
  TfDiagnosticCollector& operator=(const TfDiagnosticCollector&) = delete;
  TfDiagnosticCollector(TfDiagnosticCollector&&) = delete;
  TfDiagnosticCollector& operator=(TfDiagnosticCollector&&) = delete;

  void IssueError(const PXR_NS::TfError& error) override;
  void IssueFatalError(const PXR_NS::TfCallContext& context, const std::string& message) override;
  void IssueStatus(const PXR_NS::TfStatus& status) override;
  void IssueWarning(const PXR_NS::TfWarning& warning) override;

  // What it has collected, in the order posted, which it then forgets.
  Diagnostics TakeDiagnostics();

  // Attributes what the current thread posts, while it lives, to `source`, which must outlive it.
  class ScopedSource {
   public:
    explicit ScopedSource(const PXR_NS::SdfPath& source);
    ~ScopedSource();
    ScopedSource(const ScopedSource&) = delete;
    ScopedSource& operator=(const ScopedSource&) = delete;
    ScopedSource(ScopedSource&&) = delete;
    ScopedSource& operator=(ScopedSource&&) = delete;

   private:
    const PXR_NS::SdfPath* previous_;  // the source the thread read before this scope; null for none
  };

 private:
  void Add(DiagnosticCode code, const std::string& message);

  std::mutex mutex_;
  Diagnostics diagnostics_;  // guarded by mutex_
};

}  // namespace proscenium
