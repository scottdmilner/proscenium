// Error translation for the core's Python entry points.
//
// Every entry point that can post a Tf error opens a TfErrorMark before doing any work and calls
// RaiseTfErrors(mark) before returning, so a Tf error posted inside it raises pxr.Tf.ErrorException. C++ exceptions
// that escape an entry point become Python exceptions through pxr_boost::python's own translation:
// std::invalid_argument is ValueError, std::out_of_range is IndexError, std::bad_alloc is MemoryError, and any other
// std::exception is RuntimeError.
#pragma once

#include <pxr/base/tf/errorMark.h>
#include <pxr/pxr.h>

namespace proscenium {

// Raises the Tf errors posted since mark as a Python exception, clearing them; does nothing if there are none.
void RaiseTfErrors(const PXR_NS::TfErrorMark& mark);

}  // namespace proscenium
