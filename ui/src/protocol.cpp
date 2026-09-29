#include "protocol.hpp"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace flowd {

// Helper to safely extract a typed field; returns nullopt if missing or wrong type.
// Unknown types are ignored because both sides can add messages without breaking.
template <class T>
std::optional<T> field(const json& obj, const char* key) {
    if (!obj.contains(key)) {
        return std::nullopt;
    }
    const auto& v = obj[key];

    if constexpr (std::is_same_v<T, std::string>) {
        if (!v.is_string()) return std::nullopt;
        return v.get<std::string>();
    } else if constexpr (std::is_same_v<T, double>) {
        // Accept both int and double for numeric fields (e.g., "-20" must work as -20.0)
        if (!v.is_number()) return std::nullopt;
        return v.get<double>();
    } else if constexpr (std::is_same_v<T, int>) {
        if (!v.is_number_integer()) return std::nullopt;
        // nlohmann stores integers as int64_t or uint64_t; a value that doesn't
        // fit in an int (e.g. 99999999999) must be rejected, not truncated.
        if (v.is_number_unsigned()) {
            auto uv = v.get<std::uint64_t>();
            if (uv > static_cast<std::uint64_t>(std::numeric_limits<int>::max())) {
                return std::nullopt;
            }
            return static_cast<int>(uv);
        }
        auto iv = v.get<std::int64_t>();
        if (iv < static_cast<std::int64_t>(std::numeric_limits<int>::min()) ||
            iv > static_cast<std::int64_t>(std::numeric_limits<int>::max())) {
            return std::nullopt;
        }
        return static_cast<int>(iv);
    } else if constexpr (std::is_same_v<T, bool>) {
        if (!v.is_boolean()) return std::nullopt;
        return v.get<bool>();
    }
    return std::nullopt;
}

// Map state string names to UiState enum values.
constexpr std::array<std::pair<std::string_view, UiState>, 9> kStateMap{{
    {"idle", UiState::Idle},
    {"recording", UiState::Recording},
    {"finishing", UiState::Finishing},
    {"done", UiState::Done},
    {"fallback", UiState::Fallback},
    {"error", UiState::Error},
    {"cancelled", UiState::Cancelled},
    {"no_speech", UiState::NoSpeech},
    {"time_limit", UiState::TimeLimit},
}};

// Map theme string names to Theme enum values.
constexpr std::array<std::pair<std::string_view, Theme>, 3> kThemeMap{{
    {"system", Theme::System},
    {"light", Theme::Light},
    {"dark", Theme::Dark},
}};

static std::optional<UiState> parse_state(std::string_view name) {
    for (const auto& [key, state] : kStateMap) {
        if (key == name) return state;
    }
    return std::nullopt;
}

static std::optional<Theme> parse_theme(std::string_view name) {
    for (const auto& [key, theme] : kThemeMap) {
        if (key == name) return theme;
    }
    return std::nullopt;
}

std::optional<Message> parse_message(std::string_view line) {
    if (line.empty()) {
        return std::nullopt;
    }

    // Parse JSON, reject if invalid or discarded
    json obj = json::parse(line, nullptr, false);
    if (obj.is_discarded()) {
        return std::nullopt;
    }

    auto type = field<std::string>(obj, "type");
    if (!type) {
        return std::nullopt;
    }

    if (*type == "show") {
        return Message{Show{}};
    } else if (*type == "render") {
        auto polished = field<std::string>(obj, "polished");
        auto pending = field<std::string>(obj, "pending");
        auto live = field<std::string>(obj, "live");
        if (!polished || !pending || !live) {
            return std::nullopt;
        }
        return Message{Render{*polished, *pending, *live}};
    } else if (*type == "fade") {
        return Message{Fade{}};
    } else if (*type == "hide") {
        return Message{Hide{}};
    } else if (*type == "quit") {
        return Message{Quit{}};
    } else if (*type == "state") {
        auto state_str = field<std::string>(obj, "state");
        auto reason = field<std::string>(obj, "reason");
        if (!state_str || !reason) {
            return std::nullopt;
        }
        auto state = parse_state(*state_str);
        if (!state) {
            return std::nullopt;
        }
        return Message{StateMsg{*state, *reason}};
    } else if (*type == "level") {
        auto rms_db = field<double>(obj, "rms_db");
        auto peak_db = field<double>(obj, "peak_db");
        if (!rms_db || !peak_db) {
            return std::nullopt;
        }
        return Message{Level{*rms_db, *peak_db}};
    } else if (*type == "meta") {
        auto mode = field<std::string>(obj, "mode");
        auto app = field<std::string>(obj, "app");
        auto hotkey = field<std::string>(obj, "hotkey");
        if (!mode || !app || !hotkey) {
            return std::nullopt;
        }
        return Message{Meta{*mode, *app, *hotkey}};
    } else if (*type == "warn") {
        // reason can be null (clears the warning) or a string
        Warn w;
        if (obj.contains("reason") && !obj["reason"].is_null()) {
            auto reason = field<std::string>(obj, "reason");
            if (reason) {
                w.reason = *reason;
            }
        }
        auto blocking = field<bool>(obj, "blocking");
        if (blocking) {
            w.blocking = *blocking;
        }
        return Message{w};
    } else if (*type == "config") {
        if (!obj.contains("ui") || !obj["ui"].is_object()) {
            return std::nullopt;
        }
        const auto& ui_obj = obj["ui"];

        UiConfig ui;

        // Fill in provided values, keeping defaults for missing keys
        if (auto v = field<bool>(ui_obj, "indicator")) {
            ui.indicator = *v;
        }
        if (auto v = field<std::string>(ui_obj, "theme")) {
            auto theme = parse_theme(*v);
            if (theme) ui.theme = *theme;
        }
        if (auto v = field<int>(ui_obj, "max_lines")) {
            ui.max_lines = std::clamp(*v, kMaxLinesFloor, kMaxLinesCeiling);
        }
        if (auto v = field<int>(ui_obj, "fade_ms")) {
            ui.fade_ms = std::clamp(*v, kFadeMsFloor, kFadeMsCeiling);
        }
        if (auto v = field<bool>(ui_obj, "footer")) {
            ui.footer = *v;
        }
        if (auto v = field<int>(ui_obj, "max_session_s")) {
            ui.max_session_s = std::clamp(*v, kMaxSessionSFloor, kMaxSessionSCeiling);
        }
        if (auto v = field<std::string>(ui_obj, "hotkey_label")) {
            ui.hotkey_label = *v;
        }

        return Message{ConfigMsg{ui}};
    }

    // Unknown type
    return std::nullopt;
}

// dump() with error_handler_t::replace swaps invalid UTF-8 for U+FFFD instead
// of throwing type_error.316; these encoders run inside GTK callbacks and must
// never throw.
std::string encode_click() {
    json obj;
    obj["event"] = "click";
    return obj.dump(-1, ' ', false, json::error_handler_t::replace) + "\n";
}

std::string encode_moved(double x, std::string_view output) {
    json obj;
    obj["event"] = "moved";
    obj["output"] = output;
    obj["x"] = x;
    return obj.dump(-1, ' ', false, json::error_handler_t::replace) + "\n";
}

std::string encode_unsupported(std::string_view reason) {
    json obj;
    obj["event"] = "unsupported";
    obj["reason"] = reason;
    return obj.dump(-1, ' ', false, json::error_handler_t::replace) + "\n";
}

}  // namespace flowd
