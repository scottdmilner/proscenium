#include "python_error_translation.h"

#include <pxr/base/tf/diagnostic.h>
#include <pxr/base/tf/pyError.h>

#include <pxr/external/boost/python.hpp>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

void RaiseTfErrors(const TfErrorMark& mark) {
  if (!mark.IsClean() && TfPyConvertTfErrorsToPythonException(mark)) {
    pxr_boost::python::throw_error_already_set();
  }
}

void RaiseTfErrorsWith(const TfErrorMark& mark, const std::exception& error) {
  TF_RUNTIME_ERROR("%s", error.what());
  RaiseTfErrors(mark);
  throw;  // not reached: the mark has errors, so RaiseTfErrors raised them
}

}  // namespace proscenium
