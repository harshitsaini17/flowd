---
version: alpha
name: flowd
description: >-
  Local, offline voice dictation for Linux. A near-monochrome black-on-white
  canvas, one weight of type, flat surfaces with hairline borders, and violet
  as the only chromatic voice. A recording red that
  only appears while the mic is open is the single functional exception.
colors:
  # Light theme is canonical; dark-* mirrors every role.
  primary: "#9333ea"            # violet, text-safe: links, active labels, focus ring, filled CTA
  brand: "#b154f9"              # violet: fills, rings, indicators, toggles (non-text, 3:1)
  on-primary: "#ffffff"
  primary-soft: "#f5edfe"       # selected nav item, hover wash on violet buttons
  bg: "#ffffff"                 # canvas
  surface: "#ffffff"            # cards, row groups, inputs
  sunken: "#f1f1f1"             # code blocks, tracks, alt surfaces
  hover: "#f6f6f6"
  border: "#e5e5e5"             # black at 10%: hairlines, card edges (decorative)
  border-strong: "#8a8989"      # input outlines, toggle-off track ring (3:1 non-text)
  text: "#000000"
  text-2: "#6c6b6b"             # helper text, pending words, bars
  live: "#8b2fd9"               # live partial words (italic)
  record: "#c42f2a"             # functional exception: mic open
  record-fill: "#c42f2a"
  warn: "#835500"
  warn-soft: "#fbf0da"
  danger: "#b8261f"
  danger-soft: "#fbe8e6"
  glass: "#ffffff"              # indicator/popup material @ 0.94 alpha
  charcoal: "#171717"           # idle indicator core, dark surfaces
  dark-primary: "#c98bfb"
  dark-brand: "#b154f9"
  dark-on-primary: "#000000"
  dark-primary-soft: "#2a1840"
  dark-bg: "#111111"
  dark-surface: "#171717"
  dark-raised: "#1f1f1f"
  dark-sunken: "#0b0b0b"
  dark-hover: "#222222"
  dark-border: "#2e2e2e"
  dark-border-strong: "#6e6d6d"
  dark-text: "#ffffff"
  dark-text-2: "#a3a3a3"
  dark-live: "#c98bfb"
  dark-record: "#ff6b66"
  dark-record-fill: "#d03b36"
  dark-warn: "#f2b34c"
  dark-warn-soft: "#2d2412"
  dark-danger: "#ff7470"
  dark-danger-soft: "#341b1a"
  dark-glass: "#171717"         # indicator/popup material @ 0.88 alpha
typography:
  # One weight (400). Hierarchy comes from size and tracking, never boldness.
  display:
    fontFamily: Inter
    fontSize: 80px
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  heading-lg:
    fontFamily: Inter
    fontSize: 64px
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  heading:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  heading-sm:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: 400
    lineHeight: 1.2
  subheading:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: 400
    lineHeight: 1.25
    letterSpacing: "0.01em"
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: "0.01em"
  body:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.375
    letterSpacing: "0.01em"
  small:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.43
    letterSpacing: "0.01em"
  label:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.23
    letterSpacing: "0.02em"
  popup-text:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 400
    lineHeight: 22px
  mono:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: 400
    lineHeight: 20px
rounded:
  xs: 4px
  md: 8px                       # buttons, inputs, cards, tabs, badges
  xl: 14px                      # large containers: row groups, panels, popup, menus
  hero: 30px                    # hero panels only: time-saved card, privacy statement, demo stage
  pill: 999px                   # indicator, toggles
spacing:
  "4": 4px
  "8": 8px
  "12": 12px
  "16": 16px
  "20": 20px
  "24": 24px
  "32": 32px
  "48": 48px
  "80": 80px
  "96": 96px
  "128": 128px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 10px 20px
    height: 40px
  button-primary-dark:
    backgroundColor: "{colors.dark-primary}"
    textColor: "{colors.dark-on-primary}"
  button-outline:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 10px 20px
    height: 40px
  button-outline-hover:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
  button-outline-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-primary}"
  link:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
  link-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-primary}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    height: 40px
    padding: 0 12px
  input-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
  input-outline:
    backgroundColor: "{colors.border-strong}"
  input-outline-dark:
    backgroundColor: "{colors.dark-border-strong}"
  settings-page:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
  settings-page-dark:
    backgroundColor: "{colors.dark-bg}"
    textColor: "{colors.dark-text}"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: 20px
  card-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
  row-group:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.xl}"
    padding: 20px 24px
  row-group-dark:
    backgroundColor: "{colors.dark-surface}"
  row-description:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-2}"
    typography: "{typography.small}"
  row-description-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text-2}"
  hero-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.display}"
    rounded: "{rounded.hero}"
    padding: 40px
  hero-panel-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
  alt-surface:
    backgroundColor: "{colors.sunken}"
    textColor: "{colors.text}"
  alt-surface-dark:
    backgroundColor: "{colors.dark-sunken}"
    textColor: "{colors.dark-text}"
  hover-wash:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.text}"
  hover-wash-dark:
    backgroundColor: "{colors.dark-hover}"
    textColor: "{colors.dark-text}"
  menu-dark:
    backgroundColor: "{colors.dark-raised}"
    textColor: "{colors.dark-text}"
    rounded: "{rounded.xl}"
  nav-item-active:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    height: 40px
  nav-item-active-dark:
    backgroundColor: "{colors.dark-primary-soft}"
    textColor: "{colors.dark-primary}"
  tab-active-ring:
    backgroundColor: "{colors.brand}"
    rounded: "{rounded.md}"
    height: 36px
  tab-active-ring-dark:
    backgroundColor: "{colors.dark-brand}"
  toggle-on:
    backgroundColor: "{colors.brand}"
    rounded: "{rounded.pill}"
    width: 44px
    height: 24px
  toggle-off-track:
    backgroundColor: "{colors.sunken}"
  toggle-off-track-dark:
    backgroundColor: "{colors.dark-sunken}"
  code-snippet:
    backgroundColor: "{colors.sunken}"
    textColor: "{colors.text}"
    typography: "{typography.mono}"
    rounded: "{rounded.md}"
    padding: 16px 24px
  code-snippet-dark:
    backgroundColor: "{colors.dark-sunken}"
    textColor: "{colors.dark-text}"
  badge-status:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: 24px
  badge-warn:
    backgroundColor: "{colors.warn-soft}"
    textColor: "{colors.warn}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
  badge-warn-dark:
    backgroundColor: "{colors.dark-warn-soft}"
    textColor: "{colors.dark-warn}"
  badge-danger:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
  badge-danger-dark:
    backgroundColor: "{colors.dark-danger-soft}"
    textColor: "{colors.dark-danger}"
  inline-error:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
    typography: "{typography.small}"
  inline-error-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-danger}"
  divider:
    backgroundColor: "{colors.border}"
  divider-dark:
    backgroundColor: "{colors.dark-border}"
  popup-card:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.text}"
    typography: "{typography.popup-text}"
    rounded: "{rounded.xl}"
    padding: 14px 18px
    width: 640px
  popup-card-dark:
    backgroundColor: "{colors.dark-glass}"
    textColor: "{colors.dark-text}"
  popup-pending:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.text-2}"
  popup-pending-dark:
    backgroundColor: "{colors.dark-glass}"
    textColor: "{colors.dark-text-2}"
  popup-live:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.live}"
  popup-live-dark:
    backgroundColor: "{colors.dark-glass}"
    textColor: "{colors.dark-live}"
  popup-recording-mark:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.record}"
  popup-recording-mark-dark:
    backgroundColor: "{colors.dark-glass}"
    textColor: "{colors.dark-record}"
  warning-marker:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.warn}"
  warning-marker-dark:
    backgroundColor: "{colors.dark-glass}"
    textColor: "{colors.dark-warn}"
  indicator-stop-glyph:
    backgroundColor: "{colors.record-fill}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.pill}"
  indicator-stop-glyph-dark:
    backgroundColor: "{colors.dark-record-fill}"
    textColor: "{colors.on-primary}"
  indicator-idle:
    backgroundColor: "{colors.charcoal}"
    rounded: "{rounded.pill}"
    width: 48px
    height: 8px
  indicator-expanded:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    width: 120px
    height: 36px
---

# flowd design

Status: accepted (2026-09-28) · Applies to `flowd-ui` (the C++ indicator and
popup, ADR 0013) and the settings page served by the daemon (ADR 0014).

Mockups (open directly in a browser; everything is local):

- [`mockups.html`](mockups.html): every indicator and popup state in both
  themes, over light, dark and worst-case wallpapers, with and without blur,
  plus a clickable end-to-end dictation.
- [`settings.html`](settings.html): the full settings page, working: auto-save,
  validation, keyboard reorder, tag input, tables, charts, theme switching,
  degraded-state simulators and a component state gallery.
- `assets/tokens.css` is the CSS form of the tokens below; `contrast.py`
  re-checks every color pair in this document.

## Overview

flowd is a tool you stop noticing. It sits at the bottom edge of the screen as
a thin, dim line. For the few seconds you're speaking it becomes the most
important thing on screen, then it gets out of the way.

**Visual language: quiet white with one violet spark.**

- a near-monochrome canvas where black text on white carries the interface;
- **one** chromatic voice, violet, for actions, links, focus and selection;
- **one weight** of type (400). Hierarchy is built from size (13 → 80 px) and
  tracking, never boldness, which gives a calm, editorial tone;
- **flat** surfaces. Elevation is a 1 px hairline or a light gray tint, not a
  drop shadow;
- consistent soft geometry: 8 px for controls and cards, 14 px for large
  containers, 30 px for hero panels only;
- generous whitespace and section rhythm from large type jumps, not colored
  bands;
- light **and** dark themes, following the system;
- no decorative illustration: an OSD and a settings page need none;
- violet is split into `brand` (#b154f9, fills and rings) and `primary`
  (#9333ea, text-safe), because #b154f9 is 3.8:1 on white and fails WCAG AA
  for text;
- functional state colors (recording red, amber warn, danger red) never
  decorate, and each is always paired with an icon or text.

**Three surfaces, one language.**

| Surface | Archetype | Governing rule |
| --- | --- | --- |
| Indicator | Monitor (ambient) | Ignorable when idle, unmistakable when recording |
| Preview popup | Monitor (live) | The words are the interface; chrome stays near zero |
| Settings page | Configure | Grouped rows, one decision per row, save is automatic and visible |

**Principles.**

1. **Violet means "you can act on this" or "this is selected."** Buttons,
   links, focus rings, the active tab, nav item and toggle. It never marks
   data or health. Status badges are neutral outlines with an icon; the
   chart's best day is the one exception, as a highlight of a single datum.
2. **Red means the mic is open, and only that.** The record hue never appears
   on the settings page except in the microphone test. Errors use a different
   red (`danger`) paired with an icon, never a recording look.
3. **Nothing speaks by color alone.** Every state has a shape, icon, or word as
   well as a hue (see "State encoding" in Components).
4. **Focus belongs to the user's app.** The indicator and popup are
   layer-shell surfaces with `keyboard-mode NONE` (ADR 0003). Nothing in this
   design needs keyboard input on those surfaces, and nothing may add it.
5. **Numbers people care about.** The overview leads with what flowd gave the
   user (time saved, words, where they dictate) in minutes and plain
   sentences, computed from `metrics.jsonl`, with the one assumption shown and
   editable. Engineering numbers (percentiles, fallback rate) stay accurate but
   live behind "Performance details".

**Where the indicator can't exist.** On GNOME Wayland (no `wlr-layer-shell`)
`flowd-ui` disables itself rather than risk stealing focus. The settings header
then shows a `warn` badge, "Preview unavailable on GNOME Wayland", linking to
the reason. Dictation still works, and the design never pretends otherwise.

## Colors

All pairs below were checked with the WCAG 2.x formula (script:
`docs/design/contrast.py`). The indicator and popup materials were also
composited over #fff, #000, #808080 and pure red, green, blue, and yellow as
worst-case wallpapers.

### Roles

| Role | Light | Dark | Use | Min. contrast (checked) |
| --- | --- | --- | --- | --- |
| `bg` | #ffffff | #111111 | Page canvas | — |
| `surface` | #ffffff | #171717 | Cards, row groups, inputs | — |
| `raised` | #ffffff | #1f1f1f | Menus, popovers, toasts | — |
| `sunken` | #f1f1f1 | #0b0b0b | Code blocks, tracks, alt surfaces | — |
| `hover` | #f6f6f6 | #222222 | Row hover | — |
| `border` | black 10% | white 10% | Hairlines, card edges (decorative) | n/a |
| `border-strong` | #8a8989 | #6e6d6d | Input outlines, toggle-off ring | 3.09 / 3.08 worst surface (≥ 3:1) |
| `text` | #000000 | #ffffff | Primary text | 18.6 / 15.9 worst surface |
| `text-2` | #6c6b6b | #a3a3a3 | Helper text, pending words, chart bars | 4.66 / 6.31 worst surface |
| `brand` | #b154f9 | #b154f9 | Toggle-on fill, active-tab ring, best-day bar, logo mark | 3.38 / 4.17 (non-text ≥ 3:1) |
| `primary` | #9333ea | #c98bfb | Links, filled/outlined buttons, active nav label, focus ring | 4.72 / 6.49 worst surface |
| `on-primary` | #ffffff | #000000 | Text on a filled violet button | 5.38 / 8.57 |
| `primary-soft` | #f5edfe | #2a1840 | Selected nav item, violet button hover wash | `primary` on it 4.72 / 6.58 |
| `live` | #8b2fd9 | #c98bfb | Live partial words (italic) | ≥ 5.02 / 5.16 on glass, worst wallpaper |
| `record` | #c42f2a | #ff6b66 | Recording ring, level bars | ≥ 4.65 / 4.54 on glass (3:1 needed) |
| `record-fill` | #c42f2a | #d03b36 | Disc behind the white stop glyph | white on it 5.55 / 4.82 |
| `warn` | #835500 | #f2b34c | Degraded-state marker, warnings | ≥ 5.40 / 6.82 on glass |
| `warn-soft` | #fbf0da | #2d2412 | Warning banner bg | `warn` on it 5.69 / 8.25 |
| `danger` | #b8261f | #ff7470 | Errors, destructive actions | 5.53 / 6.05 worst surface |
| `danger-soft` | #fbe8e6 | #341b1a | Error banner bg | `danger` on it 5.33 / 6.06 |
| `glass` | #ffffff @ 94% | #171717 @ 88% | Indicator + popup material | see below |

**Rules.**

- `brand` (#b154f9) is never used for text. Anything that has to be read in
  violet uses `primary`.
- Status badges are neutral: a hairline outline, black text and a state icon.
  Only warn and danger badges take a tinted fill, because those need to be seen.
- `border` is never the only thing marking a control's edge. Inputs and toggle
  tracks use `border-strong`.
- Success is `text` plus a check icon. There's no green, which keeps one accent
  and avoids red/green pairs.
- Dark mode is the Charcoal family: surfaces get lighter as they rise
  (`sunken` < `bg` < `surface` < `raised`), and violet is lifted to #c98bfb for
  text.

### Glass material (indicator, popup)

A flat tint over a compositor blur, never a gradient.

| Theme | Fill | Blur (if compositor provides) | Edge | Worst-case text contrast |
| --- | --- | --- | --- | --- |
| Light | `rgba(255,255,255,0.94)` | 24 px | 1 px black 10% inside + `shadow-float` | `text` 17.6, `text-2` 4.6, `live` 5.0 (over #000) |
| Dark | `rgba(23,23,23,0.88)` | 24 px | 1 px white 10% inside, 1 px black 50% outside | `text` 12.6, `text-2` 5.0, `live` 5.2 (over #fff) |

GTK can't blur what's behind a surface; only the compositor can. Layer-rule
syntax changes between compositor releases, so check these against your
version's documentation. The alphas
were chosen so contrast holds **with no blur at all**, so blur only improves
things. Recommended compositor rules, all opt-in:

```lua
-- Hyprland (Lua config, 0.53+): namespace set via Gtk4LayerShell.set_namespace()
hl.layer_rule({ match = { namespace = "^flowd-(indicator|popup)$" }, blur = true, ignore_alpha = 0.2, animation = "fade" })
```

```ini
# Hyprland (hyprlang config)
layerrule = blur true, match:namespace ^flowd-(indicator|popup)$
layerrule = ignore_alpha 0.2, match:namespace ^flowd-(indicator|popup)$
```

```ini
# Sway / SwayFX
layer_effects "flowd-popup" blur enable; corner_radius 14
```

KDE Plasma applies blur to layer surfaces that request it through
`org_kde_kwin_blur` when available. Without it the material still meets
contrast, just unblurred.

### High contrast

When `gtk-interface-contrast` = more (GTK) or `prefers-contrast: more` (web),
glass alpha goes to **1.0**, `border` is replaced by `border-strong`, `text-2`
by `text` for pending words (the pending state then relies on its underline),
and focus rings go to 3 px.

## Typography

**One weight.** Every text role is Inter at weight 400: headings, buttons,
labels, numbers, badges. `<b>`, `<strong>`, `th` and headings are reset to 400.
This is the main source of its calm. Hierarchy comes
from size, tracking and color (`text` vs `text-2`). There is no 500, 600 or 700
anywhere.

**Families.** Inter (variable, OFL 1.1), plus JetBrains Mono (variable, OFL 1.1) for snippets, key
names, config paths and app ids. The page uses the local `woff2` files under `docs/design/assets/fonts/` (Inter
normal + italic, 48 KB + 52 KB; JetBrains Mono, 40 KB). `flowd-ui` ships TTF
copies of the same fonts and registers them with Pango
(`pango_font_map_add_font_file`, Pango ≥ 1.56), falling back to the system
font if that fails.

```css
--font-sans: "Inter", "InterVariable", system-ui, "Cantarell", "Noto Sans", sans-serif;
--font-mono: "JetBrains Mono", ui-monospace, "Cascadia Code", "Source Code Pro", monospace;
```

Inter also gives true italics (needed for the live zone) and tabular figures
(`tnum`) for every changing number.

**Scale.** Jumps of (16 → 24 → 32 → 48 → 64 → 80), extended downward
for dense settings rows.

| Token | Size / line | Tracking | Use |
| --- | --- | --- | --- |
| `display` | 80 / 1.1 | −0.01em | The one hero number (time saved), fluid down to 48 |
| `heading-lg` | 64 / 1.1 | −0.01em | Mockup page titles |
| `heading` | 48 / 1.2 | −0.01em | Settings section titles ("Microphone") |
| `heading-sm` | 32 / 1.2 | 0 | Stat card values |
| `subheading` | 24 / 1.25 | +0.01em | Group titles ("Input"), panel titles, dialog titles, wordmark |
| `body-lg` | 18 / 1.3 | +0.01em | Section summaries, hero sublines |
| `body` | 16 / 1.375 | +0.01em | Row titles, inputs, buttons, table cells |
| `small` | 14 / 1.43 | +0.01em | Row descriptions, captions, helper text, sidebar footer |
| `label` | 13 / 1.23 | +0.02em | Badges, key hints; the floor |
| `popup-text` | 15 / 22 | 0 | All three popup zones |
| `mono` | 14 / 20 | 0 | Snippets, app ids, paths |

All changing numbers use `font-variant-numeric: tabular-nums`, so values don't
jitter as they update.

## Layout

**Spacing.** A 4 px base: 4, 8, 12, 16, 20, 24, 32, 48, 80, 96, 128.
Density is "comfortable": card padding 20–24, row padding 20 × 24, section gap
80.

### Indicator placement

- Layer: `OVERLAY`. Anchor: `LEFT | BOTTOM`, with the horizontal position set
  by the left margin (see Components → Indicator → Dragging). Exclusive zone:
  `0` (it never pushes windows up). Namespace `flowd-indicator`.
- Bottom margin **6 px** idle, measured from the output edge. The expanded
  pill grows **upward** from the same baseline, so the pointer never has to chase it.
- Hit area: the idle line is 8 px tall but its input region is a **120 × 20 px**
  invisible strip centered on it (`Gdk.Surface.set_input_region`). That makes
  it hoverable without pixel hunting while staying small visually. The surface
  itself is sized 144 × 54 (the 120 × 36 pill plus 12 px of shadow room on
  each side) so the expansion has room without a resize; it grows to 384 × 54
  only for the warning pill, and spans the output's full width only while a
  drag is in progress. Everything outside the input region is click-through.
- Horizontal position is stored as a fraction of output width (0–1, default
  0.5) in `$XDG_STATE_HOME/flowd/indicator.json`, so it survives resolution
  changes. One per output name.

### Popup placement

- Namespace `flowd-popup`, layer `OVERLAY`, anchor `LEFT | BOTTOM`, keyboard
  `NONE`, input region **empty** (fully click-through; it's read-only).
- The surface is `min(output_width, 688px)` wide (the widest 640 px card plus
  24 px of shadow room on each side) and a fixed height set by `max_lines`, so
  it never resizes mid-session; the card is drawn and animated inside it. Its
  left margin is placed around the widest card the indicator's centre could
  get, so a card growing during a session never moves the surface.
- Horizontally centered on the indicator's x, clamped so the card stays
  ≥ 16 px inside the output edges.
- Vertical gap: **10 px** between the pill's top edge (expanded, 36 px tall)
  and the card's bottom edge, so the card bottom sits 52 px above the output
  edge.
- Width: `min(640px, output_width − 32px)`, and it **shrinks to fit** content
  down to 280 px. The width only grows during a session and never shrinks
  mid-session, so text doesn't reflow under the user's eyes.
- Height: content-driven, 1–6 lines of `popup-text` (22 px) plus padding:
  14 + (22 × n) + 14, plus a 28 px footer if shown. The default 4 lines is
  116 px + footer; the maximum 6 lines is 160 px + footer.

### Settings page

The page is a Configure surface: grouped rows with a label on the left and the
control on the right. There's no hero except the Overview's time-saved panel.

| Breakpoint | Width | Structure |
| --- | --- | --- |
| Wide | ≥ 1200 px | Header 64 px, white, 1 px hairline below. Sidebar 256 px with a hairline right edge. One content column, max 1120 px, **centred** right of the sidebar, side padding `clamp(24px, 4vw, 64px)`. Every section uses the same column |
| Medium | 768–1199 px | Sidebar collapses to a 64 px icon rail with tooltips; same centred column |
| Narrow | < 768 px | Header 56 px with a "Sections" button; sidebar becomes a full-height sheet; rows stack label over control; 16 px padding; hit targets ≥ 44 px. Checked down to 320 px |

**Row anatomy (wide).** A two-column grid `label | control`: the control column
is fixed at **360 px** with a 48 px gap. Min height 72 px, padding 20 × 24.
- Label column: `body` title and optional `small` description in `text-2`,
  max 560 px, vertically centred with the control.
- Control column: every control spans the full 360 px (selects, sliders,
  inputs, segmented controls, buttons), so all controls share **one left and
  one right edge**. Toggles sit at the right edge.
- Rows in a group share one `surface` container with `rounded.xl` (14), a 1 px
  hairline border and hairline dividers inset 24 px on both sides. No shadow.
- Stacked rows (tag inputs, long text) span both columns.

**Section anatomy.** A `heading` (48) title, then a `body-lg` (18) summary in
`text-2` (max 70ch), then groups 48 px apart, each titled in `subheading` (24)
with an optional violet "Reset to defaults" link on the same line. Sections are
80 px apart with a hairline rule between them. Advanced is collapsed by default.

**Scroll behavior.** The content column scrolls; header and sidebar stay fixed.
The sidebar highlights the last section whose top has crossed
`min(40% of viewport, 240 px)`. Deep links: `#microphone`, `#vocabulary`, …

## Elevation & Depth

**Flat.** Elevation is a 1 px hairline (`border`, black
at 10%) or a tint shift to `sunken`, never a drop shadow. Cards,
row groups, buttons, inputs, tabs and panels have **no shadow**.

The one exception is surfaces that float over **other apps or over the page**,
where a hairline alone would vanish against arbitrary content:

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `shadow-none` | none | none | Everything on the page |
| `shadow-float` | `0 1px 2px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.08)` | `0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.5)` | Indicator (expanded), popup, menus, toasts, dialogs |
| `shadow-idle` | `0 0 0 1px rgba(255,255,255,.55), 0 1px 3px rgba(0,0,0,.35)` | same | The idle line (see below) |

Floating surfaces over the page also switch to a `border-strong` edge, so they
read as separate even with the shadow stripped out in high-contrast mode.

**Blur tokens.** `blur-glass` = 24 px (compositor, indicator + popup). The page
itself uses no blur (the mobile nav sheet uses a flat `rgba(0,0,0,.32)` scrim).

**The idle line.** It must disappear on any wallpaper and still be findable. It
has a Charcoal (#171717) core with a 1 px 55%-white hairline ring and a tiny
drop shadow, at 35% overall opacity. Dark core plus light ring means it's
never the same color as what's behind it. Ring vs core is 6.1:1 before the
opacity is applied.

**GTK caveat.** GTK4 draws `box-shadow` inside the surface, so the indicator
and popup surfaces are padded by the shadow extent (indicator 12 px, popup
24 px) and the input region excludes that padding.

## Shapes

Three radii, plus pills for the two things that are genuinely
pill-shaped.

| Token | Value | Use |
| --- | --- | --- |
| `rounded.xs` | 4 px | Level bars, key caps, tag remove buttons |
| `rounded.md` | **8 px** | Buttons, inputs, selects, tabs, badges, tags, cards, code blocks, nav items, toasts |
| `rounded.xl` | **14 px** | Large containers: row groups, panels, popup card, menus, dialogs |
| `rounded.hero` | **30 px** | Hero panels only: the time-saved panel, the privacy statement, the mockup stage |
| `rounded.pill` | 999 px | The indicator (all states) and toggle tracks |

Never 12 px, never 4 px on a card or button. Nested radii follow
`inner = outer − padding`.

**Icons.** Lucide (ISC), inlined as SVG, `stroke-width: 1.75`, `currentColor`,
sizes 14 / 16 / 20, monochrome black (or `text-2`). Violet only on the logo mark, the active nav item's
icon and the privacy statement's lock. No icon fonts, no CDN. Used set:
`mic, mic-off, square, check, circle-check, triangle-alert, circle-alert, info,
loader-circle, grip-vertical, grip-horizontal, copy, rotate-ccw, x, plus,
pencil, trash-2, search, chevron-down, keyboard, audio-lines, sparkles, book-a,
app-window, type, palette, shield, sliders-horizontal, gauge, activity, cpu,
memory-stick, timer, terminal, code, message-square, mail, file-text, lock,
eye-off, circle-dashed, power`. Icons label; they don't decorate.

## Motion

Motion explains state changes. It never loops without a reason and never
delays the user. Every duration here is under 200 ms except fades that happen
*after* the work is done.

### Tokens

| Token | Value | Use |
| --- | --- | --- |
| `dur-instant` | 80 ms | Color/opacity on hover, press feedback |
| `dur-fast` | 120 ms | Small moves: toggle thumb, segmented thumb, badge swap |
| `dur-base` | 160 ms | Indicator expand/collapse, popup enter |
| `dur-slow` | 200 ms | Popup height change, nav sheet, toast enter |
| `dur-fade-out` | 240 ms | Popup/toast exit (runs after the paste, costs the user nothing) |
| `ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Anything that moves and stays |
| `ease-enter` | `cubic-bezier(0.05, 0.7, 0.1, 1)` | Appearing surfaces (decelerate) |
| `ease-exit` | `cubic-bezier(0.3, 0, 0.8, 0.15)` | Disappearing surfaces (accelerate) |
| `ease-linear` | `linear` | Level meter, progress, spinner rotation |
| `spring-pill` | stiffness 520, damping 38, mass 1 (≈ 150 ms settle, no visible overshoot) | Indicator size, if implemented with a spring; otherwise `dur-base` + `ease-standard` |

**GTK mapping.** GTK4 CSS transitions cover opacity, color, `min-width` and
`min-height` on the inner widget. Size changes of the indicator animate the
*inner* pill inside a fixed-size surface (144 × 54), so the compositor never
has to resize the layer surface mid-animation. The level meter is drawn in a
`Gtk.DrawingArea` driven by `add_tick_callback`, not CSS.

### Reduced motion

Detection: web `prefers-reduced-motion: reduce`. GTK
`Gtk.Settings:gtk-interface-reduced-motion` = `REDUCE` (GTK 4.20+), or
`gtk-enable-animations` = false.

When reduced:

- Every size/position change becomes an **instant** swap plus an 80 ms
  opacity crossfade (`dur-instant`). Nothing slides, grows, or scales.
- The level meter keeps working because it's information, not decoration.
  It switches from 5 moving bars to a **single static bar whose fill
  width** tracks the level, updated at 10 Hz instead of 20.
- The finishing spinner becomes a static `loader-circle` icon with the word
  "Finishing" in the popup footer.
- Popup auto-scroll jumps instead of scrolling.
- Toasts and the saved indicator appear and disappear with opacity only.

### Choreography: one full dictation

| t | Indicator | Popup |
| --- | --- | --- |
| hotkey / click | Idle → Recording: pill grows 48×8 → 120×36 in `dur-base`, `ease-standard`; fill goes to glass; record ring fades in over 80 ms *after* 40 ms (so the size lands first) | Enters: opacity 0 → 1 and translateY 6 → 0 px, `dur-base`, `ease-enter`. Shows "Listening…" |
| speaking | Level bars at 20 Hz, each bar height eased toward target with a 50 ms one-pole low-pass (no CSS transition, so it can't lag behind) | Text streams in (see Popup → Streaming) |
| release | Recording → Finishing: bars collapse to a 3-dot shimmer in 120 ms | Live zone fades to pending style in 120 ms; footer shows "Finishing" |
| pasted | Finishing → Idle: pill shrinks 120×36 → 48×8 in `dur-base`, `ease-standard` | Done state: check + "Pasted" for `fade_ms` (default 1000 ms), then exit: opacity 1 → 0, translateY 0 → 4 px, `dur-fade-out`, `ease-exit` |

The pill starts shrinking at *paste*, not at fade-out. Its job is over and it
should return to being ignorable immediately; the popup is what confirms.

### Latency honesty

Nothing waits for an animation. State changes are applied to the model first
and the animation catches up. If a new state arrives mid-transition, the
transition retargets from its current value (CSS does this natively; the
spring/tick code must too). The finishing state has a **120 ms grace**: if the
paste lands within 120 ms of release, the Finishing visuals are skipped and the
pill goes straight to Idle, so fast sessions don't flicker a spinner.

## Components

### State encoding (applies everywhere)

Every state is carried by at least two channels. Color is never the only one.

| State | Shape / icon | Text | Color |
| --- | --- | --- | --- |
| Idle | 48×8 line | — (tooltip on hover: "flowd · Super+D to dictate") | glass @ 35% |
| Ready (hover) | Pill + `mic` | aria/tooltip "Start dictation" | glass, `text` icon |
| Recording | Pill + red ring + stop disc + moving bars | Popup: "Listening…" / words | `record` |
| Finishing | Pill + 3 pulsing dots | Popup footer: "Finishing" | `text-2` |
| Pasted | Popup `check` | "Pasted into {app}" | `primary` |
| Fallback | Popup `info` | "Pasted without cleanup" | `text-2` |
| Warning | Amber dot + `triangle-alert` on hover | One-line reason | `warn` |
| Error | `mic-off` / `circle-alert` | Message + next step | `danger` |
| Healthy (settings) | `circle-check` | "Online", "Running" | `primary` |

---

### Indicator

A layer-shell surface (namespace `flowd-indicator`, 144 × 54 px fixed, input
region varies by state) holding one inner pill that changes size. It never
takes keyboard focus. Every interaction is pointer-only; the keyboard path is
the global hotkey.

**Anatomy (expanded).** Pill 120 × 36, `rounded.pill`, glass material,
`shadow-float`. Left: 28 px circular button area (icon 16 px) at 4 px inset. Right:
level meter or status slot, 72 × 20. 1 px edge per theme (see Colors → Glass).

#### 1. Idle

- 48 × 8 px, `rounded.pill`, fill `dark-glass` in **both** themes (see
  Elevation → the idle line), ring `0 0 0 1px rgba(255,255,255,.55)`, opacity
  **0.35**.
- Input region 120 × 20 centered, so it's hoverable without hunting.
- Cursor: default.
- Hidden entirely when `[ui] indicator = false` (settings: Hotkey &
  activation → Show indicator), and while a fullscreen client is focused on that
  output (best effort: Hyprland and Sway only, via the same queries as
  `context.py`); it returns on exit.

#### 2. Hover (Ready)

- Enter delay **80 ms** (prevents flicker when the pointer crosses the screen
  edge on its way somewhere else). Leave delay **240 ms**.
- Expands to 120 × 36 in `dur-base` / `ease-standard`, opacity 0.35 → 0.96,
  fill becomes the theme's glass.
- Content fades in 60 ms after the size starts: a 28 px circle in `sunken`
  holding the `mic` icon 16 px in `text`, then the label "Dictate" in
  `label` `text-2`. That's all that fits in 120 px, and it's all that's
  needed. The hotkey hint lives in the popup footer while recording (flowd never
  sees the compositor binding, so it shows the label the user typed in
  Settings → Hotkey & activation, or nothing).
- Pointer: `pointer`. Click (button 1, press + release within the pill) →
  Recording. Right-click → nothing (no context menu; settings live in the
  browser). Middle-click → nothing.
- If the hotkey fires while hovered, same as click.
- A `grip-vertical` icon (12 px, `text-2` at 70%) fades in at the far right
  **only after 600 ms of hover**, the drag affordance (see 6). It's absent
  at first so a quick hover-and-click stays uncluttered.

#### 3. Recording

- Size stays 120 × 36. Fill: glass. Ring: 1.5 px inside stroke in `record`.
- Left: 24 px `record-fill` disc with a white 8 × 8 `rounded.xs` square (stop).
  Contrast white on fill 5.55 / 4.82.
- Right: **level meter**, 5 bars, each 3 px wide, 3 px gap, `rounded.xs`, color
  `record`, heights 4–20 px. The bars are driven by RMS in dBFS over each 50 ms
  window (20 Hz), mapped −60 dB → 4 px and −12 dB → 20 px, with a small fixed
  per-bar offset (0.8, 1.0, 0.9, 0.7, 0.85) × level so they don't move in
  lockstep. That makes it read as a voice, not a VU. Silence never drops below
  4 px, so the meter visibly "breathes" and the user knows the mic is live.
- Clipping (peak ≥ −1 dBFS for ≥ 3 consecutive windows): the bars stay red and
  the popup footer shows "Too loud, move back a little" for 2 s. No flashing.
- Click → Stop (same as hotkey release in toggle mode). In push-to-talk mode
  clicking still stops. The pointer is the fallback when a key-up is lost.
- A barely perceptible 1.5 s opacity breath on the ring (1.0 ↔ 0.72,
  `ease-standard`) signals "live" to peripheral vision. Disabled under reduced
  motion (the ring stays at 1.0).
- Time limit: from `max_session_s − 10 s` the popup footer counts down ("0:09
  left") in `warn`. At the limit, flowd auto-stops (spec 9.1) and the footer
  says "Time limit reached".

#### 4. Finishing

- Entered on release. Skipped if the paste lands within 120 ms.
- Stop disc → `text-2` 16 px `loader-circle` rotating 800 ms/turn linear
  (reduced motion: static). Bars collapse into 3 dots, 4 px, `text-2`, pulsing
  opacity 0.3 ↔ 1 staggered 120 ms (reduced motion: static at 0.6).
- Ring goes from `record` to none over 120 ms. The mic is already closed, and
  red must mean *mic open* only.
- Not clickable (input region shrinks to empty), so a late double-click can't
  start a new session over an unfinished paste.
- Hard ceiling is `final_timeout_ms` (800) + injection; after that it always
  resolves to Idle, with the popup explaining any fallback.

#### 5. Warning

A degraded-but-working condition. It overlays whichever base state is current.

- **Idle + warning:** a 6 px `warn` dot with a 1 px dark ring sits centered
  above the right end of the idle line (x = +18 px, y = −5 px). The idle line's
  opacity rises from 0.35 → 0.55, so the marker is readable on busy wallpaper.
  Shape (dot) plus position is the non-color cue.
- **Hover + warning:** the expanded pill widens to fit a one-line reason (max
  **360 px**, ellipsized; a surface that never takes focus offers no
  tooltip, so the full reason is not shown there). This is the one
  state where the layer surface grows: it's resized to 384 × 54 *before* the
  pill animates wider and shrunk back after it collapses, so the pill is never
  clipped by its own surface: `triangle-alert`
  14 px in `warn`, then the reason in `label` `text`, e.g.
  - "Cleanup offline, pasting as heard"
  - "Microphone unavailable: USB Audio unplugged"
  - "Preview unavailable on this compositor" (settings-only; `flowd-ui` isn't
    running in that case)
  The mic button stays at the left and clicking it still starts dictation,
  except when the mic itself is the problem. Then the icon is `mic-off` in
  `danger`, the pill is not clickable, and the reason says so.
- **Recording + warning** (cleanup went down mid-session): no change to the
  pill. The popup footer carries it ("Cleanup offline, pasting as heard").
- Warnings clear themselves as soon as the condition clears (the next health
  check succeeds, or the device is back); the dot fades out over 160 ms.

#### 6. Dragging

- Affordance: the grip appears after 600 ms of hover (see 2), and the cursor
  over the grip is `grab`. Dragging works from anywhere on the pill once the
  pointer has moved **> 4 px** horizontally with the button held. Below that
  it's a click.
- During drag: cursor `grabbing`; pill lifts (`shadow-float`, scale 1.00 → 1.04 in
  `dur-fast`); content is replaced by `grip-horizontal` + "Move". The pill tracks
  the pointer on x only, clamped 16 px from the output edges.
- **Snap points:** 0.25, 0.5 and 0.75 of the output width, with an 8 px
  magnetic range. A 1 px × 12 px tick in `text-2` appears at the snap point while
  within range. The center snap has a slightly stronger pull (12 px).
- Release: settles to the final x in `dur-fast` / `ease-standard`, saves the
  fraction to `indicator.json`, returns to Hover. Esc can't cancel (no keyboard
  focus by design); dragging back is the undo, and Settings → Hotkey &
  activation → "Reset indicator position" restores center.
- **Implementation note.** A layer surface can't be moved by the compositor
  on drag. Past the drag threshold the indicator surface widens to the full
  output width (left margin 0) and the pill is drawn at the pointer inside it,
  so the surface never moves under the pointer; on release it shrinks back to
  144 px with its left margin at the new place. Wayland keeps delivering
  pointer events to the surface the button was pressed on until release. The indicator stays on its output; the per-output
  position is the way to place it on another.
- Reduced motion: no scale, no settle animation; ticks still show.

#### Indicator on-screen rules

- Over fullscreen video or games: hidden (see Idle).
- Multi-monitor: shown on the output with the focused window (best effort,
  Hyprland and Sway), and it follows focus with a 160 ms crossfade (never a slide across outputs).
- Screen sharing: the indicator is a layer surface, so it appears in screen
  captures that capture overlay layers. That's intentional; a visible mic
  state is the honest default.

---

### Preview popup

A read-only layer surface (namespace `flowd-popup`, click-through, keyboard
`NONE`) placed as in Layout → Popup placement.

**Anatomy.**

```
┌──────────────────────────────────────────────────────────────┐  rounded.xl, glass, shadow-float
│  Polished words in text. Pending words in text-2 and         │  popup-text 15/22
│  live words in italic live-color…▍                           │  ≤ max_lines (1–6, default 4)
├──────────────────────────────────────────────────────────────┤  1 px border @ 50% (only if footer)
│  [code] Code · kitty                        0:12 · Super D to stop│  footer 28 px, label, text-2
└──────────────────────────────────────────────────────────────┘
```

- Padding 14 px top/bottom, 18 px sides. Footer: 8 px top padding, 28 px tall,
  `label` in `text-2`. Left: mode chip; center-left: app id; right: elapsed
  time in `tnum` and, while recording, the stop hint.
- The footer is always one line. When space runs out, the least important
  part goes first: app id, then elapsed time, then the stop hint. A status
  message is ellipsized last, and its full text goes to the tooltip-free
  `notify-send` path when it's an error.
- Footer shows only when `[ui] footer = true` (default true) *or* when it
  carries a status (finishing, fallback, warning, error), so status never
  depends on the setting.

#### The three text zones

They must be distinct without being loud. The distinction is carried by
**luminance, style and an underline**, so it survives any single channel failing.

| Zone | Color | Style | Extra cue | Changes when |
| --- | --- | --- | --- | --- |
| Polished | `text` | Upright 400 | — | Only on a self-correction merge |
| Pending | `text-2` | Upright 400 | 1 px solid underline in `text-2` @ 40% (Pango has no dotted underline) | Replaced when the LLM chunk returns |
| Live | `live` | *Italic* 400 | Trailing caret ▍ 2 × 16 px in `live`, blinking 1 s steps (reduced motion: solid) | Every partial (~5–10 Hz) |

- Zones flow inline in one paragraph (polished → pending → live), separated by a
  normal space. There are no line breaks between zones.
- **Pending → polished swap:** the pending run crossfades to the polished text
  over `dur-fast` (opacity 0 → 1 on the new run, the old run removed at the
  same time). Word-level diffing isn't attempted; a chunk is swapped whole.
  If the swap changes the line count, the height animates over `dur-slow`.
- **Live updates:** text is replaced instantly. Animating a partial that changes
  10× a second reads as jitter. Only the caret is animated.
- **Self-correction merge** ("no wait, Thursday"): the affected polished run
  gets a 600 ms `primary-soft` highlight fading to transparent, so the user sees
  *why* earlier text changed. Reduced motion: 600 ms highlight with no fade,
  then removed.
- **Auto-scroll:** the text box is clipped to `max_lines`; when content exceeds
  it, it scrolls so the last line is fully visible, `dur-slow` / `ease-standard`
  (reduced motion: jump). A 16 px top fade-out mask (glass color → transparent)
  shows there's more above. The user can't scroll it; it's click-through by
  design. The full text is in `flowctl last`.

#### States

| # | State | Content | Footer | Enter / exit |
| --- | --- | --- | --- | --- |
| 1 | **Listening** (no words yet) | "Listening…" in `text-2` italic, with a 3-dot ellipsis whose dots fade in sequence (reduced motion: static "Listening…") | mode · app | Enter: `dur-base`, `ease-enter`, translateY 6 → 0 |
| 2 | **Streaming** | Polished / pending / live as above | mode · app · 0:07 · stop hint | — |
| 3 | **Finishing** | Text frozen; live run restyles to pending (italic off, color to `text-2`) over `dur-fast` | `loader-circle` + "Finishing" | — |
| 4 | **Pasted** | Final text (all polished) | `check` in `primary` + "Pasted into kitty" | Holds `fade_ms` (default 1000), then exit `dur-fade-out` / `ease-exit`, translateY 0 → 4 |
| 5 | **Fallback used** | Final text in `text` (it *is* what was pasted) | `info` in `text-2` + "Pasted as heard · cleanup offline" (or "· cleanup timed out" / "· cleanup changed too much") | Holds `fade_ms + 1000`, since the note needs reading time |
| 6 | **Nothing to paste** | "No speech detected" in `text-2` | — | Holds 1000 ms (spec 9.1) |
| 7 | **Cancelled** | Text dims to `text-2` with a 1 px strike-through | `x` + "Cancelled, nothing pasted" | Holds 800 ms |
| 8 | **Error: mic lost** | Whatever was captured, in `text` | `mic-off` in `danger` + "Mic disconnected · pasted what was heard" (or "· nothing was pasted") | Holds 3000 ms. Also sends `notify-send` (spec 9.2) |
| 9 | **Error: paste failed** | Final text | `circle-alert` in `danger` + "Couldn't paste. Run flowctl last to copy it" | Holds 4000 ms |
| 10 | **Time limit** | Text | `timer` in `warn` + "Time limit reached (5:00)" | Then continues as 3 → 4 |

Error footers use `danger` for the icon only; the message text stays `text`
for legibility on glass.

**Empty, long, and odd content.**

- A single word: the card shrinks to content (min 280 px) and is centered on
  the indicator.
- Very long unbroken tokens (URLs, paths) break anywhere (`overflow-wrap: anywhere`
  / Pango `WRAP_WORD_CHAR`).
- RTL isn't supported by the recognizer; not designed for.

---

### Settings controls

Every control shares these rules.

- **Sizes.** Default height 40 px (desktop). Under 768 px or `pointer: coarse`:
  44 px. Hit targets are never smaller than 24 × 24 on desktop and 44 × 44 on touch.
- **Flat.** No control has a shadow. Edges are 1 px `border-strong` (inputs) or
  1.5 px violet (buttons, selected tabs).
- **Focus ring.** `:focus-visible` only: `outline: 2px solid var(--primary);
  outline-offset: 2px`, radius following the control. It's never removed and
  never replaced by a color change alone. Contrast vs surface 4.72 / 6.49 worst case.

#### Buttons

Two button styles, both violet, both `rounded.md`, `body` text at 400:

| Variant | Fill | Edge | Text | Use |
| --- | --- | --- | --- | --- |
| Filled | `primary` | none | `on-primary` | The one main action in a context: "Restart flowd", "Done", "Save" in a dialog. At most one per view |
| Outlined | `surface` (transparent in dark) | 1.5 px `primary` | `primary` | Every other action: "Reset position", "Test microphone", "Check now" |
| Ghost / link | none | none | `text`, violet + underline on hover | Low-priority actions in banners: "Later" |
| Danger | `danger` | none | `on-danger` | "Reset all" in the confirm dialog only |

Height 40 (32 for `sm`), padding 0 × 20. Hover: outlined gets a `primary-soft`
wash, filled darkens 14%. Inside a settings row a button spans the full control
column. "Reset to defaults", "Copy" and inline links are violet text links.
- **Disabled.** Opacity 0.45, `cursor: not-allowed`, still focusable when it has a
  tooltip explaining why (`aria-disabled="true"` rather than `disabled`).
- **Every control has a visible label** (the row title), linked with
  `aria-labelledby`; the row description is `aria-describedby`.
- **Auto-save** (see Save model below). No control has its own Save button.

#### Toggle

- Track 44 × 24, `rounded.pill`. Thumb 18 px circle, 3 px inset.
- Off: `sunken` track with a 1 px `border-strong` ring (3:1 non-text), thumb
  `text-2`. On: `brand` (violet) track, white thumb, with a 10 px `check`
  inside the thumb in `brand` (the non-color cue for on vs off). Sits at the
  right edge of the control column.
- Hover: track brightness ±6%. Pressed: thumb widens to 20 px (squish), `dur-instant`.
- Motion: thumb slides `dur-fast` / `ease-standard`; reduced motion is an
  instant jump.
- `role="switch"`, `aria-checked`. Space toggles; Enter also toggles.
- States: off, on, hover, focus, pressed, disabled-off, disabled-on,
  **saving** (thumb shows a 10 px spinner for > 300 ms saves), **error**
  (reverts to the previous position with a 2-cycle 3 px horizontal shake, then
  shows an inline error; reduced motion: no shake).

#### Segmented control

- A tab strip: separate tabs 8 px apart, each `rounded.md`, height
  36, padding 0 × 16, `small` text in `text`, `surface` fill, 1 px hairline.
  In a settings row the tabs share the 360 px control column equally.
- Selected: the hairline is replaced by a 1.5 px `brand` ring (dark: plus a
  `primary-soft` fill). Text stays `text`. Hover: the hairline darkens to
  `border-strong`.
- The ring moves instantly; no sliding thumb (flat, no motion needed).
- `role="radiogroup"` with `role="radio"` children, roving tabindex, ←/→ to move
  **and** select (it's a setting, so selection is the action).
- Optional leading icon per segment (14 px). States: default, hover, focus
  (ring around the whole group, with a 1 px `primary` inner outline on the
  focused segment), disabled, disabled-segment.

#### Select

- Uses the **native `<select>`** styled as an input with a `chevron-down` 14 px on
  the right. Native keeps keyboard, screen reader and mobile behavior correct
  for free; the dropdown list is the browser's.
- Rich options (the input device picker) use a custom listbox *only* where
  the option needs two lines (device name + ALSA/PipeWire id). There it's a
  button that opens a `raised` popover, `rounded.xl`, `shadow-float`, max height
  320 px, options 36 px, selected option with `check` + `primary-soft` row;
  `role="listbox"`, type-ahead, ↑/↓, Home/End, Enter selects, Esc closes and
  returns focus.
- States: default, hover (border `text-2`), focus, open, disabled,
  **invalid** (border `danger` + inline error), **missing value** (a saved
  device that isn't present: shows the stored name in `text-2` with a
  `warn` badge "Not connected", and flowd uses the default meanwhile).

#### Slider with value

- Track 4 px, `sunken`, `rounded.pill`; filled part `primary`; thumb 16 px
  `surface` with 1.5 px `border-strong` ring and; 24 px hit area.
- To the right: a **number input with unit** (see below), 88 px wide, bound to
  the slider. The value is always readable and typeable, never only
  implied by position.
- Optional ticks for meaningful points (e.g. default value: a 2 × 8 px tick in
  `text-2` labeled "default" in `small` below).
- Keyboard: ←/→ step, PgUp/PgDn 10×step, Home/End min/max. `role="slider"`,
  `aria-valuetext` including the unit ("350 milliseconds").
- Saves on **release** / key-up (debounced 400 ms for keyboard), not on every
  pixel of drag.
- States: default, hover (thumb ring `text-2`), focus, dragging (thumb scale
  1.1, `shadow-float`), disabled, out-of-recommended-range (value input shows
  `warn` border + caption "Above 1500 ms may feel sluggish"; it's allowed).

#### Number input with unit

- Input 32 px, right-aligned `tnum` value, unit suffix inside the field in
  `text-2` (`ms`, `s`, `words`, `%`) as a non-editable adornment. Width
  88–120 px.
- Optional stepper (−/+) buttons 24 px on the right for small integer ranges.
- Validation mirrors `flowd/config.py` exactly: positive integer where the
  daemon requires it, 0–1 for thresholds, min ≤ max pairs. Validates on blur and
  on Enter. While typing, only non-numeric keystrokes are blocked.
- States: default, hover, focus, **invalid** (border `danger`, `circle-alert`
  14 px inside left, inline error below), disabled, **saving**, **saved**.

#### Tag input

Used for correction phrases, terminal apps, and vocabulary terms.

- A field (`surface`, `border-strong`, `rounded.md`, min height 32) holding
  chips followed by a text input. Chips: height 24, `sunken`, `rounded.md`,
  `body` 13 px, 8 px padding, a 16 px `x` remove button with a 24 px hit area.
- Enter or `,` commits a tag; Backspace in an empty input selects the last chip
  (focus ring on it), a second Backspace removes it. ←/→ move between chips;
  Delete removes the focused chip.
- Duplicates (case-insensitive) aren't added; the existing chip flashes a
  `primary-soft` background for 600 ms and a polite live region announces
  "'no wait' is already in the list".
- Removing a chip shows an **Undo** toast (5 s).
- Terms that fail validation (e.g. a vocabulary term containing a comma, per
  `vocab.toml` rules) stay in the input with an inline error.
- States: empty (placeholder "Add a phrase…"), with tags, focus, chip-focus,
  chip-hover (remove button `text`), invalid, disabled.

#### Reorderable list

Used for the paste method order.

- Rows 48 px inside a row group. Left: `grip-vertical` 16 px handle (the
  drag target, `cursor: grab`) and the position number in `tnum` `text-2`. Then
  the method name in `mono` and a one-line caption ("Paste via wl-clipboard +
  Ctrl+V"). Right: availability badge.
- **Keyboard reorder** (required, since drag alone isn't accessible): focus
  the handle (it's a button, "Reorder clipboard, position 1 of 4"), press Space
  to pick up (row lifts: `raised`, `shadow-float`), ↑/↓ to move, Space to drop,
  Esc to cancel. Every move is announced ("clipboard, moved to position 2 of
  4"). Explicit ↑/↓ icon buttons also appear on hover/focus for pointer
  users who don't want to drag.
- Pointer drag: the row lifts and follows the pointer on y; other rows shift
  with `dur-fast` / `ease-standard`; a 2 px `primary` insertion line shows the
  drop point. Reduced motion: rows swap instantly, and the insertion line is still
  shown.
- Rows that are **not installed** stay in the list (order is still saved), are
  shown at 60% opacity with the badge, and are skipped at runtime, matching the
  daemon. The list can't be emptied (`[inject] order` must list at least one).
- States: default, hover, handle-focus, grabbed, dragging-over, disabled.

#### Key/value table

Used for app → mode mapping and vocabulary replacement rules.

- Header row 36 px, `label` `text-2`, sticky within the section. Rows 44 px,
  hairline dividers, `mono` for app ids and spoken/written phrases.
- Each row: key (text), value (text input or segmented/select for modes), row
  actions on the right: `pencil` edit and `trash-2` delete as 28 px icon buttons,
  always visible (not hover-only, for touch and discoverability), with
  `aria-label`s including the key ("Delete rule 'hyper land'").
- **Add row** is the last row: inline inputs with a `plus` "Add" button,
  Enter to submit. New rows appear with a 600 ms `primary-soft` highlight.
- **Edit** switches the row to inputs in place; Enter saves, Esc cancels,
  focus returns to the edit button.
- **Delete** removes immediately and shows an Undo toast (5 s); no confirm
  dialog for single rows.
- Built-in defaults (the `modes` table ships 17 entries) show a `badge-neutral`
  "Built-in"; they can be changed (which makes an override) but not deleted,
  only "Reset" per row.
- Filter field above tables with > 8 rows (`search` icon, `/` focuses it when
  the table section is in view).
- Narrow: each row becomes a 2-line card (key over value), actions on the right.
- States: default, hover row (`hover`), editing, invalid cell (inline error
  under the cell), duplicate key (error "kitty is already mapped to code"),
  empty (see Empty states).

#### Status badge

- Height 24, `rounded.md` (8, not a pill), 9 px horizontal padding, `label`,
  **always icon + text** (icon 12 px).
- Healthy states are **neutral**. Violet is for actions and selection, so a
  wall of violet "OK" badges would drain its meaning. Only states that need
  attention get a tint.

| Variant | Icon | Colors | Example |
| --- | --- | --- | --- |
| ok | `circle-check` | `text` on transparent, 1 px `border-strong` ring | Ready, Available, Running, Feels instant |
| warn | `triangle-alert` | `warn` on `warn-soft` | Offline, Not connected, Not tidied |
| danger | `circle-alert` | `danger` on `danger-soft` | Failed, Stopped |
| neutral | `circle-dashed` | `text-2` on transparent, 1 px `border` ring | Not installed, Built-in, Disabled |
| restart | `power` | `text-2` on transparent, 1 px `border` ring | Requires restart (see marker below) |

#### Status card

Used on the Overview (stat cards, Performance details tiles).

- `surface`, `rounded.xl`, 1 px `border`, padding 16. Title in `small` `text-2`
  with a 14 px icon, value in `heading-sm`, and a subline in `small` (e.g. "p95 812 ms").
- Right-aligned status badge when the card represents a component (Daemon,
  Speech models, Cleanup model).
- A card is never a link or button unless it navigates; if it does, the whole
  card is the `<a>` with hover `hover` and a focus ring.
- States: default, loading (value replaced by a 60 × 24 `sunken` block with
  no shimmer), unavailable ("—" with caption "No sessions yet"), degraded
  (badge warn + caption reason).

#### Small chart (latency)

Lives inside Overview → Performance details, not on the main overview.

- Inline SVG, drawn by ~60 lines of local JS. No chart library needed.
- 100% × 120 px. X: last 50 sessions (oldest → newest), Y: release-to-paste ms,
  0 to max(1200, p99), 3 horizontal gridlines in `border`.
- Each session is a 3 px wide bar in `text-2` at 50%. **Fallback sessions** are
  the same bar with a 3 px `warn` cap and hatch (shape plus color). The p50 line
  is 1.5 px solid `primary` with the label "p50 540 ms" at the right edge; p95 is
  1.5 px dashed `text` labeled "p95 812 ms". The **budget line** (spec 10.1:
  1000 ms p95) is 1 px dotted `danger` labeled "budget".
- Hover or focus on a bar (bars are focusable in a roving group, ←/→) shows a
  `raised` tooltip: "#48 · 11:02 · 612 ms · Code · clipboard".
- A visually hidden `<table>` carries the same data for screen readers, and
  a "Show as table" text button reveals it.
- Empty: "No dictations yet. Latency appears after your first session."

#### Code snippet with copy button

- `sunken`, `rounded.xl`, `mono`, padding 12 × 14, horizontal scroll, no wrap.
  Optional header strip 32 px with filename/context in `small` `text-2`
  (e.g. `~/.config/hypr/hyprland.conf`) and the copy button right-aligned.
- Copy button: 28 px, `copy` icon, `aria-label="Copy Hyprland snippet"`. On
  click: icon swaps to `check` in `primary` and the label "Copied" appears for
  1.5 s; a polite live region announces it. Failure (clipboard API denied):
  icon `circle-alert` `danger`, "Select and copy manually", and the snippet text
  is selected.
- Tabs above snippets for Hyprland / Sway / KDE / GNOME / X11 use the
  segmented control. The choice is remembered and preselected from
  `XDG_CURRENT_DESKTOP`.

#### Toast

- Bottom-right on wide (24 px from edges), bottom-center full-width minus 16 px
  on narrow. `raised`, `rounded.xl`, `shadow-float`, 1 px `border`, max width 400,
  padding 12 × 14. Icon 16 + `body` text + optional action button (text
  button in `primary`) + `x` close.
- At most 2 visible; newer ones stack above. Auto-dismiss 5 s (Undo toasts) or
  4 s (info); errors **don't** auto-dismiss. Hover and focus pause the timer.
- `role="status"` (info) / `role="alert"` (error). Esc dismisses the newest
  toast when focus is inside it.
- Enter: opacity 0 → 1, translateY 8 → 0, `dur-slow` / `ease-enter`. Exit: opacity
  only, `dur-fade-out` / `ease-exit`. Reduced motion: opacity only, 80 ms.
- Variants: info (`info`), success (`check`, `primary`), warning
  (`triangle-alert`), error (`circle-alert`, `danger`), undo (no icon, "Undo"
  action).

#### Inline validation error

- Directly under the control, 4 px gap, `small` in `danger`, with a 14 px
  `circle-alert` icon. The control gets `aria-invalid="true"` and
  `aria-describedby` pointing at the message.
- Message wording: what's wrong + what's allowed. "Must be a whole number
  above 0", "Minimum words can't exceed maximum (25)", "Cleanup must run on
  this machine (127.0.0.1, localhost or ::1)". These mirror `config.py`'s
  messages so the page and `flowctl reload` never disagree.
- An invalid value is **never saved**; the last good value stays active and
  a caption says so: "Still using 350 ms".

#### "Requires restart" marker

- A `badge restart` ("Requires restart", `power`; distinct from `rotate-ccw`, which means *reset to defaults*) placed after the row
  title, *before* the user changes anything, so it informs the decision.
- After such a change is saved, a **restart banner** pins to the top of the
  content column: `warn-soft` background, `rounded.xl`, `triangle-alert`,
  "2 changes take effect after flowd restarts." with a secondary button
  "Restart flowd" (runs `systemctl --user restart flowd` through the local API)
  and a text button "Later". During the restart the header status shows
  "Restarting…", and the banner clears when the daemon reports back.
- Which settings need a restart comes from the daemon, not the page (see
  Settings sections → Live vs restart).

#### Empty states

One pattern: a 20 px icon in `text-2`, one `body` sentence, one
`small` line of help, and at most one action. Left-aligned inside the group
container, 24 px padding. No illustrations.

| Where | Copy | Action |
| --- | --- | --- |
| Vocabulary terms | "No custom terms yet." / "Add names and acronyms the recognizer should spell your way, like Hyprland or LLM." | Add term |
| Replacement rules | "No replacement rules." / "Fix a mishearing that keeps coming back: spoken → written." | Add rule |
| Apps & modes (user overrides) | "Using built-in modes only." / "17 apps are mapped by default. Add one to override." | Add app |
| Overview (no sessions) | "No dictations yet." / "Press your hotkey or click the indicator to try it." | Show hotkey setup |
| Microphone list | "No input devices found." / "Check that PipeWire is running: `systemctl --user status pipewire`." | Refresh |
| Log (Advanced) | "Nothing logged at this level." | — |

---

### Save model (settings page)

- **When.** Toggles, segmented controls, selects and reorders save
  immediately. Sliders save on release. Text/number inputs save on blur or Enter,
  and also 800 ms after the last keystroke if the value is valid.
- **How.** `PATCH /api/config` with the changed key(s). The server writes
  `config.toml` atomically (write + rename), preserving comments where possible,
  then triggers `reload`. Response `{ok, applied: "live" | "restart", error?}`.
- **Row-level feedback** (directly under the control, right-aligned, overlaying the row's bottom padding so it never shifts layout or reserves a column):
  - Saving (> 300 ms only): 12 px spinner `text-2`.
  - Saved: 12 px `check` in `primary` + "Saved" in `small` `text-2`,
    fades out after 1.5 s. Screen readers get "Saved" via a polite live region.
  - Error: the control reverts or stays invalid, and an inline error appears.
- **Global feedback** in the header: a quiet "All changes saved" / "Saving…" /
  "Couldn't save" status text (`small`). "Couldn't save" is a `danger` badge
  with a Retry action.
- **Conflict.** If `config.toml` changed on disk since the page loaded
  (mtime/etag), a banner says "config.toml was edited outside this page" with
  "Reload page" (primary) and "Keep my changes" (overwrites). Never silently merge.
- **Daemon down.** The daemon serves the page, so it can't load without it. If
  the daemon stops while the page is open, the header badge says "Daemon
  stopped", every control turns read-only, and a banner says how to start it
  (`systemctl --user start flowd`).

---

### Settings page: structure and sections

**Transport.** The page is served by the daemon on
`http://127.0.0.1:8178` (`[settings] port`), bound to loopback only. All assets (HTML, CSS, JS, the
two fonts, the icon sprite) are bundled; the page makes no request outside its
own origin, enforced by `Content-Security-Policy: default-src 'self'`.

> **Security.** A loopback port is reachable by every local user and by any
> web page the user visits (DNS rebinding, CSRF). Every API request carries a
> per-launch token (`flowctl settings` opens `http://127.0.0.1:8178/#token=…`,
> and the page sends it as `Authorization: Bearer`), the `Host` header must be
> `127.0.0.1:8178` or `localhost:8178`, and a foreign `Origin` is rejected
> (ADR 0014).

#### Live vs restart

Derived from the current daemon (`daemon.py` reload handler and what is
captured at construction in `main.py`). The API reports this per key, so this
table is the design default, not something to hard-code.

| Applies live on save (via `reload`) | Requires restart |
| --- | --- |
| `[hotkey]` mode, debounce_ms · `[llm]` all · `[chunking]` all incl. correction cues · `[guardrails]` all · `[inject]` order, terminal_apps, restore_delay_ms · `[modes]` · vocabulary · `[logging]` log_transcripts, recordings_dir | `[stt]` model, final_model · `[audio]` device, always_open, max_session_s, block_ms, preroll_ms · `[vad]` all · `[ui]` enabled, max_lines, fade_ms (`flowd-ui` reads them on spawn, so restarting it is enough; the page can trigger that instead of a full restart) · `[logging]` level |

#### Header (64 px, sticky)

Left: the wordmark "flowd" in `subheading` (lowercase, `text`) with a 16 px
`audio-lines` mark. Then the **status strip**, a row of compact status items,
each icon + label + value, separated by 16 px:

| Item | Healthy | Degraded / down |
| --- | --- | --- |
| Service | `badge ok` "Running" (no label; the wordmark precedes it) | `badge danger` "Stopped" + "Start" text button |
| Speech | `badge ok` "Ready" (tooltip: "Moonshine small-streaming-en · Parakeet TDT 0.6B v2") | `badge warn` "Loading…" / `badge danger` "Failed to load" |
| Cleanup | `badge ok` "Ready" (not "Online", which implies a network) | `badge warn` "Offline, pasting as heard" |
| Memory | `memory-stick` + "1.2 GB memory" in `tnum` (same rounding as the overview) (anonymous memory of flowd + llama-server + flowd-ui, the same measure as the budget) | Value turns `warn` + `triangle-alert` above the 1.6 GB budget (ADR 0011) |

Right: save status text ("All changes saved"), then a theme button (`palette`
icon, cycles System/Light/Dark; `aria-label` includes the current value).

Narrow (< 768): the wordmark, a single combined badge ("All systems ok" /
"Cleanup offline" = worst state wins), and a "Sections" menu button. Tapping
the badge opens the full status list as a sheet.

#### Navigation

Sidebar, 256 px, `bg` (no separate color; it's separated by a 1 px `border`
right edge). Items 40 px, 16 px icon + `body`, `rounded.md`, 8 px inset. Active:
`nav-item-active` (`primary-soft` fill + `primary` text + `aria-current="page"`).
No accent rail; the fill is enough. A small `warn` dot on items with a problem (e.g. Cleanup when
offline), always paired with a visually hidden "(needs attention)".

Order and icons: Overview `gauge` · Hotkey & activation `keyboard` · Microphone
`mic` · Recognition `audio-lines` · Cleanup `sparkles` · Vocabulary `book-a` ·
Apps & modes `app-window` · Typing `type` · Appearance `palette` · Privacy
`shield` · Advanced `sliders-horizontal`.

Keyboard: the sidebar is a `<nav>` list of links; Tab reaches it after the
skip link ("Skip to settings"), ↑/↓ move within it, Enter activates and moves
focus to the section heading. There are no hidden single-key shortcuts; the
only page shortcut is `/` to focus a visible table filter, and it's shown as
a `kbd` hint in the filter field.

#### 1. Overview ("Your dictation")

The overview answers the user's question, *is this worth it?*, not the
engineer's question, *is it within budget?* Latency percentiles mean nothing to
most people, and "p95 812 ms" reads as noise. Everything on this screen is in
minutes, words and plain sentences. The engineering numbers still exist, one
click away under **Performance details**.

Everything is computed locally from `metrics.jsonl` (per-session `ts`, `mode`,
`app_id`, `counts.words`, and stage timestamps). No new data is collected. The
only new input is the user's typing speed, which they set themselves.

**Header row.** Title "Your dictation", one-line summary, and a period switch on
the right: `7 days | 30 days | All time` (default 30 days). These are rolling
windows, not calendar weeks or months, and the labels say so.

**1. Time saved** (the hero; full width, `surface`, `rounded.xl`).
- Left: "Time saved" label, the value in `display` (weight 400, fluid 48–80) `tnum` ("5 h 26 min"),
  then "in the last 30 days", then the change vs. the previous equal window in
  `primary` ("↑ 16% vs the 30 days before"; hidden for All time), then "That's
  18,193 words you didn't have to type."
- Right: **Minutes saved per day** bar chart (per week for All time, 13 bars),
  with "Best: 23 min on Sep 24" in the chart header. The best bar is solid
  `primary`; today's bar is outlined, and a small key under the chart names the
  best-day style. Bars are keyboard-focusable (←/→, Home/End) and show
  "Sep 24 · 23 min" on hover and focus.
- **How it's calculated** is stated right under the card, and the one
  assumption is editable inline: "Estimate: typing the same words at
  [40 words a minute], minus the time you spent speaking." Clicking the
  underlined value opens a small popover with a number field (5–200, validated),
  a "Done" button, and a hint ("Most people type 35–45 words a minute").
  The value is stored locally and every number on the page updates.
- Formula, per session: `max(0, words / typing_wpm − (speaking_s + paste_wait_s) / 60)`
  minutes. Summed per window. Speaking time is `released_ms − mic_open_ms`,
  and paste wait is `inject_ms − released_ms`. It's conservative: it doesn't
  credit fixing typos or the effort of typing.

**2. Three stat cards** (3 columns; 2 + 1 under 768 px).

| Card | Value | Subline |
| --- | --- | --- |
| Longest dictation | "188 words" | "in Thunderbird, 21 days ago · 3 min saved" |
| You speak at | "145 words a minute" | "3.6× your typing speed" |
| Dictations | "358" | "about 12 a day, on 30 of 30 days" |

**3. Where you dictate** (left panel). One row per app, sorted by words: the
app's display name (from the desktop entry; the app id is shown as a fallback,
with a hint like "Terminal (kitty)"), the mode it used as a small icon + label
(Code / Chat / Email / Writing), a bar proportional to the top app, and the
word count. This connects to Apps & modes: users can see which apps get
which style.

**4. How it's running** (right panel). Four plain-language rows, each with
an icon, a title, a one-line explanation and a status badge:

| Row | Healthy text | Badge | Degraded |
| --- | --- | --- | --- |
| Text appears | "0.5 s after you stop talking" | ok "Feels instant" (median < 700 ms) | warn "A bit slow" |
| Tidied up 96% of dictations | "The rest were typed exactly as you said them" | ok "Working well" (≤ 10% fallback) | warn "Often skipped"; offline: "Cleanup is offline, so text is typed as you said it" + warn "Offline" |
| Memory in use | "1.2 GB of your RAM while idle" | ok "Normal" (≤ 1.6 GB) | warn "High" |
| Stayed on this machine | "No audio or text was sent anywhere" | ok "Private" | never degrades; this is a statement of design, backed by the loopback check |

**5. Recent dictations.** The last 6: relative time ("2 h ago"), app + mode,
word count, and time saved, right-aligned in `primary`. Sessions that fell back
show a warn badge "Not tidied" before the saving. No transcript text, since
it isn't stored by default. A caption says: "flowd doesn't keep what you said.
Only counts and timings are stored."

**6. Performance details** (collapsed disclosure, closed by default, drawn
lazily on first open). Four small tiles: median and slowest-5% release → paste
(labelled in words, with p50 / p95 in the chart legend for people who know
them), cleanup fallback rate, and memory against budget. Then the latency chart
(see Small chart) and a pointer to `flowctl stats`. This is where the spec 10.1
budgets live.

**Empty state** (no sessions yet): the hero shows "No dictations yet" with
"Press Super+D or click the line at the bottom of your screen to try it", and
the cards, panels and list are hidden. Performance details stays available.

#### 2. Hotkey & activation

- **Activation** · segmented: Toggle | Push-to-talk. Description changes with
  the choice ("Press once to start, again to stop" / "Hold to speak, release
  to paste"). Selecting push-to-talk under KDE shows an inline `warn` note:
  "Plasma custom shortcuts fire on press only. Push-to-talk won't work there."
- **Hotkey label** · text input, placeholder "Super+D". Used only for hints in
  the indicator/popup; the binding itself lives in your compositor.
- **Debounce** · number with unit (ms), default 200.
- **Show indicator** · toggle. Description: "The thin line at the bottom of
  the screen. Dictation works without it."
- **Indicator position** · current value "Center of eDP-1" + secondary button
  "Reset position" (`rotate-ccw`).
- **Set up your hotkey** · segmented tabs Hyprland | Sway | KDE | GNOME | X11
  (preselected from `XDG_CURRENT_DESKTOP`), then the snippet for the chosen
  activation mode, from the README:

  ```ini
  # ~/.config/hypr/hyprland.conf: toggle
  bind = SUPER, D, exec, flowctl toggle
  ```
  ```ini
  # push-to-talk: bindr fires on release
  bind  = SUPER, D, exec, flowctl start
  bindr = SUPER, D, exec, flowctl stop
  ```
  Plus an optional "Full rewrite on stop" snippet (`flowctl stop --rewrite`).
  GNOME shows the `gsettings` block and a `warn` note that the live preview
  is unavailable on GNOME Wayland, with the reason in one sentence.

#### 3. Microphone

- **Input device** · rich select (name + PipeWire node, e.g. "Blue Yeti ·
  alsa_input.usb-…"), "System default" first. Requires restart.
- **Test microphone** · secondary button "Test microphone" → becomes "Stop
  test" and a live level meter appears inline: a 240 × 8 px bar in `sunken`
  with the fill in `record` (it *is* the mic being open, so red is correct here)
  plus a numeric dBFS readout in `tnum`, and a caption that updates: "Too quiet,
  speak up or move closer" (< −45 dB avg), "Good level" with `check` (−35…−12),
  "Too loud, may clip" (> −6 peak). The test auto-stops after 15 s. The
  header shows a `record` dot + "Mic open" while testing, so the mic state is
  honest.
- **Keep microphone open** · toggle, off by default. Description: "Avoids
  clipping your first syllable (300 ms pre-roll). The mic stays open while idle,
  and your system's mic indicator will stay on." Requires restart. Turning it on
  shows the privacy-style warning row (see Privacy).
- **Max session length** · number with unit (s), default 300; shows "5 min"
  helper text. Requires restart.

#### 4. Recognition

- **Preview model** · select, e.g. "Moonshine small streaming (default)",
  "Moonshine medium streaming". Each option's caption: size and a speed/accuracy
  note from the spec. Requires restart.
- **Final transcript model** · select: "Parakeet TDT 0.6B v2 (default)" /
  "None: commit the preview model's text". Caption: "Adds ~1 GB memory. Better
  accuracy on the text that gets pasted." Requires restart.
- **Silence before a phrase commits** · slider 150–1500 ms, default 350,
  tick at default. (`vad.commit_silence_ms`.)
- **Trailing audio kept** · slider 0–500 ms, default 150 (`vad.tail_ms`).
- **Voice-detection sensitivity** is *not* shown as a live control. ADR 0002
  made `vad.threshold` inert. It's listed in Advanced as read-only with the
  caption "Not used by the current recognizer (ADR 0002)." This is the honest
  version of what the brief asks for; a slider that does nothing would be
  worse than none.

#### 5. Cleanup (AI)

- **Clean up text with the local model** · toggle (maps to whether the LLM is
  used; off = always fallback text). Status badge beside the title: Online /
  Offline / Disabled.
- **Model status** row: model name in `mono` ("LFM2.5-350M Q4_0"), server
  "127.0.0.1:8177", last health check "12 s ago", and a secondary button "Check
  now". Offline shows `badge warn` "Offline" plus a `small`: "Start it with
  `systemctl --user start flowd-llm`" (copy button).
- **Chunk timeout** · number (ms), default 2000. **Final timeout** · number (ms),
  default 800, caption "The most flowd waits after you stop before pasting
  as heard." Both apply live.
- **Correction phrases** · tag input, defaults `no wait, no no, actually, i mean,
  sorry, scratch that, let me rephrase`. Caption: "Saying one of these tells
  cleanup to replace what came just before." "Reset to defaults" in the group
  header.
- **Server URL** lives in Advanced (it must be loopback; validated).

#### 6. Vocabulary

Two groups, backed by `vocab.toml`.

- **Terms** · tag input in `mono` ("Hyprland", "PipeWire", "LLM"). Caption:
  "Spelled exactly like this. Also nudges the recognizer toward them." Commas
  rejected with an inline error.
- **Replacements** · key/value table, columns "When you say" → "Write", e.g.
  `hyper land` → `Hyprland`. Caption: "Matched anywhere, ignoring case, so
  only add phrases you'd never mean literally." A "Test" field below the table:
  type a sentence and see the result live (runs `basic_clean` via the API).

#### 7. Apps & modes

- **App → mode table** · key/value, key = app id (`mono`), value = segmented
  Default | Code | Chat | Email (each with its icon: `file-text`, `code`,
  `message-square`, `mail`). Built-in rows marked. "Add the app you're in"
  helper: a button "Detect focused app" that starts a 3 s countdown; switch
  to the app and it fills in the id (via the daemon's context detection).
- **Terminal apps** · tag input (`inject.terminal_apps`). Caption:
  "Terminals get Code mode and paste with Ctrl+Shift+V."
- Mode descriptions in a compact 4-row definition list above the table, so
  the modes are explained where they're chosen.

#### 8. Typing

- **Paste method order** · reorderable list: `clipboard`, `wtype`, `ydotool`,
  `xdotool`. Badges: ok "Available", neutral "Not installed", warn
  "Installed, not running" (e.g. `ydotoold` down, with the fix in the
  tooltip and a copyable command). Caption: "flowd tries each in order and
  uses the first that works."
- **Clipboard restore delay** · number (ms), default 150. Caption: "How long
  before your previous clipboard is put back."

#### 9. Appearance

- **Theme** · segmented: System | Light | Dark (applies to the page, indicator
  and popup together).
- **Popup lines** · slider 1–6, default 4, discrete ticks. Requires a
  `flowd-ui` restart (the page offers "Restart preview" instead of the full restart).
- **Fade after paste** · slider 300–3000 ms, step 100, default 1000.
- **Show mode and app in popup** · toggle, default on.
- **Desktop notification when finished** · toggle, default off. Sends
  `notify-send` for pasted / fallback / error, for people who can't or don't
  watch the popup (screen-reader users, notification-centric setups). Errors
  always notify regardless (spec 9.2).
- **Live preview** (sticky on wide, to the right of the controls at ≥ 1200 px
  with a 320 px column; below on narrower): a 360 × 200 px stage with a
  wallpaper stand-in (a switcher: Light / Dark / Busy, where Busy is a
  CSS-generated high-frequency pattern of saturated colors, so contrast can be
  judged without shipping an image), showing the
  indicator and popup rendered with the real CSS tokens. A "Play" button runs
  the full choreography (idle → hover → recording → streaming → finishing →
  pasted) in 4 s so fade time and lines are felt. It respects reduced motion.
  It's decorative for screen readers except the "Play" button.

#### 10. Privacy

- A statement block at the top, not a toggle: `lock` icon, `body`
  "Nothing leaves this machine." Then `body` `text-2`: "Speech recognition and
  cleanup run locally. flowd makes no network requests, has no accounts and
  sends no telemetry. The cleanup server must be on 127.0.0.1." No badge, no
  marketing. This is a fact with a pointer to how it's enforced (spec 13.2,
  `config.py` loopback check).
- **Save recordings** · toggle, off. On reveals a folder path input
  (`logging.recordings_dir`, placeholder `~/flowd-recordings`) and a
  `warn-soft` banner: "Every dictation's audio and transcript will be saved
  as WAV + text in this folder until you turn this off." with "Open folder".
- **Log transcripts** · toggle, off. On shows a banner: "Your dictated text
  will be written to the journal and metrics log. Anyone who can read your
  logs can read it." Both banners use `triangle-alert` + `warn` and stay
  visible for as long as the setting is on.
- The header shows a persistent neutral badge `eye-off` → when either is on,
  it switches to `badge warn` "Recording saved" / "Logging text", so it
  can't be forgotten.

#### 11. Advanced

Collapsed disclosure row "Show advanced settings" (`chevron-down` rotates
180° in `dur-fast`). Expanded state is remembered per browser. Groups, each
with "Reset to defaults":

- **Guardrails** · `len_ratio_min` 0.6, `len_ratio_max` 1.3,
  `len_ratio_min_merged` 0.3, `novel_word_max` 0.20 (as %). Cross-field
  validation (min ≤ max) shown on both fields.
- **Chunking** · min/max chunk words (5/25), context sentences (2),
  short-bypass words (5).
- **Recognition internals** · lag allowance (900 ms), max uncommitted words
  (25), block size (100 ms, restart), `vad.threshold` read-only (see
  Recognition).
- **Cleanup server** · URL (validated loopback), max tokens factor (1.5),
  context tokens (1024, caption: "must match llama-server `-c`"), health
  interval (30 s), down after failures (2).
- **Logging** · level select: debug / info / warning / error (restart). Debug
  shows a `warn` caption: "Debug logs include transcript text."
- **Danger zone** (last, `danger` text only, no red box): "Reset all settings"
  → confirm dialog naming the file it'll rewrite (`~/.config/flowd/config.toml`)
  and that a backup `config.toml.bak` will be written. Buttons: "Cancel"
  (default focus) and "Reset all" (`danger` fill).

Every "Reset to defaults" shows an Undo toast; nothing destructive happens
without either Undo or a confirm.

---

### Accessibility checklist

These requirements are specified here. Meeting them in the design isn't
the same as passing an audit: full WCAG validation still needs manual testing
with assistive technology (Orca on GNOME/KDE, a screen reader in Firefox and
Chromium) and an expert review of the built page.

- **Contrast.** All text pairs ≥ 4.5:1, large text and UI boundaries ≥ 3:1,
  checked by `docs/design/contrast.py` and by the `design.md` lint for component
  pairs. The glass material is checked against worst-case wallpapers.
- **Not color alone.** Every state has an icon or text (State encoding table);
  the chart marks fallback sessions with a hatch cap; pending text has an
  underline; toggles show a check.
- **Keyboard.** Every settings control is reachable in DOM order; custom widgets
  follow WAI-ARIA APG patterns (switch, radiogroup, listbox, slider); the
  reorderable list has a keyboard mode; there are no keyboard traps; Esc closes
  popovers and sheets and returns focus to the opener.
- **Focus.** A visible 2 px `primary` ring with 2 px offset on every focusable
  element (`:focus-visible`), 3 px in high contrast. On the mobile nav sheet,
  focus is trapped inside while open.
- **Announcements.** One polite live region for "Saved"/"Copied"/reorder moves,
  one assertive region for save errors. The popup isn't announced, since
  it's a transient visual preview of text the user is speaking; the pasted text
  lands in their app, where their screen reader already is. If the user needs
  status by voice, Settings → Appearance lets them enable `notify-send` on
  finish/fallback/error (off by default), which goes through the desktop's own
  accessible notification path.
- **Motion.** Reduced-motion variants specified for every animation (Motion →
  Reduced motion).
- **Zoom and text size.** The page reflows at 400% zoom / 320 CSS px width with
  no horizontal scroll (except inside code snippets). All sizes are in `rem` in
  the implementation, and the popup respects GTK's text scaling factor.
- **Hit targets.** ≥ 24 px desktop, ≥ 44 px touch/narrow.
- **Language.** `lang="en"`; state words are plain ("Offline", not "Degraded
  mode engaged").

## Do's and Don'ts

**Do**

- Use violet for things the user can act on or has selected: buttons, links,
  focus, active tab, nav item, toggle-on. `brand` (#b154f9) for shapes,
  `primary` (#9333ea / #c98bfb) for text.
- Build hierarchy with size and tracking (13 → 80 px, −0.01em at 48 px and up).
  Everything is weight 400.
- Use 8 px radius for controls and cards, 14 px for containers, 30 px only for
  hero panels.
- Show depth with a 1 px hairline or a `sunken` tint. Keep the page flat.
- Keep red for *mic open*. If you need "error", use `danger` + an icon.
- Lead with numbers people care about (minutes saved, words, apps). Put
  engineering numbers behind "Performance details".
- Write state text that says what happened *and* what flowd did about it:
  "Cleanup offline, pasting as heard".
- Let the indicator return to idle the moment its job is done.
- Put "Requires restart" on the row *before* the user changes it.
- Keep settings rows one decision each: label left, control right,
  description under the label.

**Don't**

- Don't use weight 500, 600 or 700, anywhere, including `<b>`, table headers
  and numbers.
- Don't put drop shadows on cards, rows, buttons, inputs or tabs. Only surfaces
  floating over other content get `shadow-float`.
- Don't introduce a second brand color, and don't color healthy status with
  violet. Neutral outline + icon.
- Don't set text in #b154f9; it's 3.8:1 on white.
- Don't use 12 px radius, or 4 px on a card or button.
- Don't add decorative 3D objects or gradients. Decoration has no
  place in an OSD or a settings page.
- Don't take keyboard focus from the indicator or popup, for any reason. No text
  fields, no buttons that need Enter, no "click to copy" in the popup.
- Don't animate live partial text; only the caret.
- Don't use gradients, glows, or color on the idle indicator. It has to be
  ignorable.
- Don't hide failures behind a spinner. Every wait longer than
  `final_timeout_ms` resolves to a stated outcome.
- Don't expose a control that does nothing (see `vad.threshold`).
- Don't load anything from the network: no web font CDN, no icon CDN, no
  analytics, no update check.

## Implementation notes (`flowd-ui`, gtkmm)

A short bridge from these tokens to `flowd-ui` (ADR 0013). It's non-normative,
but it records the constraints the design leans on.

- **Surfaces.** Two layer surfaces: `flowd-indicator` (always present when
  enabled) and `flowd-popup` (created on the first `show`, unmapped rather
  than destroyed after the fade so surface creation and the focus checks
  don't re-run every dictation, and without a tick while hidden), each
  with `gtk_layer_set_namespace()`, keyboard mode `NONE`, and the ADR 0003
  checks that the window really is a layer surface with that keyboard mode.
  They're separate because their input regions differ (popup: none) and the
  compositor blur rule targets them separately.
- **Protocol.** As in ADR 0013: `state`, `level`, `meta`, `warn` and `config`
  messages on stdin; `click` and `moved` events on stdout, with the daemon
  treating a click as `toggle`. Unknown types are ignored both ways.
- **Theme.** `[ui] theme`; `system` follows `gtk-interface-color-scheme`
  (GTK 4.20+), falling back to the portal's `color-scheme`, then dark. One of
  two CSS providers built from this file's tokens is loaded.
- **Popup text.** A custom widget drawing a `Pango::Layout` with attribute runs
  per zone, so each run can have its own alpha for the pending → polished
  crossfade and the self-correction highlight. A `Gtk::Label` can't animate
  part of its text.
- **Level meter.** A `Gtk::DrawingArea` with a tick callback and a one-pole
  low-pass per bar (τ ≈ 50 ms). Redrawn only while recording.
- **What it replaced.** The Python overlay this design replaced used
  `rgba(20,20,24,.88)`, 12 px radius, 15 px text and `#9ad2ff` for live. This
  design keeps the 15 px size and the three-zone model and replaces the
  colors and radius with tokens; `#9ad2ff` becomes `live`.
