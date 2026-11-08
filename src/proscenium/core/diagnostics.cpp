#include "diagnostics.h"

#include <stdexcept>

namespace proscenium {

const char* DiagnosticCodeName(DiagnosticCode code) {
  switch (code) {
    case DiagnosticCode::kProjectiveTransform:
      return "projective-transform";
    case DiagnosticCode::kUnsupportedInstancing:
      return "unsupported-instancing";
    case DiagnosticCode::kInvalidInstancer:
      return "invalid-instancer";
  }
  throw std::invalid_argument("Not a diagnostic code");
}

}  // namespace proscenium
