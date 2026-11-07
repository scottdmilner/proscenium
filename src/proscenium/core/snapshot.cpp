#include "snapshot.h"

#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/instancedBySchema.h>
#include <pxr/imaging/hd/primOriginSchema.h>
#include <pxr/imaging/hd/xformSchema.h>

#include "source_facts.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

const TfTokenVector& PlannedSchemas() {
  static const TfTokenVector schemas{HdXformSchema::GetSchemaToken(), HdExtentSchema::GetSchemaToken(),
                                     HdPrimOriginSchema::GetSchemaToken(), HdInstancedBySchema::GetSchemaToken(),
                                     SourceInfoTokens::Schema()};
  return schemas;
}

}  // namespace proscenium
