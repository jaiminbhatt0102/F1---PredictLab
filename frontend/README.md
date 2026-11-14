# F1 PredictLab frontend

React 19, TypeScript, Vite, lucide-react. No router or state library: a small History-API router (`src/router.tsx`) and one shared selection context (`src/data.tsx`).

## Run (Windows PowerShell)

Normal use needs no Node.js: from the project folder run `python run_app.py` (it serves the built `frontend/dist`).

To change the frontend:

```powershell
cd frontend
npm ci
npm run build                          # type-checks, then builds into dist/
# live editing, with the engine running on 8010 (python run_app.py --port 8010 --no-browser):
$env:API_PORT=8010; npm run dev        # open http://127.0.0.1:5173 (it proxies /api to the engine)
```

Settings: `VITE_API_URL` (leave empty; the app talks to the address that served it). No secrets belong in `VITE_` variables.

## Pages

`/` this weekend · `/predictions` · `/results` · `/calendar` · `/races/:season/:round` · `/drivers` · `/drivers/:code` · `/teams` · `/teams/:slug` · `/history` · `/history/:id` · `/how-it-works` · `/updates`. Season and Grand Prix live in the address (`?season=2026&round=18`), so every view can be refreshed, shared and navigated with back/forward. Old `#/page` links are redirected.

## Structure

`src/layout` header, footer, context bar · `src/art` photo-or-fallback, race artwork · `src/components` shared UI (tables, states, prediction view, standings, race hero) · `src/pages` one file per route (lazy-loaded) · `src/api` typed client and types · `src/styles.css` the design system (tokens for dark and light).

## Photography

None is bundled (licensed photos cannot be shipped or hot-linked safely). Every slot has a designed fallback. See `public/img/README.md` to add your own; images not listed in `public/img/manifest.json` are never requested.

## Checks

`npm run build` (strict TypeScript), `npm audit` (0 vulnerabilities with Vite 6.4.4), and the browser scripts in `../tests/e2e`.
