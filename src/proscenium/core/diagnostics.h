// The source-side diagnostics the core reports (pipeline.md "Diagnostics"). Each names its problem by a code from
// Python's DiagnosticCode list, which gives it its category and severity, so the core decides neither; Python builds
// the Diagnostic, adding the binding.
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <array>
#include <cstdint>
#include <string>

namespace proscenium {

enum class DiagnosticCode : std::uint8_t {
  kProjectiveTransform,    // a world transform placed by its affine part (XFORM-05)
  kUnsupportedInstancing,  // instancing Hydra gives that the core doesn't translate
  kInvalidInstancer,       // instancing data that can't be resolved
};

// Every code the core reports, which Python's list must hold.
constexpr std::array kDiagnosticCodes{DiagnosticCode::kProjectiveTransform, DiagnosticCode::kUnsupportedInstancing,
                                      DiagnosticCode::kInvalidInstancer};

// The code's name in Python's list.
const char* DiagnosticCodeName(DiagnosticCode code);

// One reported problem. The fields that don't apply to it are empty (DIAG-02).
struct Diagnostic {
  DiagnosticCode code;
  PXR_NS::SdfPath source;  // the source entity it concerns, as a composed-stage path
  std::string message;
  PXR_NS::SdfPath property;  // the property it concerns
  std::string asset;         // the asset it concerns, as authored
  std::string fallback;      // what is displayed in its place
};

}  // namespace proscenium
