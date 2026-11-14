import os, json
from playwright.sync_api import sync_playwright
URL=os.environ.get("F1_URL", "http://127.0.0.1:8010"); out={"pages":{}}; errs=[]; fails=[]
PAGES=['/','/predictions','/results','/calendar','/drivers','/drivers/VER?season=2026','/teams','/teams/red-bull?season=2026','/races/2026/17','/races/2026/18','/history','/how-it-works','/updates','/nope']
with sync_playwright() as p:
    b=p.chromium.launch()
    for w in (1440,1280,1024,768,390):
        ctx=b.new_context(viewport={'width':w,'height':900}); pg=ctx.new_page()
        pg.on('console',lambda m: errs.append((w,m.text[:160])) if m.type=='error' else None); pg.on('pageerror',lambda e: errs.append((w,str(e)[:160])))
        pg.on('requestfailed',lambda r: fails.append((w,r.url[-60:])))
        pg.on('response',lambda r: fails.append((w,r.status,r.url[-60:])) if r.status>=400 and '/img/' not in r.url and 'nope' not in r.url else None)
        res={}
        for path in PAGES:
            pg.goto(URL+path); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(350)
            ov=pg.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1')
            wide=pg.evaluate("(()=>{const m=document.querySelector('main');const r=m.getBoundingClientRect();return Math.round(r.width)})()")
            res[path]={'overflow':ov,'main_w':wide}
            if w in (1440,390) and path in ('/','/predictions','/drivers/VER?season=2026','/races/2026/17'): pg.screenshot(path=f'/tmp/ui_{w}_{path.strip("/").replace("/","_").replace("?","_") or "home"}.png',full_page=True)
        out['pages'][w]=res; ctx.close()
    b.close()
bad={w:[p for p,v in r.items() if v['overflow']] for w,r in out['pages'].items()}
print('overflow pages by width:',bad)
print('main width @1440:',{p:v['main_w'] for p,v in out['pages'][1440].items() if p in ('/','/predictions')})
print('console errors:',errs[:8]); print('failed/4xx requests:',fails[:8])
