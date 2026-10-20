# Design system — SnowUI

The web app (`apps/web`) follows the **SnowUI** design system by ByeWind
([Figma kit](https://www.figma.com/design/PAA0JKidFMVK44KRRWB1zL/SnowUI)).
Token values are transcribed verbatim from the official source
[`SnowUI/home`](https://github.com/SnowUI/home) (`snowui-themes.css`,
`snowui-utilities.css`, v1.2.0) into
[`apps/web/src/styles/snowui-tokens.css`](../apps/web/src/styles/snowui-tokens.css).
Do not edit token values there; add app-level aliases in `styles.css`.

## Color palette (Light)

| Token | Value | Use |
| --- | --- | --- |
| `--black-100` / `--primary` / `--foreground` | `#000000` | Text, primary buttons, active indicator |
| `--black-80` | `#000000CC` | Secondary body text |
| `--black-40` | `#00000066` | Labels, captions, placeholders |
| `--black-20` | `#00000033` | Disabled, table header rule, scrollbar |
| `--black-10` | `#0000001A` | Dividers, input borders |
| `--black-4` | `#0000000A` | Hover/active fills, secondary buttons, segmented track |
| `--background-1` | `#FFFFFF` | Page, sidebar, right panel |
| `--background-2` | `#F9F9FA` | Cards |
| `--background-3` | `#FFFFFFE5` | Glass popovers |
| `--color-1` | `#E6F1FD` | KPI card (odd) |
| `--color-2` | `#EDEEFC` | KPI card (even), AI surfaces |
| `--logo-1` | `#4C98FD` | Brand mark |
| `--logo-2` | `#4F507F` | Brand ink (AI text) |

Secondary colors: purple `#B899EB`, indigo `#ADADFB`, blue `#7DBBFF`,
cyan `#A0BCE8`, mint `#6BE6D3`, green `#71DD8C`, yellow `#FFCC00`,
orange `#FFB55B`, red `#FF4747`. Use them for dots, fills and accents. For
status **text**, `styles.css` derives darker inks (`--success`, `--caution`,
`--red`, `--blue`) with `color-mix(… , black)` so they pass WCAG AA on white.

A `[theme="dark"]` token set is included but not wired up yet.

## Typography

Inter (variable, Latin + Vietnamese subsets via `@fontsource-variable/inter`).
Weights: 400 regular, 600 semibold. Root size is responsive
`clamp(14px, 0.875vw + 10px, 16px)`; all scales are rem.

| Token | Size / line height |
| --- | --- |
| `--text-12` | 12 / 16 |
| `--text-14` | 14 / 20 (body default) |
| `--text-16` | 16 / 24 |
| `--text-18` | 18 / 28 |
| `--text-24` | 24 / 32 (page titles, results) |
| `--text-32` … `--text-64` | 32/40, 48/58, 64/78 |

## Spacing, radius, effects

- Spacing (`--space-*`): 4, 8, 12, 16, 20, 24, 28, 40, 48.
- Radius (`--radius-*`): 4, 8, 12 (controls), 16 (cards), 20, 24 (login), 32, full.
- Shadows: `--shadow-drop-2` (raised segmented item), `--shadow-glass-1`
  (login), `--shadow-glass-2` + `--blur-40` (popovers), `--shadow-focus`.
- Gradient sheen `--gradient-sheen` is layered over a color for "glass" fills.

## Layout & component conventions

- Shell: 212px sidebar (`background-1`, right border `black-10`), 68px top bar,
  28px content padding, right panel with left border.
- Sidebar item: 40px tall, 12px radius; active = `black-4` fill plus a
  4×16px black pill on the left.
- Cards: `background-2`, 16px radius, 24px padding, no border.
- KPI cards alternate `color-1` / `color-2`.
- Buttons: primary = black fill + white text; secondary = `black-4` fill;
  12px radius.
- Segmented controls: `black-4` track with 4px padding; active item is white
  with `shadow-drop-2`.
- Badges: full-radius pill, tinted fill, 6px colored dot.
- Camera overlays: static black 80% + blur 40, 8px radius.

## Page structure (all tabs)

Applies Apple's wayfinding / grouping principles on top of SnowUI:

1. **Top bar** (sticky, translucent `background-3` + blur): breadcrumb
   `Workspace › Tab`, a sidebar toggle, and the live AI status pill. Hidden ≤1020px,
   where the horizontal nav already shows the current tab.
2. **Notices** (`.workspace-notices`): demo/mock/metadata banners, grouped.
3. **Page intro**: 24px semibold title only (-0.01em tracking). No eyebrow or
   description lines; the breadcrumb already provides context.
4. **Content**: one shared left edge (28px gutter); cards follow the rules above.

### Nhận dạng (Recognize)

- Camera heading shows camera status (AI status appears there only ≤1020px,
  where the top bar is hidden).
- Camera off → a glass card in the stage: icon, one-line title, "Bật camera".
- The toolbar under the stage shows the capture mode as a visible segmented control
  (Thủ công / Tự động); the primary action ("Giữ để ký" + Space hint) sits
  far right and turns red with a pulse while recording.
- Result card: status pill in the heading, toned callout (info / warning / error),
  32px label, confidence meter (green ≥70%, yellow ≥40%, red below).
- Sentence stays above the result (an existing product decision covered by
  `App.test.tsx`).

### Motion

- Press feedback on pointer-down: `scale(0.97)`, 100ms.
- New surfaces "materialize" with `@starting-style` (opacity + scale 0.98).
- `prefers-reduced-motion` disables all of it; `prefers-reduced-transparency`
  makes glass surfaces solid; `prefers-contrast: more` darkens secondary text and
  outlines the cards.

## Text

Prefer one line per idea. No subtext under titles, empty states are a single
short line ("Chưa có kết quả"), and status shown elsewhere is not repeated.

## Icons

[Mage Icons](https://mageicons.com/) (Apache-2.0), 24px grid, 1.5px stroke.
`scripts/generate-mage-icons.mjs` reads `@iconify-json/mage` (dev dependency)
and writes `src/icons/index.tsx` with only the icons listed in its `ICONS` map.
To add an icon, add `ComponentName: "mage-name"` there and run `npm run icons`.
Do not use Mage's `x` icon (it is the X/Twitter logo); use `multiply`.

## Sidebar

- Width 180–360px (default 212), stored in `localStorage` (`vsign.sidebar`).
- Drag the right edge: tracks the pointer 1:1, rubber-bands past the limits,
  and collapses to the 68px icon rail if dragged left of 140px. Double-click
  resets the width.
- Keyboard on the handle: ←/→ (Shift = larger steps), Home/End, Enter toggles.
- The top-bar toggle switches between the full sidebar and the icon rail. Rail
  items keep their accessible names and tooltips.
- ≤1020px the sidebar becomes the horizontal nav; resize and rail do not apply.
