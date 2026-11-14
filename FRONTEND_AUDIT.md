# Frontend audit and verification (v0.3.0)

## What the app is
A race-weekend companion for people who follow Formula 1, not for engineers. Seven pages: **This weekend**, **Predictions**, **Results**, **Prediction history**, **Drivers & teams**, **How it works**, **Updates**. No model scores or technical terms appear anywhere (a browser check scans every page for them). All numbers come from the API; offline, the app shows a clear "can't reach the backend" message and no sample data.

## Verified (v0.4 redesign, headless Chromium on Linux, real API, copy of your data)
- Every page at 1440, 1280, 1024, 768 and 390 px: no sideways scroll, no console errors, no failed requests.
- Dark default (even when the system prefers light); light theme works and is remembered; navigation with real URLs, back/forward, old `#/` links redirected, custom 404.
- Season and Grand Prix selection through the address; prediction made, saved, filtered by driver and team, sorted; driver and team pages with race-by-race data; calendar and race pages; history and comparison; Updates actions and confirmation dialog.
- Mobile menu opens, closes on navigation and on Escape.
- `npm run build` strict TypeScript passes; `npm audit` reports 0 vulnerabilities (Vite upgraded 6.3.5 to 6.4.4); backend tests pass.

## Not verified
Windows, Firefox, Safari, screen readers, real internet access to the data sources, and licensed photography (none is bundled; designed fallbacks are shown).

## Manual checklist
1. Run `python run_app.py`. The browser opens at the address it prints.
2. This weekend: hero, session timeline, featured prediction (or an honest empty state), standings, calendar preview, weather, readiness.
3. Change the Grand Prix in the bar; the address and every panel follow.
4. Predictions: stages show Ready / Waiting / Already happened; make a prediction; search a driver; filter a team; download the spreadsheet.
5. Drivers, then a driver, then their team, then a race: every link works and back returns where you were.
6. Toggle the theme (sun/moon button), reload: the choice stays.
7. Close the app window and refresh: a clear message with Try again, no numbers.
8. Narrow the window to a phone: menu button works, nothing scrolls sideways.

## Pre-launch checklist (this is a private, local app, so public-website items are marked accordingly)
| # | Item | Status |
|---|---|---|
| 1 | Custom 404 | Done: unknown addresses show an in-app page titled "Page not found". The server returns the app for non-API paths so refreshes and shared links work. |
| 2 | Favicons | Done: .ico, SVG, Apple touch, 192/512 and maskable icons, manifest. Placeholder mark made from the brand slashes. Replace with an official logo if you have one. |
| 3 | Loading skeleton and empty states | Done on every data view; separate error state with retry. |
| 4 | Toast notifications | Done (saved prediction, update started/finished/failed; announced politely to screen readers). |
| 5 | Reduced motion | Done (skeleton shimmer, toasts, menu, spinners). |
| 6 | Social sharing image | N/A: not published publicly. Text OG tags added. |
| 7 | Event tracking | N/A by choice: no analytics. Nothing is sent anywhere except to your own backend. |
| 8 | Cookie consent | N/A: no cookies and no trackers. The only stored item is your theme choice (`localStorage`, this device only), which is not personal data. |
| 9 | Security headers | Done: backend and dev/preview servers send nosniff, frame deny, no-referrer, no-store (API); production build embeds a strict CSP limited to your API address. |
| 10 | Contact form | N/A: no public audience or mail service. |
| 11 | Unique titles and descriptions | Done: each page sets its own title; one description. |
| 12 | Open Graph | Done (text only). |
| 13 | Sitemap | N/A (private, in-page routes). |
| 14 | robots.txt | Done: disallow all, plus noindex meta, because this is a private tool. |
| 15 | Canonical URLs | N/A (no public address). |
| 16 | Structured data | N/A. |
| 17 | Breadcrumbs | N/A; detail pages have a back link. |
| 18 | Internal linking | Done: home, predictions, results, history and updates link to each other. |
| 19 | WebP images | N/A: no raster images in the interface. |
| 20 | Lazy loading | N/A: no images or embeds. |
| 21 | Faster fonts | Done by design: system fonts only (Bahnschrift on Windows), nothing to load. |

If you ever host it publicly: add authentication or keep it on a private network (the API can start updates and retrain models), set real canonical/OG URLs, a sitemap, and serve it over HTTPS.
