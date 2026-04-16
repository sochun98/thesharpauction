"""
법원경매정보 사이트에서 사건번호로 상세 페이지를 자동 조회합니다.

PGJ159M00.xml (경매사건검색) 폼에 사건번호를 자동 입력하고
결과 화면을 스크린샷으로 반환합니다.
"""
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL   = "https://www.courtauction.go.kr"
SEARCH_URL = f"{BASE_URL}/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml"

# 스크레이퍼에서 수집한 법원명 → 사이트 셀렉트박스 값 매핑
# 페이지 탐색 시 options 텍스트로 부분 매칭하므로 주요 법원만 정의
COURT_KEYWORD: dict[str, str] = {
    "서울중앙": "서울중앙",
    "서울동부": "서울동부",
    "서울남부": "서울남부",
    "서울북부": "서울북부",
    "서울서부": "서울서부",
    "수원":     "수원",
    "인천":     "인천",
    "대전":     "대전",
    "대구":     "대구",
    "부산":     "부산",
    "광주":     "광주",
    "울산":     "울산",
    "창원":     "창원",
    "춘천":     "춘천",
    "청주":     "청주",
    "전주":     "전주",
    "제주":     "제주",
    "의정부":   "의정부",
    "성남":     "성남",
    "평택":     "평택",
    "안산":     "안산",
    "안양":     "안양",
    "고양":     "고양",
}


def parse_case_number(case_number: str) -> dict:
    """
    "2025타경1345" 또는 "2025타경1345(1)" 등 다양한 형식 파싱.
    Returns: {"year": "2025", "type": "타경", "num": "1345"}
    """
    # "(숫자)" 같은 물건번호 제거
    cn = re.sub(r"\(\d+\).*$", "", case_number.strip())
    m = re.match(r"^(\d{4})(타경|타기|타채|타결|기타)(\d+)$", cn)
    if m:
        return {"year": m.group(1), "type": m.group(2), "num": m.group(3)}
    # 년도 + 숫자만 있는 경우
    m2 = re.match(r"^(\d{4})\D*(\d+)$", cn)
    if m2:
        return {"year": m2.group(1), "type": "타경", "num": m2.group(2)}
    return {"year": "", "type": "타경", "num": cn}


def fetch_case_detail_screenshot(
    case_number: str,
    court_name: str = "",
    headless: bool = True,
    navigate_to_detail: bool = True,
) -> bytes:
    """
    법원경매 사이트 경매사건검색 페이지에서 사건번호를 자동 입력하고
    결과(또는 상세) 화면의 스크린샷 PNG bytes를 반환합니다.

    Parameters
    ----------
    case_number : "2025타경1345" 형식
    court_name  : 법원명 (예: "수원지방법원"). 없으면 모든 법원 검색
    headless    : False 이면 브라우저 창을 표시
    navigate_to_detail : True 이면 검색 결과 첫 행을 클릭해 상세 페이지까지 이동
    """
    parsed = parse_case_number(case_number)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        try:
            # 1) 메인 페이지 먼저 방문해 세션 쿠키 획득
            page.goto(
                f"{BASE_URL}/pgj/index.on",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            _wait_websquare(page)

            # 2) 경매사건검색 페이지 이동
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
            _wait_websquare(page)

            # 3) 법원 선택
            _select_court(page, court_name)

            # 4) 년도 선택
            if parsed["year"]:
                _select_option_by_value(
                    page,
                    "#mf_wfm_mainFrame_sbx_auctnCsSrchCsYear",
                    parsed["year"],
                )

            # 5) 사건번호 입력 (사이트는 "타경1345" 또는 숫자만 허용)
            case_no_field = page.locator("#mf_wfm_mainFrame_ibx_auctnCsSrchCsNo")
            case_no_field.fill("")
            time.sleep(0.3)
            # 먼저 "타경1345" 전체 시도
            case_no_field.fill(parsed["type"] + parsed["num"])
            time.sleep(0.3)

            # 6) 검색 버튼 클릭
            page.locator("#mf_wfm_mainFrame_btn_auctnCsSrchBtn").click()
            time.sleep(3)

            # 7) 결과 확인 — 결과가 없으면 숫자만으로 재시도
            result_count = _get_result_count(page)
            if result_count == 0:
                case_no_field.fill(parsed["num"])
                time.sleep(0.3)
                page.locator("#mf_wfm_mainFrame_btn_auctnCsSrchBtn").click()
                time.sleep(3)
                result_count = _get_result_count(page)

            # 8) 상세 페이지로 이동 (결과 첫 행 클릭)
            if navigate_to_detail and result_count > 0:
                _click_first_result(page)
                time.sleep(3)

            # 9) 스크린샷
            screenshot = page.screenshot(full_page=False)

        finally:
            browser.close()

    return screenshot


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _wait_websquare(page, timeout_ms: int = 15_000):
    """WebSquare 프레임워크 초기화 대기."""
    try:
        page.wait_for_function("typeof scwin !== 'undefined'", timeout=timeout_ms)
    except Exception:
        pass
    time.sleep(1.5)


def _select_option_by_value(page, selector: str, value: str):
    """select 요소에서 value와 일치하는 옵션 선택."""
    try:
        page.locator(selector).select_option(value=value)
    except Exception:
        pass


def _select_court(page, court_name: str):
    """
    법원 셀렉트박스에서 court_name 키워드를 포함하는 옵션 선택.
    court_name이 없으면 변경하지 않음.
    """
    if not court_name:
        return
    sel = "#mf_wfm_mainFrame_sbx_auctnCsSrchCortOfc"
    try:
        select_el = page.locator(sel)
        options = select_el.locator("option").all()
        for opt in options:
            opt_text = opt.inner_text().strip()
            # court_name 부분 매칭 (예: "수원지방법원" → 옵션 "수원지방법원" 선택)
            if court_name in opt_text or opt_text in court_name:
                select_el.select_option(label=opt_text)
                return
        # 키워드 테이블로 재시도
        for kw, label_part in COURT_KEYWORD.items():
            if kw in court_name:
                for opt in options:
                    if label_part in opt.inner_text():
                        select_el.select_option(label=opt.inner_text().strip())
                        return
    except Exception:
        pass


def _get_result_count(page) -> int:
    """검색 결과 행 수를 반환합니다."""
    try:
        # 결과 테이블의 행(tr) 수 — 헤더 제외
        count = page.evaluate("""
            (() => {
                const tbodies = document.querySelectorAll(
                    '[id*="mainFrame"] table tbody tr, [id*="mainFrame"] [id*="grid"] tr'
                );
                return tbodies.length;
            })()
        """)
        return int(count or 0)
    except Exception:
        return 0


def _click_first_result(page):
    """결과 목록의 첫 번째 행을 클릭합니다."""
    selectors = [
        "[id*='mainFrame'] table tbody tr:first-child td:first-child",
        "[id*='mainFrame'] [id*='grid'] tr:nth-child(1)",
        "[id*='mainFrame'] tr.w2grid_row:first-child",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                el.first.click()
                return
        except Exception:
            pass
    # 마지막 수단: 첫 번째 링크 클릭
    try:
        page.locator("[id*='mainFrame'] a").first.click()
    except Exception:
        pass
