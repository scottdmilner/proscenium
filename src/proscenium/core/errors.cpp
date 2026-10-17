#include "errors.h"

#include <pxr/base/tf/pyError.h>

#include <pxr/external/boost/python.hpp>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

void RaiseTfErrors(const TfErrorMark& mark) {
  if (!mark.IsClean() && TfPyConvertTfErrorsToPythonException(mark)) {
    pxr_boost::python::throw_error_already_set();
  }
}

}  // namespace proscenium
