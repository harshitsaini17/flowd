#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace flowd {

enum class UiState {
    Idle,
    Recording,
    Finishing,
    Done,
    Fallback,
    Error,
    Cancelled,
    NoSpeech,
    TimeLimit,
};

enum class Theme {
    System,
    Light,
    Dark,
};

constexpr int kMaxLinesCeiling = 12;

// Defaults below mirror the [ui] block in docs/spec.md 8.1, except
// kDefaultMaxSessionS, which mirrors [audio] max_session_s in the same section.
constexpr int kDefaultMaxLines = 4;
constexpr int kDefaultFadeMs = 1000;
constexpr int kDefaultMaxSessionS = 300;

// Sanity caps against a bad daemon message, not spec-derived: 10 s of fade
// and an hour of session.
constexpr int kFadeMsCeiling = 10000;
constexpr int kMaxSessionSCeiling = 3600;
constexpr int kMaxLinesFloor = 1;
// 0 means no hold: the popup fades at once.
constexpr int kFadeMsFloor = 0;
// A session needs at least a second to mean anything.
constexpr int kMaxSessionSFloor = 1;

struct UiConfig {
    bool indicator = true;
    Theme theme = Theme::System;
    int max_lines = kDefaultMaxLines;
    int fade_ms = kDefaultFadeMs;
    bool footer = true;
    int max_session_s = kDefaultMaxSessionS;
    std::string hotkey_label;
};

struct Show {};
struct Render {
    std::string polished;
    std::string pending;
    std::string live;
};
struct Fade {};
struct Hide {};
struct Quit {};

struct StateMsg {
    UiState state;
    std::string reason;
};

struct Level {
    double rms_db;
    double peak_db;
};

struct Meta {
    std::string mode;
    std::string app;
    std::string hotkey;
};

struct Warn {
    std::optional<std::string> reason;
    bool blocking = false;
};

struct ConfigMsg {
    UiConfig ui;
};

using Message = std::variant<Show, Render, Fade, Hide, Quit, StateMsg, Level, Meta, Warn, ConfigMsg>;

std::optional<Message> parse_message(std::string_view line);
std::string encode_click();
std::string encode_moved(double x, std::string_view output);
std::string encode_unsupported(std::string_view reason);

}  // namespace flowd
