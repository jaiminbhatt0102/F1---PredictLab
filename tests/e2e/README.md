# Browser checks (not collected by pytest)

Real Chromium against the real app, using a throwaway copy of the data so nothing in your project is written.

```powershell
pip install playwright; playwright install chromium
python tests/e2e/make_sandbox.py full                      # creates a data copy (edit the path inside for Windows)
$env:F1_PROJECT_ROOT="<sandbox folder>"; $env:AUTOMATION_ENABLED="0"
python run_app.py --no-browser                             # prints the address, e.g. http://127.0.0.1:8010
$env:F1_URL="http://127.0.0.1:8010"
python tests/e2e/check_widths.py     # every page at 1440, 1280, 1024, 768, 390 px: sideways overflow, console errors, failed requests
python tests/e2e/check_flows.py      # theme, navigation, back/forward, filters, driver and team pages, predictions, mobile menu
```

`check_flows.py` makes one real prediction in the sandbox. Both scripts print a summary; read it, they do not assert.
