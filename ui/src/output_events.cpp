#include "output_events.hpp"

#include <nlohmann/json.hpp>

namespace flowd {

namespace {

using nlohmann::json;

constexpr std::string_view kHyprSep = ">>";
constexpr std::string_view kFocusedMon = "focusedmon";
constexpr std::string_view kFullscreen = "fullscreen";
constexpr std::string_view kWorkspace = "workspace";

// Parses without throwing: a bad line from the compositor is just ignored.
std::optional<json> parse(std::string_view text) {
    json j = json::parse(text, nullptr, /*allow_exceptions=*/false);
    if (j.is_discarded()) return std::nullopt;
    return j;
}

std::optional<std::string> string_at(const json& obj, const char* key) {
    if (!obj.is_object()) return std::nullopt;
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_string()) return std::nullopt;
    return it->get<std::string>();
}

}  // namespace

std::optional<OutputEvent> parse_hypr_line(std::string_view line) {
    if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
    const auto sep = line.find(kHyprSep);
    if (sep == std::string_view::npos) return std::nullopt;
    const std::string_view name = line.substr(0, sep);
    const std::string_view data = line.substr(sep + kHyprSep.size());

    if (name == kFocusedMon) {
        const std::string_view mon = data.substr(0, data.find(','));
        if (mon.empty()) return std::nullopt;
        return OutputEvent{std::string(mon), std::nullopt, true};
    }
    if (name == kWorkspace) return OutputEvent{std::nullopt, std::nullopt, true};
    if (name == kFullscreen) {
        if (data == "1") return OutputEvent{std::nullopt, true, false};
        if (data == "0") return OutputEvent{std::nullopt, false, false};
    }
    return std::nullopt;
}

std::optional<OutputEvent> parse_sway_event(std::string_view text) {
    const auto j = parse(text);
    if (!j || !j->is_object()) return std::nullopt;
    const auto change = string_at(*j, "change");
    if (!change) return std::nullopt;

    // Workspace events carry "current"; window events carry "container".
    if (const auto cur = j->find("current"); cur != j->end()) {
        if (*change != "focus") return std::nullopt;
        if (auto out = string_at(*cur, "output")) return OutputEvent{std::move(out), std::nullopt, false};
        return std::nullopt;
    }
    if (const auto con = j->find("container"); con != j->end()) {
        if (*change != "focus" && *change != "fullscreen_mode") return std::nullopt;
        if (!con->is_object()) return std::nullopt;
        const auto mode = con->find("fullscreen_mode");
        if (mode == con->end() || !mode->is_number_integer()) return std::nullopt;
        // 1 is fullscreen on its output, 2 global fullscreen; both cover it.
        return OutputEvent{std::nullopt, mode->get<int>() != 0, false};
    }
    return std::nullopt;
}

std::optional<std::string> focused_output_from_json(std::string_view text) {
    const auto j = parse(text);
    if (!j || !j->is_array()) return std::nullopt;
    for (const auto& mon : *j) {
        if (!mon.is_object()) continue;
        const auto f = mon.find("focused");
        if (f != mon.end() && f->is_boolean() && f->get<bool>()) return string_at(mon, "name");
    }
    return std::nullopt;
}

std::optional<bool> fullscreen_from_hypr_activewindow(std::string_view text) {
    const auto j = parse(text);
    if (!j || !j->is_object()) return std::nullopt;
    const auto f = j->find("fullscreen");
    if (f == j->end()) return std::nullopt;
    // Older releases report a bool, newer ones a mode number.
    if (f->is_boolean()) return f->get<bool>();
    if (f->is_number_integer()) return f->get<int>() != 0;
    return std::nullopt;
}

bool JsonObjectSplitter::step(char c) {
    if (depth_ == 0) {
        if (c != '{') return false;  // between objects: newlines, stray bytes
        depth_ = 1;
        in_string_ = escaped_ = false;
        buf_.assign(1, c);
        return false;
    }
    buf_.push_back(c);
    if (buf_.size() > kMaxJsonObject) {
        buf_.clear();
        depth_ = 0;
        return false;
    }
    if (in_string_) {
        if (escaped_)
            escaped_ = false;
        else if (c == '\\')
            escaped_ = true;
        else if (c == '"')
            in_string_ = false;
        return false;
    }
    if (c == '"')
        in_string_ = true;
    else if (c == '{' || c == '[')
        ++depth_;
    else if (c == '}' || c == ']')
        --depth_;
    return depth_ == 0;
}

}  // namespace flowd
