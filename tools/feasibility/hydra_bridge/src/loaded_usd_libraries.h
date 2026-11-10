// Which USD images the process has loaded, for the exactly-one-USD checks.
#pragma once

#include <string>
#include <vector>

namespace hydra_bridge {

// Every loaded image named like a USD library.
std::vector<std::string> LoadedUsdLibraries();

// The image that provides USD imaging code to this module, as the loader bound it.
std::string UsdProvidingLibrary();

}  // namespace hydra_bridge
