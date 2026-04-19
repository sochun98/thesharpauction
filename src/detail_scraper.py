"""
법원경매정보 사이트에서 사건번호로 상세 페이지를 자동 조회합니다.

PGJ159M00.xml (경매사건검색) 폼에 사건번호를 자동 입력하고
결과 화면을 스크린샷으로 반환하거나, 구조화 데이터를 파싱합니다.
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


def _fill_case_no(page, selector: str, value: str) -> None:
    """maxlength 제한을 JS로 해제한 뒤 입력 — 6자리 이상 사건번호 대응."""
    page.evaluate(
        """([sel]) => {
            const el = document.querySelector(sel);
            if (el) { el.removeAttribute('maxlength'); el.value = ''; }
        }""",
        [selector],
    )
    page.locator(selector).fill(value)


def fetch_case_detail_data(
    case_number: str,
    court_name: str = "",
    headless: bool = True,
) -> dict | None:
    """
    Playwright로 경매사건검색 → 상세 페이지까지 이동한 뒤
    구조화된 경매 데이터를 파싱하여 dict 반환.

    반환 dict 키:
        case_number, court, address, geo_address,
        property_desc, appraised_value, min_bid,
        auction_date, failure_count, detail_url

    사건을 찾지 못하면 None 반환.
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
            # 1) 세션 쿠키 획득
            page.goto(
                f"{BASE_URL}/pgj/index.on",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            _wait_websquare(page)

            # 2) 경매사건검색 페이지
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
            _wait_websquare(page)

            # 3) 법원 / 년도 / 사건번호 입력
            _select_court(page, court_name)
            if parsed["year"]:
                _select_option_by_value(
                    page,
                    "#mf_wfm_mainFrame_sbx_auctnCsSrchCsYear",
                    parsed["year"],
                )

            _FIELD = "#mf_wfm_mainFrame_ibx_auctnCsSrchCsNo"
            _fill_case_no(page, _FIELD, parsed["num"])
            time.sleep(0.3)

            page.locator("#mf_wfm_mainFrame_btn_auctnCsSrchBtn").click()
            time.sleep(3)

            result_count = _get_result_count(page)
            if result_count == 0:
                # 타입 포함 재시도
                _fill_case_no(page, _FIELD, parsed["type"] + parsed["num"])
                time.sleep(0.3)
                page.locator("#mf_wfm_mainFrame_btn_auctnCsSrchBtn").click()
                time.sleep(3)
                result_count = _get_result_count(page)

            if result_count == 0:
                return None  # 사건 없음

            # 4) 결과 목록에서 먼저 간단한 데이터 수집 (상세 이동 전)
            list_data = _extract_list_row_data(page)

            # 5) 첫 번째 결과 클릭 → 상세 페이지
            _click_first_result(page)
            time.sleep(3)

            # 6) 상세 페이지에서 데이터 파싱
            detail_data = _extract_detail_page_data(page)
            detail_url = page.url  # 현재 URL (상세 페이지)

        finally:
            browser.close()

    # list_data와 detail_data 병합 (detail 우선)
    merged = {**list_data, **{k: v for k, v in detail_data.items() if v or v == 0}}
    merged["case_number"] = merged.get("case_number") or case_number
    merged["detail_url"]  = detail_url if "index.on" in detail_url else ""
    return merged


def _extract_list_row_data(page) -> dict:
    """
    경매사건검색 결과 목록 첫 번째 행에서 기본 데이터 추출.
    """
    data: dict = {
        "case_number": "", "court": "", "address": "", "geo_address": "",
        "property_desc": "", "appraised_value": 0, "min_bid": 0,
        "auction_date": "", "failure_count": 0,
    }
    try:
        # 결과 테이블 전체 텍스트 수집
        text = page.evaluate("""
            (() => {
                const rows = document.querySelectorAll(
                    '[id*="mainFrame"] table tr, [id*="mainFrame"] [class*="grid"] tr'
                );
                return Array.from(rows).map(r => r.innerText).join('\\n');
            })()
        """) or ""
        _fill_from_text(data, text)
    except Exception:
        pass
    return data


def _extract_detail_page_data(page) -> dict:
    """
    사건 상세 페이지(PGJ101M01.xml)에서 구조화 데이터 추출.
    WebSquare 레이블/값 쌍을 대상으로 DOM 텍스트 전체를 파싱.
    """
    data: dict = {
        "case_number": "", "court": "", "address": "", "geo_address": "",
        "property_desc": "", "appraised_value": 0, "min_bid": 0,
        "auction_date": "", "failure_count": 0,
    }
    try:
        # 페이지 전체 텍스트 (innerText)
        text = page.evaluate(
            "document.querySelector('[id*=\"mainFrame\"]')?.innerText || document.body.innerText"
        ) or ""
        _fill_from_text(data, text)

        # WebSquare input 값도 별도로 수집 (ibx_ 로 시작하는 input)
        inputs = page.evaluate("""
            (() => {
                const res = {};
                document.querySelectorAll('[id*="mainFrame"] input[id*="ibx_"], '
                    + '[id*="mainFrame"] input[id*="st_"]').forEach(el => {
                    const v = (el.value || '').trim();
                    if (v) res[el.id] = v;
                });
                return res;
            })()
        """) or {}
        _fill_from_inputs(data, inputs)

    except Exception:
        pass
    return data


# ── 파싱 헬퍼 ────────────────────────────────────────────────────────────────

def _fill_from_text(data: dict, text: str):
    """페이지 innerText에서 정규식으로 주요 필드 추출 (in-place)."""

    # 소재지 / 물건소재지
    for pat in [
        r'(?:물건\s*)?소재지\s*[:\t ]+(.+?)(?=\n|감정|최저|매각|유찰|$)',
        r'소\s*재\s*지\s*[:\t ]+(.+?)(?=\n|감정|최저|$)',
    ]:
        m = re.search(pat, text)
        if m:
            addr = m.group(1).strip()
            if len(addr) > 5:
                data["address"] = addr
                # 지오코딩용: 지번 주소 앞부분만 (건물명/동호수 제거)
                geo = re.sub(r'\s*[(\[].+?[)\]]', '', addr)
                geo = re.sub(r'\s+\d+층.*$', '', geo)
                data["geo_address"] = geo.strip()
                break

    # 감정평가액
    for pat in [
        r'감정\s*평가\s*액?\s*[:\t ]*([\d,]+)\s*원',
        r'감\s*정\s*가\s*[:\t ]*([\d,]+)\s*원',
        r'감정가\s*[:\t ]*([\d,]+)',
    ]:
        m = re.search(pat, text)
        if m:
            data["appraised_value"] = int(m.group(1).replace(",", ""))
            break

    # 최저매각가격
    for pat in [
        r'최저\s*매각\s*가\s*격?\s*[:\t ]*([\d,]+)\s*원',
        r'최저가\s*[:\t ]*([\d,]+)',
    ]:
        m = re.search(pat, text)
        if m:
            data["min_bid"] = int(m.group(1).replace(",", ""))
            break

    # 매각기일
    for pat in [
        r'매각\s*기일\s*[:\t ]+(\d{4}[.\-]\d{2}[.\-]\d{2})',
        r'(\d{4}[.\-]\d{2}[.\-]\d{2})\s*\d{2}:\d{2}',  # 날짜+시간 패턴
    ]:
        m = re.search(pat, text)
        if m:
            data["auction_date"] = m.group(1).replace(".", "-")
            break

    # 유찰 횟수
    m = re.search(r'유찰\s*(?:횟수)?\s*[:\t ]*(\d+)', text)
    if m:
        data["failure_count"] = int(m.group(1))

    # 용도 / 물건 종류
    for pat in [
        r'(?:주\s*용\s*도|물건\s*용도|용\s*도)\s*[:\t ]+(.+?)(?=\n|감정|최저|소재|$)',
        r'(?:근린생활시설|상\s*가|오피스텔|아파트|연립|단독|공장|창고|토지|사무실)',
    ]:
        m = re.search(pat, text)
        if m:
            desc = m.group(0) if m.lastindex is None else m.group(1)
            data["property_desc"] = desc.strip()[:40]
            break

    # 법원명
    m = re.search(r'(\S+지방법원(?:\s+\S+지원)?)', text)
    if m:
        data["court"] = m.group(1).strip()


def _fill_from_inputs(data: dict, inputs: dict):
    """WebSquare input 값에서 추가 데이터 보완 (in-place)."""
    for _id, val in inputs.items():
        id_lower = _id.lower()
        if "addr" in id_lower or "lotno" in id_lower or "adong" in id_lower:
            if not data["address"] and len(val) > 5:
                data["address"] = val
        elif "gamevalamt" in id_lower or "eval" in id_lower:
            if not data["appraised_value"]:
                try:
                    data["appraised_value"] = int(re.sub(r"[^\d]", "", val))
                except ValueError:
                    pass
        elif "minmaeprice" in id_lower or "minbid" in id_lower:
            if not data["min_bid"]:
                try:
                    data["min_bid"] = int(re.sub(r"[^\d]", "", val))
                except ValueError:
                    pass
        elif "magiil" in id_lower or "maegii" in id_lower:
            if not data["auction_date"]:
                data["auction_date"] = val


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

            # 5) 사건번호 입력 (maxlength 우회 후 숫자 입력)
            _FIELD = "#mf_wfm_mainFrame_ibx_auctnCsSrchCsNo"
            _fill_case_no(page, _FIELD, parsed["num"])
            time.sleep(0.3)

            # 6) 검색 버튼 클릭
            page.locator("#mf_wfm_mainFrame_btn_auctnCsSrchBtn").click()
            time.sleep(3)

            # 7) 결과 확인 — 결과가 없으면 타입 포함 재시도
            result_count = _get_result_count(page)
            if result_count == 0:
                _fill_case_no(page, _FIELD, parsed["type"] + parsed["num"])
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
