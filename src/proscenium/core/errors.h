// Error translation for the core's Python entry points.
//
// Every entry point that can post a Tf error runs its work through Guarded, so a Tf error posted inside it raises
// pxr.Tf.ErrorException. C++ exceptions that escape an entry point become Python exceptions through
// pxr_boost::python's own translation: std::invalid_argument is ValueError, std::out_of_range is IndexError,
// std::bad_alloc is MemoryError, and any other std::exception is RuntimeError.
#pragma once

#include <pxr/base/tf/errorMark.h>
#include <pxr/pxr.h>

#include <exception>
#include <type_traits>

namespace proscenium {

// Raises the Tf errors posted since mark as a Python exception, clearing them; does nothing if there are none.
void RaiseTfErrors(const PXR_NS::TfErrorMark& mark);

// Raises the Tf errors posted since mark, which has some, with error as one more.
[[noreturn]] void RaiseTfErrorsWith(const PXR_NS::TfErrorMark& mark, const std::exception& error);

// Runs body as an entry point's work and returns what it returns. Tf errors it posts raise pxr.Tf.ErrorException. A
// C++ exception it throws after posting them joins them as one more error, since the last mark would otherwise
// report them only through the diagnostic delegate, out of Python's reach; one thrown with none posted propagates.
template <class Body>
auto Guarded(const Body& body) -> std::invoke_result_t<const Body&> {
  const PXR_NS::TfErrorMark mark;
  try {
    if constexpr (std::is_void_v<std::invoke_result_t<const Body&>>) {
      body();
      RaiseTfErrors(mark);
    } else {
      auto result = body();
      RaiseTfErrors(mark);
      return result;
    }
  } catch (const std::exception& error) {
    if (mark.IsClean()) throw;
    RaiseTfErrorsWith(mark, error);
  }
}

}  // namespace proscenium
