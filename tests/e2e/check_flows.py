import os, json
from playwright.sync_api import sync_playwright
URL=os.environ.get("F1_URL", "http://127.0.0.1:8010"); out={}; errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1440,'height':900}, color_scheme='light'); pg=ctx.new_page()
    pg.on('console',lambda m: errs.append(m.text[:140]) if m.type=='error' else None); pg.on('pageerror',lambda e: errs.append(str(e)[:140]))
    pg.goto(URL+'/'); pg.wait_for_selector('#hero-title'); out['default_theme_with_light_os']=pg.evaluate('document.documentElement.dataset.theme')
    pg.screenshot(path='/tmp/f_home_dark.png')
    pg.click('button[aria-label^="Switch to light"]'); out['after_toggle']=pg.evaluate('document.documentElement.dataset.theme'); pg.screenshot(path='/tmp/f_home_light.png')
    pg.reload(); pg.wait_for_selector('#hero-title'); out['theme_persists']=pg.evaluate('document.documentElement.dataset.theme')
    pg.click('button[aria-label^="Switch to dark"]')
    # nav + back/forward
    for label in ['Predictions','Results','Calendar','Drivers','Teams','History','How it works','Updates']:
        pg.click(f'.main-nav >> text={label}'); pg.wait_for_load_state('networkidle'); out.setdefault('nav',[]).append((label,pg.url.replace(URL,''), pg.title()))
    pg.go_back(); pg.go_back(); out['back_twice']=pg.url.replace(URL,''); pg.go_forward(); out['forward']=pg.url.replace(URL,'')
    # selection persists via URL
    pg.goto(URL+'/results?season=2026&round=17'); pg.wait_for_selector('#actual-h'); out['results_rows']=pg.locator('table.data tbody tr').count()
    pg.select_option('#gp-select','16'); pg.wait_for_timeout(700); out['gp_change_url']=pg.url.replace(URL,''); out['rows_after']=pg.locator('table.data tbody tr').count()
    pg.click('.segmented >> text=Qualifying'); pg.wait_for_timeout(500); out['quali_url']=pg.url.replace(URL,'')
    # driver link from results
    pg.click('.segmented >> text=Race'); pg.wait_for_selector('table.data tbody tr a'); pg.click('table.data tbody tr a >> nth=0'); pg.wait_for_selector('#drv-h'); out['driver_page']=pg.inner_text('#drv-h'); pg.screenshot(path='/tmp/f_driver.png',full_page=True)
    out['driver_rows']=pg.locator('table.data tbody tr').count()
    pg.click('.team-chip'); pg.wait_for_selector('#team-h'); out['team_page']=pg.inner_text('#team-h'); out['team_rows']=pg.locator('table.data tbody tr').count(); pg.screenshot(path='/tmp/f_team.png',full_page=True)
    # prediction flow + filters
    pg.goto(URL+'/predictions?season=2026&round=18'); pg.wait_for_selector('.stages'); pg.click('.make .btn'); pg.wait_for_selector('table.data tbody tr',timeout=20000)
    out['pred_rows']=pg.locator('table.data tbody tr').count(); pg.fill('input[type=search]','ver'); pg.wait_for_timeout(300); out['pred_search_rows']=pg.locator('table.data tbody tr').count()
    pg.fill('input[type=search]',''); pg.select_option('.filters select','Ferrari'); pg.wait_for_timeout(300); out['pred_team_rows']=pg.locator('table.data tbody tr').count()
    pg.screenshot(path='/tmp/f_pred.png',full_page=True)
    # history shows it
    pg.goto(URL+'/history'); pg.wait_for_selector('.cards'); out['history_cards']=pg.locator('.cards li').count()
    # race page
    pg.goto(URL+'/races/2026/17'); pg.wait_for_selector('#hero-title'); pg.wait_for_load_state('networkidle'); out['race_page']=pg.inner_text('#hero-title'); pg.screenshot(path='/tmp/f_race.png',full_page=True)
    # old hash links still work
    pg.goto(URL+'/#/predictions?season=2026&round=18'); pg.wait_for_selector('.stages'); out['old_hash_link_becomes']=pg.url.replace(URL,'')
    # mobile menu
    m=b.new_context(viewport={'width':390,'height':844}).new_page(); m.goto(URL+'/'); m.wait_for_selector('#hero-title'); m.click('.menu-btn'); m.wait_for_timeout(300); out['mobile_menu_links']=m.locator('.mobile-nav a').count(); m.screenshot(path='/tmp/f_mobile_menu.png')
    m.click('.mobile-nav >> text=Drivers'); m.wait_for_selector('.driver-grid'); out['menu_closes_after_nav']=not m.evaluate("document.querySelector('.mobile-nav').classList.contains('open')"); m.screenshot(path='/tmp/f_mobile_drivers.png',full_page=True)
    out['console_errors']=errs; b.close()
print(json.dumps(out,indent=1,ensure_ascii=False))
