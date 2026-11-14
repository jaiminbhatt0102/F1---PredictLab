# Photography

No photographs are shipped, because licensed motorsport photos cannot be bundled or hot-linked safely.
Until you add some, every image slot shows a designed fallback (race artwork, or a team-colour portrait with initials).

To add a photo you have the right to use:

1. Save it as a JPEG under the matching folder:
   - `hero/<circuit_id>.jpg`  (wide, about 1600x1000; circuit ids come from the app, e.g. `americas`)
   - `drivers/<CODE>.jpg`     (portrait, about 800x1000; e.g. `VER`)
   - `teams/<team-slug>.jpg`  (wide, about 1200x520; e.g. `red-bull`)
2. List it in `manifest.json`, for example:
   `{ "hero": ["americas"], "drivers": ["VER"], "teams": ["red-bull"] }`
3. Run `npm run build` (or just refresh in dev). Files not listed are never requested.

Keep files small (under about 250 KB each) and note the licence and credit in your own records.
