#include "snapshot.h"

#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/instancedBySchema.h>
#include <pxr/imaging/hd/instancerTopologySchema.h>
#include <pxr/imaging/hd/primOriginSchema.h>
#include <pxr/imaging/hd/purposeSchema.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/visibilitySchema.h>
#include <pxr/imaging/hd/xformSchema.h>

#include "source_facts.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

const TfTokenVector& PlannedSchemas() {
  static const TfTokenVector schemas{HdXformSchema::GetSchemaToken(),
                                     HdExtentSchema::GetSchemaToken(),
                                     HdPrimOriginSchema::GetSchemaToken(),
                                     HdInstancedBySchema::GetSchemaToken(),
                                     HdInstancerTopologySchema::GetSchemaToken(),
                                     HdVisibilitySchema::GetSchemaToken(),
                                     HdPurposeSchema::GetSchemaToken(),
                                     SourceInfoTokens::Schema()};
  return schemas;
}

const TfTokenVector& PlannedPrimvars() {
  static const TfTokenVector primvars{HdInstancerTokens->instanceTransforms};
  return primvars;
}

}  // namespace proscenium
