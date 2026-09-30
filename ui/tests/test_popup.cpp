#include <doctest/doctest.h>

#include <gtkmm/init.h>
#include <gtkmm/snapshot.h>

#include <cstdlib>
#include <filesystem>

#include "backend.hpp"
#include "fonts.hpp"
#include "popup.hpp"
#include "theme.hpp"

using namespace flowd;

namespace {

bool have_display() {
    if (!std::getenv("WAYLAND_DISPLAY") && !std::getenv("DISPLAY")) return false;
    if (!gtk_init_check()) return false;
    Gtk::init_gtkmm_internals();
    return true;
}

// Draws one frame into a throwaway snapshot and reports whether any node
// came out.
bool draws_something(Popup& p, double now) {
    GtkSnapshot* s = gtk_snapshot_new();
    p.draw_at(s, now);
    GskRenderNode* node = gtk_snapshot_free_to_node(s);
    const bool any = node != nullptr;
    if (node) gsk_render_node_unref(node);
    return any;
}

double now_s() { return static_cast<double>(g_get_monotonic_time()) / 1e6; }

}  // namespace

TEST_CASE("fonts: a missing directory registers nothing") {
    CHECK(register_fonts("/nonexistent/flowd-fonts") == 0);
}

TEST_CASE("fonts: the bundled directory is one that exists") {
    // The test binary has no fonts beside it, and the installed directory
    // may be absent: either way the answer is an existing directory or none.
    if (const auto dir = bundled_fonts_dir()) CHECK(std::filesystem::is_directory(*dir));
}

TEST_CASE("fonts: every bundled font registers") {
    if (!have_display()) {
        MESSAGE("no display; skipped");
        return;
    }
#if PANGO_VERSION_CHECK(1, 56, 0)
    int files = 0;
    for (const auto& e : std::filesystem::directory_iterator(FLOWD_TEST_FONTS_DIR))
        if (e.path().extension() == ".woff2") ++files;
    CHECK(files > 0);
    CHECK(register_fonts(FLOWD_TEST_FONTS_DIR) == files);
#endif
}

// Everything here runs off-screen: the popup is never shown on a backend
// that could map it.
TEST_CASE("popup: lays out, wraps, scrolls and draws without a compositor") {
    if (!have_display()) {
        MESSAGE("no display; skipped");
        return;
    }
    auto* p = new Popup(Backend::Unsupported, tokens(true, false), false);
    CHECK(p->why_not());
    UiConfig c;
    c.max_lines = 2;
    p->on_config(c);
    p->set_anchor_x(400);
    CHECK(p->model().phase() == PopupPhase::Hidden);
    CHECK_FALSE(draws_something(*p, now_s()));

    p->on_show_msg();
    CHECK(p->model().phase() == PopupPhase::Entering);
    CHECK(p->card().w >= kPopupMinW);
    CHECK(p->text_lines() == 1);
    // Entering: the first frame is still transparent, the last opaque.
    CHECK(draws_something(*p, now_s() + 1.0));

    p->on_render({"Short.", "", ""});
    const int one_line_h = p->card().h;

    std::string long_text;
    for (int i = 0; i < 60; ++i) long_text += "dictation ";
    p->on_render({long_text, "pending words", "live"});
    CHECK(p->text_lines() > 2);
    // Clipped to max_lines, however long the text.
    CHECK(p->card().h == one_line_h + kPopupLineH);
    CHECK(p->card().w <= kPopupMaxW);
    CHECK(draws_something(*p, now_s() + 1.0));

    // A status footer still draws with the footer turned off.
    c.footer = false;
    p->on_config(c);
    p->on_state({UiState::Finishing, ""});
    CHECK(p->model().footer_visible());
    CHECK(draws_something(*p, now_s() + 1.0));

    p->on_state({UiState::Cancelled, ""});
    CHECK(draws_something(*p, now_s() + 1.0));

    p->on_hide_msg();
    delete p;
}

TEST_CASE("popup: the card never shrinks within a session") {
    if (!have_display()) {
        MESSAGE("no display; skipped");
        return;
    }
    auto* p = new Popup(Backend::Unsupported, tokens(false, false), true);
    p->on_show_msg();
    p->on_render(
        {"a considerably longer sentence than the minimum card holds on one line", "", ""});
    const int wide = p->card().w;
    p->on_render({"short", "", ""});
    CHECK(p->card().w == wide);
    delete p;
}
