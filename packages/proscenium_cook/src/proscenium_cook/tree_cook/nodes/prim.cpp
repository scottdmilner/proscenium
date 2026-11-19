// Prim outputs a single prim path (docs/phase3/node-tree.md "Prim"). The shared checks have refused a Path that isn't
// absolute, or names a property or a variant, so the node can't run with one; the path is checked against a stage at
// the node that uses it.
#include <pxr/base/tf/token.h>

#include "nodes/node_types.h"
#include "nodes/prim_attributes.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

ValueOutputs ComputePrim(const ValueInputs& context) {
  const PrimInputs inputs = ReadPrimInputs(context.Inputs());
  if (inputs.path.IsEmpty()) {
    context.ReportError(DiagnosticCode::kMissingPath, "Path names no prim",
                        context.AttributePath(TfToken(PrimInputs::kPath)));
  }
  PrimOutputs outputs;
  outputs.prim = inputs.path;
  return WritePrimOutputs(outputs);
}

}  // namespace proscenium
