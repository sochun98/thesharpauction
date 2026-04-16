"""
상가/근린생활시설 검색 POST 바디 캡처 스크립트
- 메인 페이지에서 상가 관련 탭/빠른검색 버튼 찾기
- POST 바디를 logs/ 폴더에 저장
"""
import time, json
from pathlib import Path
from playwright.sync_api import sync_playwright

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)

captured = {}

def on_request(req):
    if 'searchController' in req.url:
        captured['req_url'] = req.url
        captured['req_body'] = req.post_data or ''
        print(f'[REQUEST] {req.url}')
        print(f'  바디: {(req.post_data or "")[:400]}')

def on_response(resp):
    if 'searchController' in resp.url:
        try:
            body = resp.body().decode('utf-8', 'replace')
            captured['resp'] = body
            d = json.loads(body)
            total = d.get('data', {}).get('dma_pageInfo', {}).get('totalCnt', '?')
            items = d.get('data', {}).get('dlt_srchResult', [])
            util_dist = {}
            for it in items:
                lc = it.get('lclsUtilCd', '(none)')
                util_dist[lc] = util_dist.get(lc, 0) + 1
            print(f'[RESPONSE] total={total}, 용도분포={util_dist}')
        except Exception as e:
            print(f'[RESPONSE] 파싱오류: {e}')

def click_any_search(page):
    for sel in [
        "#mf_btn_quickSearchGds",
        "[id*='quickSearch']",
        "input[value*='조회']",
        "input[value*='검색']",
        "button:has-text('조회')",
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                print(f'  클릭: {sel}')
                el.first.click()
                return True
        except:
            pass
    return False

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
        viewport={'width': 1400, 'height': 900}
    )
    page = ctx.new_page()
    page.on('request', on_request)
    page.on('response', on_response)

    page.goto('https://www.courtauction.go.kr/pgj/index.on', wait_until='domcontentloaded', timeout=60000)
    try:
        page.wait_for_function("typeof scwin !== 'undefined'", timeout=20000)
    except:
        pass
    time.sleep(3)
    page.screenshot(path='debug_main_page.png')

    # 메인 페이지 전체 텍스트에서 상가/근린 관련 요소 찾기
    try:
        elems = page.evaluate("""
            Array.from(document.querySelectorAll('*'))
              .filter(e => {
                  const t = (e.innerText || e.value || e.title || e.getAttribute('onclick') || '').trim();
                  return (t.includes('상가') || t.includes('근린') || t.includes('비주거') || t.includes('기타건물'))
                      && t.length < 50 && e.children.length === 0;
              })
              .map(e => ({id: e.id, tag: e.tagName, text: (e.innerText||e.value||'').trim().slice(0,30)}))
              .slice(0, 20)
        """)
        print('상가/근린 관련 요소:')
        for el in elems: print(f'  {el}')
    except Exception as e:
        print(f'요소 탐색 실패: {e}')

    # 전체 버튼/링크 목록
    try:
        all_btns = page.evaluate("""
            Array.from(document.querySelectorAll('input[type=button], button, a'))
              .map(e => ({id: e.id, text: (e.value||e.innerText||'').trim().slice(0,20)}))
              .filter(x => x.text)
              .slice(0, 50)
        """)
        print('전체 버튼:')
        for b in all_btns: print(f'  {b}')
    except:
        pass

    # 경기도, 수원시 영통구 선택
    print('\n지역 선택...')
    try:
        sd = page.locator('#mf_sbx_rletRpdtSdLst')
        for i, opt in enumerate(sd.locator('option').all()):
            if '경기' in opt.inner_text():
                sd.select_option(index=i)
                print(f'  경기도 선택')
                break
        time.sleep(2)
        sgg = page.locator('#mf_sbx_rletRpdtSggLst')
        for i, opt in enumerate(sgg.locator('option').all()):
            if '영통' in opt.inner_text():
                sgg.select_option(index=i)
                print(f'  수원시 영통구 선택')
                break
        time.sleep(1)
    except Exception as e:
        print(f'  지역 선택 실패: {e}')

    page.screenshot(path='debug_region_selected.png')

    # 빠른검색 클릭
    print('\n검색 클릭...')
    new_pages = []
    ctx.on('page', lambda pg: new_pages.append(pg))
    click_any_search(page)
    time.sleep(3)

    # 새 탭 처리
    if new_pages:
        np = new_pages[-1]
        print(f'새 탭: {np.url[:80]}')
        time.sleep(3)
        # 새 탭에서도 요청 감지
        np.on('request', on_request)
        np.on('response', on_response)
        for sel in ["[id$='btn_srch']", "input[value*='조회']", "input[value*='검색']"]:
            try:
                el = np.locator(sel)
                if el.count() > 0:
                    el.first.click()
                    print(f'  새 탭 검색 클릭: {sel}')
                    break
            except:
                pass
        time.sleep(5)

    print('\n=== 결과 ===')
    if 'req_body' in captured:
        try:
            d = json.loads(captured['req_body'])
            ts = time.strftime('%Y%m%d_%H%M%S')
            path = LOG_DIR / f'{ts}_commercial_post.json'
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            print(f'저장: {path}')
            print(json.dumps(d, ensure_ascii=False, indent=2)[:800])
        except:
            print(captured.get('req_body', '')[:500])
    else:
        print('POST 바디 캡처 실패')

    input('\nEnter 누르면 종료...')
    browser.close()
