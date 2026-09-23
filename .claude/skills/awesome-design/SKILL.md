---
name: awesome-design
description: Real brand design systems as DESIGN.md files (typography, colour, spacing, layout, components) for 74 sites including Apple, Stripe, Linear, Vercel, Notion, Tesla, BMW, Ferrari, Airbnb and Spotify. Use when building or restyling a web page, landing page or app UI and the user names a brand look ("make it look like Apple", "Stripe-style") or wants real-website typography and spacing instead of generic AI defaults.
---

# Awesome Design (DESIGN.md collection)

Vendored from [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)
(MIT, see LICENSE). Only the `DESIGN.md` files are kept; the upstream preview
HTML pages are not.

## How to use

1. Pick the system that matches the look asked for. The folders are in
   `design-md/<brand>/DESIGN.md`, for example `design-md/apple/DESIGN.md`,
   `design-md/stripe/DESIGN.md`, `design-md/linear.app/DESIGN.md`.
   List them with `ls .claude/skills/awesome-design/design-md`.
2. Read that one file in full before writing any CSS. It gives the type scale,
   font stacks, colour tokens, spacing, radii, shadows and component rules.
3. Build from its tokens. Precedence still applies: the user's own words, then
   the project's existing design system, then the DESIGN.md.
4. These describe publicly observable styles for reference. Do not copy a
   brand's logo, name or trademarked assets into a page that is not that brand's,
   and never make a page that could pass as the real company's site.

Pairs well with `taste-skill` and `impeccable` for the design pass, and with
`playwright-cli` to screenshot and check the result.
