"""
searchControllerMain.on  POST 바디 + 응답 캡처
- route 인터셉션으로 요청 바디/헤더 캡처
- 새 탭(PGJ151F00.xml)이 열리면 조회 버튼 자동 클릭
- Python requests로 동일 요청 재현
"""
import sys, time, json, threading
sys.path.insert(0, "src")
import requests as req_lib
from playwright.sync_api import sync_playwright, Route

captured = {}
done_event = threading.Event()

def handle_route(route: Route):
    r = route.request
    body = r.post_data or ""
    headers_dict = dict(r.headers)

    captured["req"]     = body
    captured["headers"] = headers_dict
    print(f"\n✅ 요청 캡처! ({len(body)}자)")

    # Python requests로 직접 재현
    try:
        skip = {"host", "content-length", "transfer-encoding"}
        req_headers = {k: v for k, v in headers_dict.items()
                       if k.lower() not in skip}
        resp = req_lib.post(
            r.url,
            data=body.encode("utf-8"),
            headers=req_headers,
            timeout=30,
        )
        print(f"   직접 요청 응답: HTTP {resp.status_code} ({len(resp.content):,}바이트)")
        captured["resp"] = resp.json()
    except Exception as e:
        print(f"   직접 요청 오류: {e}")

    # 즉시 파일 저장 (타임아웃 만료 후에도 데이터 보존)
    import pathlib
    from datetime import datetime
    LOG_DIR = pathlib.Path(__file__).parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        (LOG_DIR / f"{ts}_post_body.txt").write_text(body, encoding="utf-8")
        print(f"   POST 바디 저장: logs/{ts}_post_body.txt")
    except Exception:
        pass
    if "resp" in captured:
        try:
            with open(LOG_DIR / f"{ts}_response.json", "w", encoding="utf-8") as f:
                json.dump(captured["resp"], f, ensure_ascii=False, indent=2)
            print(f"   응답 저장: logs/{ts}_response.json")
        except Exception:
            pass

    done_event.set()
    try:
        route.continue_()
    except Exception:
        pass  # 브라우저가 닫히는 중이면 무시


def click_search_on_new_page(np):
    """새 탭에서 조회 버튼 클릭"""
    # 1. about:blank에서 실제 URL로 이동할 때까지 대기
    print(f"   URL 이동 대기 중...")
    for _ in range(40):
        if np.url not in ("about:blank", ""):
            break
        time.sleep(0.5)
    print(f"   새 탭 URL: {np.url[:100]}")

    # 2. WebSquare 초기화 대기
    try:
        np.wait_for_function("typeof scwin !== 'undefined'", timeout=30_000)
        print("   WebSquare 초기화 완료")
    except Exception:
        print("   WebSquare 초기화 타임아웃 (계속 진행)")
    time.sleep(2)

    # 3. 페이지 내 버튼 목록 디버그 출력
    try:
        btns = np.evaluate("""
            Array.from(document.querySelectorAll('input[type=button],button,a'))
              .map(e => e.id + '|' + (e.value||e.innerText||'').trim())
              .filter(s => s.length > 1)
              .slice(0, 20)
        """)
        print(f"   버튼 목록: {btns}")
    except Exception:
        pass

    # 4. 조회 버튼 클릭 시도
    for sel in [
        "#mf_btn_srch",
        "#mf_wfm_mainFrame_btn_srch",
        "[id$='btn_srch']",
        "[id$='btnSrch']",
        "[id*='Srch'][id*='btn']",
        "input[value='조회']",
        "input[value*='조회']",
        "button:has-text('조회')",
        "input[value*='검색']",
        "button:has-text('검색')",
    ]:
        try:
            els = np.locator(sel)
            if els.count() > 0:
                btn_id = els.first.get_attribute("id") or sel
                print(f"   조회 클릭: {btn_id}")
                els.first.click()
                return True
        except Exception:
            continue

    # 5. scwin 함수 직접 호출
    try:
        result = np.evaluate("""
            (function() {
                if (typeof scwin === 'undefined') return null;
                var fns = Object.keys(scwin).filter(k =>
                    k.toLowerCase().includes('srch') || k.toLowerCase().includes('search'));
                if (fns.length > 0) { scwin[fns[0]](); return fns[0]; }
                return null;
            })()
        """)
        if result:
            print(f"   JS 함수 호출: scwin.{result}()")
            return True
    except Exception:
        pass

    print("   ⚠️ 조회 버튼을 찾지 못했습니다.")
    return False


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )

    ctx.route("**/searchControllerMain.on", handle_route)

    new_pages = []

    def on_new_page(pg):
        new_pages.append(pg)
        print(f"   새 탭 감지: {pg.url[:80]}")

    page = ctx.new_page()
    page.goto("https://www.courtauction.go.kr/pgj/index.on",
              wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("typeof scwin !== 'undefined'", timeout=30_000)
    time.sleep(2)

    # ── 시/도 선택 ────────────────────────────────────────────────────
    sd = page.locator("#mf_sbx_rletRpdtSdLst")
    for i, o in enumerate(sd.locator("option").all()):
        if "경기" in o.inner_text():
            sd.select_option(index=i)
            print(f"시/도 선택: {o.inner_text().strip()} (index={i})")
            break
    time.sleep(2)

    # ── 시/군/구 선택 ─────────────────────────────────────────────────
    sgg = page.locator("#mf_sbx_rletRpdtSggLst")
    for i, o in enumerate(sgg.locator("option").all()):
        if "영통" in o.inner_text():
            sgg.select_option(index=i)
            print(f"시/군/구 선택: {o.inner_text().strip()} (index={i})")
            break
    time.sleep(1)

    # ── 검색 클릭 (이벤트 핸들러는 클릭 직전에 등록) ─────────────────
    ctx.on("page", on_new_page)
    print("검색 버튼 클릭...")
    page.locator("#mf_btn_quickSearchGds").click()

    # ── 새 탭 기다리기 (최대 20초) ────────────────────────────────────
    print("새 탭 대기 중...")
    for _ in range(40):
        time.sleep(0.5)
        # about:blank 말고 실제 페이지인 탭만
        real_pages = [pg for pg in new_pages if pg.url != "about:blank"]
        if real_pages:
            break

    real_pages = [pg for pg in new_pages if pg.url not in ("about:blank", "")]
    if not real_pages:
        # URL이 아직 blank일 수 있으니 전체 목록에서 마지막 것 사용
        real_pages = new_pages

    if real_pages and not done_event.is_set():
        np = real_pages[-1]
        print(f"   대상 탭: {np.url[:80]}")
        # 새 탭에서 조회 버튼 클릭 (백그라운드 스레드)
        t = threading.Thread(target=click_search_on_new_page, args=(np,), daemon=True)
        t.start()

    # ── POST 대기 (최대 180초) ─────────────────────────────────────────
    print("POST 대기 중 (최대 180초, 자동으로 발동됩니다)...")
    done_event.wait(timeout=180)

    # ── logs/ 폴더 저장 ───────────────────────────────────────────────
    import pathlib
    from datetime import datetime
    LOG_DIR = pathlib.Path(__file__).parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 결과 출력 ─────────────────────────────────────────────────────
    print("\n" + "="*60)
    if "req" in captured:
        print("=== POST 바디 (전체) ===")
        print(captured["req"])
        req_path = LOG_DIR / f"{ts}_post_body.txt"
        req_path.write_text(captured["req"], encoding="utf-8")
        print(f"\n→ {req_path} 저장됨")
    else:
        print("❌ POST 바디 캡처 실패")

    print("\n" + "="*60)
    if "resp" in captured:
        body = captured["resp"]
        print("=== 응답 JSON 구조 ===")
        if isinstance(body, dict):
            print(f"최상위 키: {list(body.keys())}")
            for k, v in body.items():
                if isinstance(v, list):
                    print(f"\n  [{k}] → list, {len(v)}건")
                    if v and isinstance(v[0], dict):
                        print(f"       컬럼: {list(v[0].keys())}")
                        print(f"       첫행: {json.dumps(v[0], ensure_ascii=False)[:500]}")
                elif isinstance(v, dict):
                    print(f"\n  [{k}] → dict, 키: {list(v.keys())}")
                    for k2, v2 in v.items():
                        if isinstance(v2, list) and v2:
                            print(f"    [{k2}] → {len(v2)}건")
                            if isinstance(v2[0], dict):
                                print(f"         컬럼: {list(v2[0].keys())}")
                                print(f"         첫행: {json.dumps(v2[0], ensure_ascii=False)[:500]}")
                        else:
                            print(f"    [{k2}] = {str(v2)[:80]}")
                else:
                    print(f"  [{k}] = {str(v)[:100]}")

        resp_path = LOG_DIR / f"{ts}_response.json"
        with open(resp_path, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        print(f"\n→ {resp_path} 저장됨")
    else:
        print("❌ 응답 캡처 실패")

    input("\nEnter 누르면 종료...")
    browser.close()
