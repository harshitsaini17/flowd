#include "position_store.hpp"

#include <fcntl.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <nlohmann/json.hpp>
#include <system_error>

#include "placement.hpp"

using json = nlohmann::json;

namespace flowd {

namespace {

// XDG Base Directory spec: the default for $XDG_STATE_HOME.
constexpr const char* kStateFallback = ".local/state";
constexpr const char* kAppDir = "flowd";
constexpr const char* kFileName = "indicator.json";
// A plain user file; the umask narrows it further.
constexpr mode_t kFileMode = 0644;

bool in_range(double f) { return f >= kMinFraction && f <= kMaxFraction; }

// Writes all of text to fd, retrying short writes and EINTR.
bool write_all(int fd, const std::string& text) {
    const char* p = text.data();
    std::size_t left = text.size();
    while (left > 0) {
        const ssize_t n = ::write(fd, p, left);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        p += n;
        left -= static_cast<std::size_t>(n);
    }
    return true;
}

}  // namespace

PositionStore::PositionStore(std::filesystem::path file) : file_(std::move(file)) {
    if (file_.empty()) return;
    // ifstream does not throw by default; a missing file just reads as defaults.
    std::ifstream in(file_, std::ios::binary);
    if (!in) return;
    const std::string text{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};

    const json doc = json::parse(text, nullptr, false);
    if (doc.is_discarded() || !doc.is_object()) return;
    const auto version = doc.find("version");
    if (version == doc.end() || !version->is_number_integer() || *version != kPositionFileVersion) return;
    const auto outputs = doc.find("outputs");
    if (outputs == doc.end() || !outputs->is_object()) return;

    for (const auto& [name, value] : outputs->items()) {
        // Anything else was hand-edited or written by something else; skip it
        // rather than let it push the pill off-screen.
        if (!value.is_number()) continue;
        const double f = value.get<double>();
        if (in_range(f)) fractions_[name] = f;
    }
}

double PositionStore::get(std::string_view output) const {
    const auto it = fractions_.find(output);
    return it == fractions_.end() ? kDefaultFraction : it->second;
}

bool PositionStore::set(std::string_view output, double fraction) {
    // NaN would survive std::clamp and serialise as null, so treat it as centre.
    const double f = std::isnan(fraction) ? kDefaultFraction : std::clamp(fraction, kMinFraction, kMaxFraction);
    // In memory first, so this run keeps the position even if the disk refuses it.
    fractions_.insert_or_assign(std::string(output), f);
    return save();
}

bool PositionStore::save() const {
    if (file_.empty() || !file_.has_filename()) return false;

    std::error_code ec;
    const auto dir = file_.parent_path();
    if (!dir.empty()) {
        std::filesystem::create_directories(dir, ec);
        if (ec) return false;
    }

    json outputs = json::object();
    for (const auto& [name, f] : fractions_) outputs[name] = f;
    const json doc = {{"version", kPositionFileVersion}, {"outputs", outputs}};
    // Output names come from the compositor; replace invalid UTF-8 rather
    // than let dump() throw.
    const std::string text = doc.dump(-1, ' ', false, json::error_handler_t::replace) + "\n";

    // Same directory as the target, so rename() is atomic: a crash leaves
    // either the old file or the new one, never half of one.
    auto tmp = file_;
    tmp += ".tmp." + std::to_string(::getpid());

    const int fd = ::open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, kFileMode);
    if (fd < 0) return false;

    bool ok = write_all(fd, text) && ::fsync(fd) == 0;
    // close() can report a deferred write error, so it is checked too.
    if (::close(fd) != 0) ok = false;
    if (ok && ::rename(tmp.c_str(), file_.c_str()) != 0) ok = false;
    if (!ok) ::unlink(tmp.c_str());
    return ok;
}

std::filesystem::path default_position_file() {
    std::filesystem::path base;
    // XDG spec: a relative $XDG_STATE_HOME is invalid and must be ignored.
    const char* xdg = std::getenv("XDG_STATE_HOME");
    if (xdg && *xdg && std::filesystem::path(xdg).is_absolute()) {
        base = xdg;
    } else {
        const char* home = std::getenv("HOME");
        if (!home || !*home) return {};
        base = std::filesystem::path(home) / kStateFallback;
    }
    return base / kAppDir / kFileName;
}

}  // namespace flowd
