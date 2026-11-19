#include "node_ids.h"

// <cstdint> comes first, kept there against clang-format's sorting, since Blender's OpenUSD unicodeUtils.h names
// uint32_t without including it, and Linux's standard library doesn't bring it in through the headers before it.
// clang-format off
#include <cstdint>
// clang-format on

#include <pxr/base/tf/unicodeUtils.h>
#include <pxr/usd/sdf/path.h>

#include <array>
#include <charconv>
#include <cstddef>
#include <iterator>
#include <sstream>
#include <string_view>
#include <system_error>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

constexpr char kEscape = '_';

// The most hex digits an escape has: the highest code point, 10ffff, has six.
constexpr std::size_t kMaxEscapeDigits = 6;

std::string Utf8(TfUtf8CodePoint codePoint) {
  std::ostringstream out;
  out << codePoint;
  return out.str();
}

// Whether USD's identifiers accept the character here: alone at the start, or after a letter elsewhere. An identifier
// is XID_Start or `_`, then XID_Continue ("Unicode in USD", openusd.org/release/api/_usd__page__u_t_f_8.html). Asking
// SdfPath::IsValidIdentifier rather than Tf's XID functions keeps the escaping in step with what USD accepts in this
// process, should UTF-8 identifiers be turned off there.
bool IdentifierAccepts(const std::string& character, bool atStart) {
  return SdfPath::IsValidIdentifier(atStart ? character : "a" + character);
}

// The escape for a character identifiers reject: `_`, its code point in lowercase hex, `_`.
std::string Escape(TfUtf8CodePoint codePoint) {
  std::array<char, kMaxEscapeDigits> digits{};
  // Never fails: every code point fits in six hex digits.
  const auto written = std::to_chars(digits.data(), std::next(digits.data(), digits.size()), codePoint.AsUInt32(), 16);
  std::string escape(1, kEscape);
  escape.append(digits.data(), written.ptr);
  escape += kEscape;
  return escape;
}

// Whether value is a code point TfUtf8CodePoint keeps rather than replaces: in range, and outside the surrogates.
bool IsCodePoint(std::uint32_t value) {
  return value <= TfUtf8CodePoint::MaximumValue &&
         (value < TfUtf8CodePoint::SurrogateRange.first || value > TfUtf8CodePoint::SurrogateRange.second);
}

}  // namespace

std::string PrimNameFromNodeId(const std::string& nodeId) {
  std::string primName;
  bool atStart = true;
  // Invalid UTF-8 decodes to U+FFFD, which escapes like any other rejected character.
  for (const TfUtf8CodePoint codePoint : TfUtf8CodePointView(nodeId)) {
    const std::string character = Utf8(codePoint);
    if (codePoint == TfUtf8CodePointFromAscii(kEscape)) {
      primName += "__";
    } else if (IdentifierAccepts(character, atStart)) {
      primName += character;
    } else {
      primName += Escape(codePoint);
    }
    atStart = false;
  }
  return primName;
}

std::optional<std::string> NodeIdFromPrimName(const std::string& primName) {
  const std::string_view name(primName);
  std::string nodeId;
  for (std::size_t i = 0; i < name.size();) {
    if (name[i] != kEscape) {
      nodeId += name[i];
      ++i;
    } else if (i + 1 < name.size() && name[i + 1] == kEscape) {
      nodeId += kEscape;
      i += 2;
    } else {
      const std::size_t end = name.find(kEscape, i + 1);
      if (end == std::string_view::npos) return std::nullopt;
      const std::string digits(name.substr(i + 1, end - i - 1));
      const char* const digitsEnd = std::next(digits.data(), static_cast<std::ptrdiff_t>(digits.size()));
      std::uint32_t value = 0;
      const auto parsed = std::from_chars(digits.data(), digitsEnd, value, 16);
      if (digits.empty() || parsed.ec != std::errc() || parsed.ptr != digitsEnd || !IsCodePoint(value)) {
        return std::nullopt;
      }
      nodeId += Utf8(TfUtf8CodePoint(value));
      i = end + 1;
    }
  }
  // Only the canonical spelling decodes, so each node has one prim name. This rejects an escape of a character that
  // needs none, uppercase hex digits, and leading zeros.
  if (PrimNameFromNodeId(nodeId) != primName) return std::nullopt;
  return nodeId;
}

}  // namespace proscenium
