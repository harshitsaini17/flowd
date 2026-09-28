"""WCAG contrast checks for the flowd palette. Run: python3 contrast.py"""

import sys


def lum(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]

    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def cr(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def over(fg, a, bg):
    fg = fg.lstrip("#")
    bg = bg.lstrip("#")
    return "#" + "".join(
        f"{round(a * int(fg[i : i + 2], 16) + (1 - a) * int(bg[i : i + 2], 16)):02x}"
        for i in (0, 2, 4)
    )


# Mirrors assets/tokens.css. `brand` is violet (#b154f9): fills, rings and indicators only,
# checked at 3:1 (non-text). `primary` is the text-safe violet used for links and labels.
T = {
    "light": dict(
        bg="#ffffff",
        surface="#ffffff",
        raised="#ffffff",
        sunken="#f1f1f1",
        hover="#f6f6f6",
        borderS="#8a8989",
        text="#000000",
        text2="#6c6b6b",
        brand="#b154f9",
        primary="#9333ea",
        onPrimary="#ffffff",
        primarySoft="#f5edfe",
        live="#8b2fd9",
        record="#c42f2a",
        recordFill="#c42f2a",
        warn="#835500",
        warnSoft="#fbf0da",
        danger="#b8261f",
        dangerSoft="#fbe8e6",
    ),
    "dark": dict(
        bg="#111111",
        surface="#171717",
        raised="#1f1f1f",
        sunken="#0b0b0b",
        hover="#222222",
        borderS="#6e6d6d",
        text="#ffffff",
        text2="#a3a3a3",
        brand="#b154f9",
        primary="#c98bfb",
        onPrimary="#000000",
        primarySoft="#2a1840",
        live="#c98bfb",
        record="#ff6b66",
        recordFill="#d03b36",
        warn="#f2b34c",
        warnSoft="#2d2412",
        danger="#ff7470",
        dangerSoft="#341b1a",
    ),
}
GLASS = {"light": ("#ffffff", 0.94), "dark": ("#171717", 0.88)}
SURFACES = ["bg", "surface", "raised", "sunken", "hover"]
fails = []


def check(label, a, b, need):
    v = cr(a, b)
    if v < need:
        fails.append(f"{label} {v:.2f} < {need}")
    return v


for name, t in T.items():
    print("==", name)
    for k in ["text", "text2", "primary", "live", "record", "warn", "danger"]:
        row = [
            f"{b} {check(f'{name} {k}/{b}', t[k], t[b], 4.5):.2f}"
            for b in [*SURFACES, "primarySoft"]
        ]
        print(f"  {k:8}", "  ".join(row))
    # Non-text (3:1): violet fills/rings, input outlines, chart bars (border-strong), toggle track.
    for b in SURFACES:
        check(f"{name} brand/{b} (non-text)", t["brand"], t[b], 3.0)
        check(f"{name} borderS/{b} (non-text)", t["borderS"], t[b], 3.0)
    brand_min = round(min(cr(t["brand"], t[b]) for b in SURFACES), 2)
    borders_min = round(min(cr(t["borderS"], t[b]) for b in SURFACES), 2)
    print(f"  brand min (3:1) {brand_min}  borderS min (3:1) {borders_min}")
    on_primary = round(check(f"{name} onPrimary", t["onPrimary"], t["primary"], 4.5), 2)
    print(f"  onPrimary/primary {on_primary}")
    white_brand = round(check(f"{name} white/brand", "#ffffff", t["brand"], 3.0), 2)
    print(f"  white/brand (toggle thumb, 3:1) {white_brand}")
    white_record = round(check(f"{name} white/recordFill", "#ffffff", t["recordFill"], 3.0), 2)
    print(f"  white/recordFill (icon, 3:1) {white_record}")
    warn_soft = round(check(f"{name} warn/warnSoft", t["warn"], t["warnSoft"], 4.5), 2)
    danger_soft = round(check(f"{name} danger/dangerSoft", t["danger"], t["dangerSoft"], 4.5), 2)
    print(f"  warn/warnSoft {warn_soft}  danger/dangerSoft {danger_soft}")
    c, a = GLASS[name]
    for back in ["#ffffff", "#000000", "#808080", "#ff0000", "#0000ff", "#ffff00", "#00ff00"]:
        m = over(c, a, back)
        vals = {
            k: check(f"{name} glass {k} over {back}", t[k], m, 4.5 if k != "record" else 3.0)
            for k in ["text", "text2", "live", "record", "warn"]
        }
        print(f"  glass over {back} -> {m}", " ".join(f"{k} {v:.2f}" for k, v in vals.items()))

print("\nFAILS:" if fails else "\nALL PASS", *fails, sep="\n  ")
sys.exit(1 if fails else 0)
