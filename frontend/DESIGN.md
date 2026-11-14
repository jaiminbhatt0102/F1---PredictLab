# Design decisions

**Direction.** A race-weekend publication, not a dashboard: full-width page, a top navigation like a sports site, one editorial hero per Grand Prix, tables for data. Inspired by the structure of formula1.com (header, hero, standings and calendar rows); nothing is copied, and the site has its own marks and artwork.

**Colour.** Dark is the default for everyone: graphite `#0e0f11`, warm white text, racing red `#e10600` only for the primary action, the selected state and key accents. Light is a separate design on a warm paper canvas (`#f5f2ea`), not inverted. Green and amber appear only as status and always with a word or icon. Team colours are tiny accents (a bar or dot), never page colours.

**Type.** System fonts only (nothing to download). Bahnschrift on Windows (falls back to Arial Narrow) for headings and numbers, uppercase and condensed; the system sans for reading text. Numbers use tabular figures.

**Layout.** One shell: sticky header, a page container that fills the viewport up to 1760 px with fluid gutters, a two-column grid (content plus aside) only where the aside has real content, collapsing below 1100 px. The header menu collapses below 1240 px. Tables scroll inside their own container and hide secondary columns on phones.

**Honesty rules in the UI.** Results and predictions never share a table. Missing data shows "–" or a plain sentence, never zero. No countdown without a timestamp. No claim of automatic updates unless the backend says they are running. History is read-only.

**Avoided on purpose.** Glass effects, glows, decorative charts, repeated identical card rows (driver and team directories are the only grids), fake telemetry, fixed-width columns that leave empty space.
