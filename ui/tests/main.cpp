// One translation unit owns doctest's main; every test_*.cpp only includes it.
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
