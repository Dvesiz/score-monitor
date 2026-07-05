#!/usr/bin/env python3
"""诊断：查看成绩页面的表格结构"""
import asyncio, sys, json, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import ddddocr
from playwright.async_api import async_playwright

async def main():
    ocr = ddddocr.DdddOcr(show_ad=False)
    p = await async_playwright().start()
    b = await p.chromium.launch(headless=True, args=['--no-sandbox'])
    ctx = await b.new_context(viewport={'width':1280,'height':800})
    page = await ctx.new_page()

    # --- Login ---
    await page.goto('http://jwgl.jsut.edu.cn/xs_main.aspx?xh=2023144106', wait_until='networkidle')
    await page.wait_for_timeout(2000)

    code_img = await page.query_selector('#icode, img[src*="CheckCode"]')
    raw = await code_img.screenshot()
    code = ocr.classification(raw)
    print(f'Captcha: {code}')

    await page.fill('#txtUserName', '2023144106')
    await page.fill('#TextBox2', 'Dhy3115190838')
    await page.fill('#txtSecretCode', code)
    await page.click('#Button1')
    await page.wait_for_timeout(5000)
    print(f'After login URL: {page.url}')
    print('Login OK:', not await page.query_selector('#txtUserName'))

    # --- Navigate to score ---
    for f in page.frames:
        try:
            txt = await f.inner_text('body') if await f.query_selector('body') else ''
            if '信息查询' in txt:
                await f.click('a:has-text("信息查询")')
                await page.wait_for_timeout(1500)
                await f.click('a:has-text("成绩查询")')
                await page.wait_for_timeout(2000)
                print(f'Navigated in frame: {f.url[:60]}')
                break
        except:
            pass
    await page.wait_for_timeout(2000)

    # --- Query scores ---
    for f in page.frames:
        try:
            txt = await f.inner_text('body') if await f.query_selector('body') else ''
            if '2025-2026' in txt or '学年' in txt:
                sel = await f.query_selector('select[id*="ddlXN"], select[name*="ddlXN"]')
                if sel:
                    await sel.select_option(label='2025-2026')
                    await page.wait_for_timeout(500)
                sel2 = await f.query_selector('select[id*="ddlXQ"], select[name*="ddlXQ"]')
                if sel2:
                    await sel2.select_option(label='2')
                    await page.wait_for_timeout(500)
                btn = await f.query_selector('input[value*="学期"]')
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    print(f'Clicked query button in frame: {f.url[:60]}')
                break
        except:
            pass

    await page.wait_for_timeout(3000)

    # --- Dump all tables ---
    all_frames = page.frames
    print(f'\nTotal frames: {len(all_frames)}')
    for fi, f in enumerate(all_frames):
        try:
            furi = f.url[:80]
            tables = await f.query_selector_all('table')
            print(f'\n=== Frame[{fi}] {furi} ===')
            print(f'  Tables: {len(tables)}')
            for ti, t in enumerate(tables):
                rows = await t.query_selector_all('tr')
                print(f'  Table[{ti}]: {len(rows)} rows')
                for ri, r in enumerate(rows[:8]):
                    cells = await r.query_selector_all('td, th')
                    texts = []
                    for ci, c in enumerate(cells):
                        txt = (await c.inner_text()).strip().replace('\n',' ')[:40]
                        texts.append(f'[{ci}]{txt}')
                    print(f'    R{ri}: {" | ".join(texts)}')
        except Exception as e:
            print(f'  Frame[{fi}] error: {e}')

    # Save page HTML for reference
    for f in all_frames:
        try:
            html = await f.content()
            if 'dgrd' in html.lower() or 'datagrid' in html.lower() or '成绩' in html:
                with open('data/score_frame.html', 'w', encoding='utf-8') as fh:
                    fh.write(html)
                print(f'\nSaved score frame HTML to data/score_frame.html ({len(html)} bytes)')
                break
        except:
            pass

    await b.close()
    await p.stop()

asyncio.run(main())
