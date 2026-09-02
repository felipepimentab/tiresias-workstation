# Workstation interface

## Visual direction

The workstation uses a deliberately light appearance: a quiet gray sidebar,
white content surfaces, restrained borders, and charcoal primary actions. The
layout follows the clean, minimal character of Codex, with macOS conventions
for system typography, control proportions, keyboard focus, and dialogs.

The application keeps the platform's Qt style; it does not replace the macOS
style with Fusion or custom window chrome. Native combo-box arrows, scrolling,
menus, file dialogs, and window controls remain platform-owned. Shared button
and input styling gives the application consistent spacing and contrast.

## Why some controls previously appeared dark

Individual screens supplied partial stylesheets, usually setting only white
page backgrounds and selected control colors. Unstyled widgets continued to
inherit the operating system palette. With dark mode enabled, inputs, combo
popups, table headers, tabs, and disabled states could therefore disagree with
the surrounding light page. Some screens also used blue actions while others
used charcoal actions.

`presentation/theme.py` now owns both parts of the appearance:

- `light_palette()` defines active, inactive, and disabled roles, including
  input backgrounds, selected text, placeholders, tooltip surfaces, and buttons.
- `apply_light_theme(app)` requests Qt's light color scheme, retains the system
  typeface and platform style, and installs the shared application stylesheet.
- The entry point applies the theme before creating any windows. Standalone
  previews and Qt tests must do the same after constructing `QApplication`.

Qt documents that the color-scheme request is platform-dependent, while explicit
application palette entries survive system palette updates. Both mechanisms
are intentional here. See [Qt's color-scheme documentation](https://doc.qt.io/qt-6/qstylehints.html#colorScheme-prop).

## Screen overview

| Screen | Layout and behavior |
| --- | --- |
| Devices | Clear scan action, subtle connection badge, quiet discovery table, and separate connection controls. |
| Board information | Read-only identity and protocol details, selectable values, and wrapping for long device metadata. |
| DSP parameters | Fixed-column metadata with a resizable byte preview, plus a two-row editor and system monospace hex input. |
| Prescriptions | Consistent table selection, bounded profile-name width, full text in tooltips, and compact loading progress. |
| Audiogram fitting | Aligned field labels, light inputs and popups, centered numeric tables, readable target details, and compact local dates. |

Board information and DSP parameters use stacked pages controlled by the
sidebar, eliminating duplicate tab navigation. Full digests and original
timestamps remain accessible through details/tooltips or JSON exports. Delete
confirmation defaults to Cancel. Controls remain keyboard reachable, and focus
and errors are visibly distinct from disabled states.

The default window is 1180 × 820 logical pixels, with a 960 × 680 minimum.
Tables scroll at compact sizes instead of pushing actions outside the window.

## Offline visual regression checks

Tests use fake controller signals and temporary prescription storage. They
never construct a Bleak transport or communicate with a physical board.

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

To also produce screen previews in a chosen temporary directory:

```sh
TIRESIAS_UI_PREVIEW_DIR=/tmp/tiresias-ui-preview \
QT_QPA_PLATFORM=offscreen \
.venv/bin/python -m unittest discover -s tests -p test_presentation_theme.py -v
```

The preview suite starts with a simulated dark palette and covers every screen
at default and minimum sizes, empty and populated tables, disabled controls,
validation errors, keyboard focus, a rule popup, and a confirmation dialog.
It checks palette roles and action visibility as well as generating images.
Offscreen rendering verifies Qt content; macOS-native window decorations and
native file dialogs still require an on-screen platform check.

## Extending the UI

Keep color and control-state styling in `theme.py`, not on individual screens.
Reuse the standard margins (36 px horizontally, 32 px at the top), subdued
secondary text, 30 px control heights, and compact table styling. Use the
`fieldLabel` role for form labels and give each label a keyboard buddy. Preserve
tooltips or export access when presenting shortened technical values. Do not
remove keyboard focus indicators or replace native dialogs to obtain a custom
appearance.
