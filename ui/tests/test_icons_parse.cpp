#include <doctest/doctest.h>

#include <gtk/gtk.h>

#include <string>

#include "icons.hpp"

using namespace flowd;

TEST_CASE("icons: every Lucide path parses with gsk_path_parse") {
    for (int i = 0; i < int(Icon::Count_); ++i)
        for (auto& e : icon(Icon(i))) {
            GskPath* p = gsk_path_parse(std::string(e.path).c_str());
            CHECK_MESSAGE(p != nullptr, e.path);
            if (p) gsk_path_unref(p);
        }
}
