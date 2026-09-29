#pragma once

#include <filesystem>
#include <map>
#include <string>
#include <string_view>

// Remembers the indicator's horizontal position per output, as a fraction of
// that output's width, so it survives restarts. No GTK here.
namespace flowd {

// The on-disk format version; any other version reads as empty defaults.
constexpr int kPositionFileVersion = 1;
// design.md "Indicator placement": the stored fraction is in [0, 1].
constexpr double kMinFraction = 0.0;
constexpr double kMaxFraction = 1.0;

class PositionStore {
public:
    // Loads file now. A missing, corrupt or foreign file reads as defaults.
    explicit PositionStore(std::filesystem::path file);

    // The saved fraction for output, or kDefaultFraction (0.5) when unknown.
    double get(std::string_view output) const;

    // Clamps fraction to [0, 1], keeps it in memory, then writes the whole
    // file atomically. Returns false on any I/O failure; never throws.
    bool set(std::string_view output, double fraction);

private:
    bool save() const;

    std::filesystem::path file_;
    std::map<std::string, double, std::less<>> fractions_;
};

// $XDG_STATE_HOME/flowd/indicator.json, falling back to
// $HOME/.local/state/flowd/indicator.json. Empty when neither is usable.
std::filesystem::path default_position_file();

}  // namespace flowd
