# DESIGN.md — TripoSR Studio

> A plain-text design system for the TripoSR web experience. Drop this file into any
> project (or paste it into your AI coding agent) to generate UI that matches the
> **TripoSR Studio** look: a dark, precision-engineered render viewport with an
> iridescent violet→cyan signature drawn from the normal/depth maps of 3D rendering.
>
> Format follows the [awesome-design-md](https://github.com/voltagent/awesome-design-md)
> convention: nine sections, semantic tokens, agent-readable.

---

## 1. Visual Theme & Atmosphere

TripoSR Studio feels like standing inside a render viewport. The canvas is near-black
graphite so 3D output and imagery pop; chrome recedes. The mood is **technical, calm,
and confident** — a professional tool, not a toy.

- **Keywords:** viewport-dark, iridescent, engineered, quiet, high-contrast output.
- **Signature move:** a violet→cyan gradient (the colors of a normal map) used sparingly
  for the primary action, active states, and the generation "beam."
- **Density:** generous. One primary task per screen (drop an image → get a mesh).
- **Motion:** minimal and physical. Things ease in, they don't bounce. Progress is a
  sweeping gradient beam, never a spinner-for-spinner's-sake.
- **Voice:** terse and precise. "Generate," "Drop image," "Exporting GLB" — no fluff.

---

## 2. Color Palette & Roles

Semantic tokens first — reference these names, not raw hex, in components.

| Token                 | Hex        | Role                                                        |
| --------------------- | ---------- | ---------------------------------------------------------- |
| `--bg-viewport`       | `#0B0C0E`  | App background — the near-black "viewport"                  |
| `--bg-surface`        | `#16181D`  | Cards, panels, the drop zone                                |
| `--bg-surface-raised` | `#1E2128`  | Hover surfaces, popovers, raised controls                  |
| `--bg-inset`          | `#101216`  | Inset wells, code blocks, input fields                     |
| `--border-hairline`   | `#262A31`  | Default 1px borders, dividers                              |
| `--border-strong`     | `#3A404A`  | Focused/active borders                                     |
| `--text-primary`      | `#F4F5F7`  | Headings, primary copy                                     |
| `--text-secondary`    | `#9BA1AC`  | Labels, secondary copy, metadata                          |
| `--text-muted`        | `#5C636E`  | Placeholders, disabled, hints                             |
| `--accent-violet`     | `#7C5CFF`  | Signature start — primary action, active                  |
| `--accent-cyan`       | `#22D3EE`  | Signature end — highlights, links, focus ring             |
| `--accent-ink`        | `#0B0C0E`  | Text/icon color on top of the bright gradient             |
| `--success`           | `#34D399`  | Success (mesh ready)                                       |
| `--warning`           | `#FBBF24`  | Warnings (large file, slow cold-start)                    |
| `--danger`            | `#F87171`  | Errors (failed job, bad key)                              |

**Signature gradient** (use for primary button fill, active tab underline, progress beam):

```
--gradient-signature: linear-gradient(135deg, #7C5CFF 0%, #22D3EE 100%);
```

**Rules**

- Exactly one gradient per view carrying the primary action. Everything else is flat.
- Semantic colors (success/warning/danger) appear only in status, never decoration.
- Text on the gradient is always `--accent-ink`, never white, to hold AA contrast.

---

## 3. Typography Rules

Two families: a clean grotesque for UI, a monospace for technical values (dimensions,
IDs, hex, byte counts).

- **UI / body:** `Inter`, `-apple-system`, `system-ui`, `sans-serif`
- **Mono / technical:** `"JetBrains Mono"`, `"SF Mono"`, `ui-monospace`, `monospace`

| Style        | Size / Line   | Weight | Tracking  | Use                                  |
| ------------ | ------------- | ------ | --------- | ------------------------------------ |
| Display      | 40 / 44 px    | 600    | -0.02em   | Hero title                           |
| H1           | 28 / 34 px    | 600    | -0.01em   | Section titles                       |
| H2           | 20 / 28 px    | 600    | -0.01em   | Panel headers                        |
| Body         | 15 / 24 px    | 400    | 0         | Default copy                         |
| Body-strong  | 15 / 24 px    | 500    | 0         | Emphasis inline                      |
| Label        | 13 / 16 px    | 500    | 0.01em    | Form labels, buttons                 |
| Caption      | 12 / 16 px    | 400    | 0.01em    | Metadata, hints                      |
| Mono         | 13 / 20 px    | 400    | 0         | Endpoint IDs, dimensions, hex, sizes |

**Rules**

- Weights used: 400, 500, 600. Never 700+ (studio is quiet, not shouty).
- Any number a user might copy or compare (IDs, px, MB) is set in **Mono**.
- Headings use tight tracking; body stays at 0.

---

## 4. Component Stylings

### Buttons

| Variant   | Fill                          | Text            | Border               | Radius | Height |
| --------- | ----------------------------- | --------------- | -------------------- | ------ | ------ |
| Primary   | `--gradient-signature`        | `--accent-ink`  | none                 | 10px   | 44px   |
| Secondary | `--bg-surface-raised`         | `--text-primary`| `--border-hairline`  | 10px   | 44px   |
| Ghost     | transparent                   | `--text-secondary` | none              | 10px   | 40px   |
| Danger    | transparent                   | `--danger`      | `1px --danger @ 40%` | 10px   | 40px   |

- **States:** hover raises brightness ~6% (primary) or swaps to `--bg-surface-raised`
  (secondary); active drops 1px; disabled = 40% opacity, no pointer.
- **Focus:** 2px `--accent-cyan` ring at 60% opacity, 2px offset. Never remove focus.
- Label in Label style (13px/500). Icon + text gap = 8px.

### Drop Zone (hero component)

- Full-width panel, `--bg-surface`, `2px dashed --border-hairline`, radius 16px, min-height 320px.
- On drag-over: border becomes `2px solid`, painted with `--gradient-signature`
  (use a gradient border), and a faint violet glow (`box-shadow: 0 0 0 4px rgba(124,92,255,.12)`).
- Center content: upload glyph (32px, `--text-muted`), "Drop image or click to browse"
  (Body, `--text-secondary`), "PNG · JPG · WEBP" (Caption, `--text-muted`).

### Cards / Panels

- `--bg-surface`, `1px --border-hairline`, radius 14px, padding 20–24px.
- Header row: H2 title left, meta/actions right, 16px below before content.

### Inputs / Text fields

- `--bg-inset`, `1px --border-hairline`, radius 10px, height 44px, padding 0 14px.
- Text `--text-primary`; placeholder `--text-muted`. Focus: border → `--border-strong`
  plus 2px cyan ring. Mono variant for keys/IDs.

### Status Pill

- Rounded-full, 24px tall, padding 0 10px, Caption weight 500.
- Idle: `--bg-surface-raised` / `--text-secondary`. Running: violet tint bg
  `rgba(124,92,255,.15)` / `--accent-violet`. Success: `rgba(52,211,153,.15)` /
  `--success`. Error: `rgba(248,113,113,.15)` / `--danger`.

### 3D Viewer

- Fills its card, `--bg-inset`, radius 14px, inset shadow to feel recessed.
- Subtle radial vignette from center so the mesh reads as lit in a studio.

---

## 5. Layout Principles

- **Spacing scale (4px base):** 4, 8, 12, 16, 20, 24, 32, 40, 56, 72. Use these only.
- **Container:** max-width 1200px, centered, 24px side gutters (16px on mobile).
- **Primary layout:** two columns on desktop — left = input (drop zone + controls),
  right = output (3D viewer). Collapses to a single stacked column below 900px.
- **Rhythm:** 24px between sibling panels; 16px between label and control; 8px between
  an icon and its label.
- **Alignment:** left-aligned throughout. Center only the empty drop-zone prompt.

---

## 6. Depth & Elevation

Depth comes from **surface lightness + hairline borders + soft shadows**, never heavy
drop shadows. Four levels:

| Level | Use                     | Surface               | Shadow                                  |
| ----- | ----------------------- | --------------------- | --------------------------------------- |
| 0     | App background          | `--bg-viewport`       | none                                    |
| 1     | Cards, panels           | `--bg-surface`        | `0 1px 2px rgba(0,0,0,.4)`              |
| 2     | Hover / raised controls | `--bg-surface-raised` | `0 4px 16px rgba(0,0,0,.5)`            |
| 3     | Popovers, menus, modals | `--bg-surface-raised` | `0 12px 40px rgba(0,0,0,.6)`           |

- The only colored glow allowed is the violet drop-zone active state and the primary
  button hover — both from the signature palette, both subtle (≤12% alpha).
- Inset elements (inputs, viewer) use `inset 0 1px 0 rgba(255,255,255,.02)` to catch a
  hairline of light on the top edge.

---

## 7. Do's and Don'ts

**Do**

- Keep the canvas near-black so imagery and meshes are the brightest thing on screen.
- Reserve the signature gradient for the single primary action and active state.
- Set every technical value (IDs, px, MB, hex) in Mono.
- Use the 4px spacing scale and the four elevation levels — nothing off-scale.
- Keep motion physical: ease-out, 150–250ms, no bounce.

**Don't**

- Don't use pure white (`#FFFFFF`) text or pure black (`#000000`) surfaces — use tokens.
- Don't put more than one gradient in a view, and never gradient-fill body text.
- Don't use weights ≥700 or add decorative drop shadows.
- Don't show a bare spinner; use the sweeping gradient progress beam.
- Don't stack colored glows — one accent glow per screen, max.

---

## 8. Responsive Behavior

| Breakpoint     | Width      | Behavior                                                        |
| -------------- | ---------- | -------------------------------------------------------------- |
| Mobile         | < 600px    | Single column; drop zone min-height 220px; 16px gutters        |
| Tablet         | 600–899px  | Single column; controls in a 2-up grid                         |
| Desktop        | 900–1199px | Two columns (input / output), 24px gap                         |
| Wide           | ≥ 1200px   | Two columns centered in 1200px container                       |

- **Touch targets:** minimum 44×44px for anything tappable.
- **Type:** Display drops to 32/36px below 600px; body stays 15px for readability.
- **3D viewer:** keeps a 1:1 aspect on mobile, 4:3 on desktop; controls stay reachable.

---

## 9. Agent Prompt Guide

Quick reference for an AI agent generating TripoSR Studio UI. Paste alongside a task.

```
THEME     Dark render-viewport studio. Near-black canvas, iridescent violet→cyan
          signature (normal-map colors) used ONLY for the primary action + active state.

COLOR     bg #0B0C0E · surface #16181D · raised #1E2128 · inset #101216
          border #262A31 · text #F4F5F7 / #9BA1AC / #5C636E
          accent violet #7C5CFF → cyan #22D3EE  (gradient 135deg)
          success #34D399 · warning #FBBF24 · danger #F87171
          Text on gradient = #0B0C0E (never white).

TYPE      UI: Inter. Technical values: JetBrains Mono. Weights 400/500/600 only.
          Display 40/600 · H1 28/600 · H2 20/600 · Body 15/400 · Label 13/500 · Mono 13.
          Any copyable number (ID, px, MB, hex) → Mono.

SPACE     4px scale: 4 8 12 16 20 24 32 40 56 72. Container max 1200px, 24px gutters.
          Layout: two columns desktop (input left / 3D output right) → stacked < 900px.

RADIUS    inputs/buttons 10px · cards 14px · drop zone 16px · pills full.

SHADOW    4 levels, soft & dark. Colored glow only on drop-zone-active + primary hover,
          ≤12% alpha. No heavy drop shadows.

DO        one gradient per view · Mono for values · near-black canvas · 44px targets ·
          ease-out 150–250ms motion.
DON'T     pure white/black · multiple gradients · weight ≥700 · bare spinners ·
          stacked glows.

COMPONENT Primary button = gradient fill, ink text, 44px, radius 10.
          Drop zone = dashed hairline → solid gradient border + violet glow on drag.
          Progress = sweeping gradient beam, not a spinner.
```
