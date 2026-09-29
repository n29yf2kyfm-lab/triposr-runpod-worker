---
name: apple-premium-ui
description: Make a website or app UI look premium and Apple-like rather than AI-generated, and easy to use on a phone. Use when building or redesigning any page, dashboard, app screen or 3D viewer UI, when the user says "premium", "Apple-like", "not AI generated", "clean", "looks cheap", "not mobile friendly", "too many buttons", "bad user experience", or mentions Hick's law. It gives a concrete checklist: one job per screen, fewer choices, system-quality type and spacing, restrained colour, real depth, calm motion, 44 pt touch targets, and a phone-first pass that is checked in a real browser before shipping.
---

# Premium, Apple-like, not AI-generated

The Apple look is not the logo, a gradient or a glass blur. It comes from a set of
decisions that remove things. Apple's own Human Interface Guidelines name them
as **clarity, deference and depth**: the content leads, the interface steps back,
and layers explain where you are.

When a real brand's system fits the request, the `awesome-design` skill has
Apple's DESIGN.md (type scale, spacing, colours). Use it for exact values; use
this skill for the decisions.

## 1. One job per screen (Hick's law)

Decision time grows with the number of choices on screen. So:

- **Name the screen's one job** in five words before drawing anything. Every
  control that does not serve it moves to a secondary place (a sheet, a "More"
  menu, a second step).
- **Three to five primary choices at most.** Show one primary action, filled in
  the accent colour. Everything else is secondary (outline or plain text).
- **Progressive disclosure.** Show the next step when it becomes relevant, not
  before. A first-time visitor sees a short, guided path; the full toolset opens
  as they need it.
- **Group what remains.** Seven loose buttons read as clutter; two groups of
  three with a clear label read as a system.
- **Default to the common case.** Pre-select the likely choice so most users only
  confirm it.

## 2. Type does the work

- One sans-serif family in two or three weights. Prefer the platform font on
  apps (`-apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui`). Use a
  single characterful display face only for large headings, if at all.
- A strict scale, for example 13 / 15 / 17 / 22 / 28 / 34 / 48. Body text is 17 px
  on phones, never below 15. No text in the UI under 13 px.
- Tight tracking on big headings (`letter-spacing: -0.02em` at 34 px and above),
  normal on body. Line length 45 to 75 characters.
- Say things in the user's words, in sentence case. A button says exactly what it
  does ("Open bonnet", not "Proceed").

## 3. Space, alignment, restraint

- One spacing unit (4 or 8 px) and multiples of it only. Be generous: sections
  breathe at 48 to 96 px on desktop and 32 to 48 on phones.
- One column of alignment per section. Everything lines up to something.
- **One accent colour**, used only for the primary action and the current state.
  The neutrals are near-white or near-black grounds with two grey text tones.
  Semantic colours (success, warning, error) are separate and rare.
- No emoji as icons, no rainbow gradients, no card inside a card inside a card,
  no drop shadow on everything, no `rounded-lg` on every box by default.

## 4. Depth that means something

- Layers show hierarchy: a sheet slides over the page and dims it; a toolbar is
  translucent over content (`backdrop-filter: saturate(180%) blur(20px)` over a
  semi-opaque ground, with a solid fallback).
- Shadows are soft and large, with low opacity (for example
  `0 10px 30px rgba(0,0,0,.12)`), and only on things that float.
- Corner radii are consistent and concentric: an inner radius equals the outer
  radius minus the padding.

## 5. Motion is calm and purposeful

- 200 to 400 ms, ease-out for arrivals and ease-in-out for moves. Nothing
  bounces unless it is a physical object.
- Animate to explain a change of place (a sheet rising, a card expanding into
  a view), never for decoration.
- Honour `prefers-reduced-motion`: cut to the end state.

## 6. Phone first, thumb first

- Every tap target is at least 44 × 44 pt, with 8 pt between targets.
- Primary actions sit in the bottom third, where the thumb reaches. Keep the
  top for reading and status.
- Respect safe areas: `env(safe-area-inset-*)` on fixed bars.
- No horizontal page scroll at 360 px wide. No hover-only affordances. A long
  label wraps or shortens; it never clips.
- A 3D or canvas view gets the whole screen. Controls are few and float over it
  on translucent bars, and a single tap on the object is the main interaction.

## 7. Content and imagery

- Real content from the first draft. Never lorem ipsum.
- Large, high-quality imagery, or the product itself, is the hero. Cut stock
  decoration.
- Empty, loading and error states are designed too. They say what happened and
  what to do next.

## 8. Checklist before shipping

Do these in a real browser (Playwright is fine) at **360 × 780**, **390 × 844**
and **1440 × 900**. Look at the screenshots; do not judge from the source.

1. Can a first-time user tell the screen's one job in three seconds?
2. How many choices are visible at once? If more than five compete, cut or group them.
3. Is there exactly one filled primary action per view?
4. Are all tap targets at least 44 pt, with nothing clipped or overlapping at 360 px?
5. Is body text at least 15 px, with only one accent colour in use?
6. Does it work with touch alone: no hover, no right-click, no tiny drag handles?
7. Are the loading, empty and error states designed?
8. Does reduced motion still leave a usable page?

If any answer is no, fix it before calling the design done.
