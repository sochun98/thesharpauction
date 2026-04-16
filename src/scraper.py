"""
대법원 법원경매정보 스크래퍼

전략:
  1. requests.Session으로 메인 페이지 GET → JSESSIONID / WMONID 쿠키 획득
     (실패 시 Playwright로 쿠키만 획득)
  2. 시도/시군구 이름 → 행정구역 코드 변환 (정적 테이블)
  3. requests.post로 searchControllerMain.on 직접 호출 (페이지네이션)
"""

import copy
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests as req_lib

BASE_URL   = "https://www.courtauction.go.kr"
ENTRY_URL  = f"{BASE_URL}/pgj/index.on"
SEARCH_URL = f"{BASE_URL}/pgj/pgjsearch/searchControllerMain.on"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── 시도 코드 (행정구역 코드 2자리) ──────────────────────────────────
SIDO_CODE: dict[str, str] = {
    "서울특별시": "11", "서울": "11",
    "부산광역시": "26", "부산": "26",
    "대구광역시": "27", "대구": "27",
    "인천광역시": "28", "인천": "28",
    "광주광역시": "29", "광주": "29",
    "대전광역시": "30", "대전": "30",
    "울산광역시": "31", "울산": "31",
    "세종특별자치시": "36", "세종": "36",
    "경기도": "41", "경기": "41",
    "강원특별자치도": "51", "강원도": "42", "강원": "51",
    "충청북도": "43", "충북": "43",
    "충청남도": "44", "충남": "44",
    "전북특별자치도": "52", "전라북도": "45", "전북": "52",
    "전라남도": "46", "전남": "46",
    "경상북도": "47", "경북": "47",
    "경상남도": "48", "경남": "48",
    "제주특별자치도": "50", "제주": "50",
}

# ── 시군구 코드 (5자리 코드의 마지막 3자리) ──────────────────────────
# 형식: (시도코드, 시군구명) → 3자리 코드
SGG_CODE: dict[tuple[str, str], str] = {
    # 서울 11
    ("11","종로구"):"110",("11","중구"):"140",("11","용산구"):"170",
    ("11","성동구"):"200",("11","광진구"):"215",("11","동대문구"):"230",
    ("11","중랑구"):"260",("11","성북구"):"290",("11","강북구"):"305",
    ("11","도봉구"):"320",("11","노원구"):"350",("11","은평구"):"380",
    ("11","서대문구"):"410",("11","마포구"):"440",("11","양천구"):"470",
    ("11","강서구"):"500",("11","구로구"):"530",("11","금천구"):"545",
    ("11","영등포구"):"560",("11","동작구"):"590",("11","관악구"):"620",
    ("11","서초구"):"650",("11","강남구"):"680",("11","송파구"):"710",
    ("11","강동구"):"740",
    # 부산 26
    ("26","중구"):"110",("26","서구"):"140",("26","동구"):"170",
    ("26","영도구"):"200",("26","부산진구"):"230",("26","동래구"):"260",
    ("26","남구"):"290",("26","북구"):"320",("26","해운대구"):"350",
    ("26","사하구"):"380",("26","금정구"):"410",("26","강서구"):"440",
    ("26","연제구"):"470",("26","수영구"):"500",("26","사상구"):"530",
    ("26","기장군"):"710",
    # 대구 27
    ("27","중구"):"110",("27","동구"):"140",("27","서구"):"170",
    ("27","남구"):"200",("27","북구"):"230",("27","수성구"):"260",
    ("27","달서구"):"290",("27","달성군"):"710",("27","군위군"):"720",
    # 인천 28
    ("28","중구"):"110",("28","동구"):"140",("28","미추홀구"):"177",
    ("28","연수구"):"185",("28","남동구"):"200",("28","부평구"):"237",
    ("28","계양구"):"245",("28","서구"):"260",("28","강화군"):"710",
    ("28","옹진군"):"720",
    # 광주 29
    ("29","동구"):"110",("29","서구"):"140",("29","남구"):"155",
    ("29","북구"):"170",("29","광산구"):"200",
    # 대전 30
    ("30","동구"):"110",("30","중구"):"140",("30","서구"):"170",
    ("30","유성구"):"200",("30","대덕구"):"230",
    # 울산 31
    ("31","중구"):"110",("31","남구"):"140",("31","동구"):"170",
    ("31","북구"):"200",("31","울주군"):"710",
    # 세종 36
    ("36","세종시"):"110",
    # 경기 41
    ("41","수원시 장안구"):"111",("41","수원시 권선구"):"113",
    ("41","수원시 팔달구"):"115",("41","수원시 영통구"):"117",
    ("41","성남시 수정구"):"131",("41","성남시 중원구"):"133",
    ("41","성남시 분당구"):"135",("41","의정부시"):"150",
    ("41","안양시 만안구"):"171",("41","안양시 동안구"):"173",
    ("41","부천시"):"190",("41","광명시"):"210",("41","평택시"):"220",
    ("41","동두천시"):"250",("41","안산시 상록구"):"271",
    ("41","안산시 단원구"):"273",("41","고양시 덕양구"):"281",
    ("41","고양시 일산동구"):"285",("41","고양시 일산서구"):"287",
    ("41","과천시"):"290",("41","구리시"):"310",("41","남양주시"):"360",
    ("41","오산시"):"370",("41","시흥시"):"390",("41","군포시"):"410",
    ("41","의왕시"):"430",("41","하남시"):"450",
    ("41","용인시 처인구"):"461",("41","용인시 기흥구"):"463",
    ("41","용인시 수지구"):"465",("41","파주시"):"480",
    ("41","이천시"):"500",("41","안성시"):"550",("41","김포시"):"570",
    ("41","화성시"):"590",("41","광주시"):"610",("41","양주시"):"630",
    ("41","포천시"):"650",("41","여주시"):"670",("41","연천군"):"800",
    ("41","가평군"):"820",("41","양평군"):"830",
    # 강원 51 (구 42)
    ("51","춘천시"):"110",("51","원주시"):"130",("51","강릉시"):"150",
    ("51","동해시"):"170",("51","태백시"):"183",("51","속초시"):"210",
    ("51","삼척시"):"230",("51","홍천군"):"720",("51","횡성군"):"730",
    ("51","영월군"):"750",("51","평창군"):"760",("51","정선군"):"770",
    ("51","철원군"):"780",("51","화천군"):"790",("51","양구군"):"800",
    ("51","인제군"):"810",("51","고성군"):"820",("51","양양군"):"830",
    ("42","춘천시"):"110",("42","원주시"):"130",("42","강릉시"):"150",
    ("42","동해시"):"170",("42","태백시"):"183",("42","속초시"):"210",
    ("42","삼척시"):"230",("42","홍천군"):"720",("42","횡성군"):"730",
    ("42","영월군"):"750",("42","평창군"):"760",("42","정선군"):"770",
    ("42","철원군"):"780",("42","화천군"):"790",("42","양구군"):"800",
    ("42","인제군"):"810",("42","고성군"):"820",("42","양양군"):"830",
    # 충북 43
    ("43","청주시 상당구"):"111",("43","청주시 서원구"):"112",
    ("43","청주시 흥덕구"):"113",("43","청주시 청원구"):"114",
    ("43","충주시"):"130",("43","제천시"):"150",("43","보은군"):"720",
    ("43","옥천군"):"730",("43","영동군"):"740",("43","증평군"):"745",
    ("43","진천군"):"750",("43","괴산군"):"760",("43","음성군"):"770",
    ("43","단양군"):"800",
    # 충남 44
    ("44","천안시 동남구"):"131",("44","천안시 서북구"):"133",
    ("44","공주시"):"150",("44","보령시"):"180",("44","아산시"):"200",
    ("44","서산시"):"210",("44","논산시"):"230",("44","계룡시"):"250",
    ("44","당진시"):"270",("44","금산군"):"710",("44","부여군"):"760",
    ("44","서천군"):"770",("44","청양군"):"790",("44","홍성군"):"800",
    ("44","예산군"):"810",("44","태안군"):"825",
    # 전북 52 (구 45)
    ("52","전주시 완산구"):"111",("52","전주시 덕진구"):"113",
    ("52","군산시"):"130",("52","익산시"):"150",("52","정읍시"):"180",
    ("52","남원시"):"190",("52","김제시"):"210",("52","완주군"):"710",
    ("52","진안군"):"720",("52","무주군"):"730",("52","장수군"):"740",
    ("52","임실군"):"750",("52","순창군"):"770",("52","고창군"):"790",
    ("52","부안군"):"800",
    ("45","전주시 완산구"):"111",("45","전주시 덕진구"):"113",
    ("45","군산시"):"130",("45","익산시"):"150",("45","정읍시"):"180",
    ("45","남원시"):"190",("45","김제시"):"210",
    # 전남 46
    ("46","목포시"):"110",("46","여수시"):"130",("46","순천시"):"150",
    ("46","나주시"):"170",("46","광양시"):"230",("46","담양군"):"710",
    ("46","곡성군"):"720",("46","구례군"):"730",("46","고흥군"):"770",
    ("46","보성군"):"780",("46","화순군"):"790",("46","장흥군"):"800",
    ("46","강진군"):"810",("46","해남군"):"820",("46","영암군"):"830",
    ("46","무안군"):"840",("46","함평군"):"860",("46","영광군"):"870",
    ("46","장성군"):"880",("46","완도군"):"890",("46","진도군"):"900",
    ("46","신안군"):"910",
    # 경북 47
    ("47","포항시 남구"):"111",("47","포항시 북구"):"113",
    ("47","경주시"):"130",("47","김천시"):"150",("47","안동시"):"170",
    ("47","구미시"):"190",("47","영주시"):"210",("47","영천시"):"230",
    ("47","상주시"):"250",("47","문경시"):"280",("47","경산시"):"290",
    ("47","의성군"):"730",("47","청송군"):"750",("47","영양군"):"760",
    ("47","영덕군"):"770",("47","청도군"):"820",("47","고령군"):"830",
    ("47","성주군"):"840",("47","칠곡군"):"850",("47","예천군"):"900",
    ("47","봉화군"):"920",("47","울진군"):"930",("47","울릉군"):"940",
    # 경남 48
    ("48","창원시 의창구"):"121",("48","창원시 성산구"):"123",
    ("48","창원시 마산합포구"):"125",("48","창원시 마산회원구"):"127",
    ("48","창원시 진해구"):"129",("48","진주시"):"170",
    ("48","통영시"):"220",("48","사천시"):"240",("48","김해시"):"250",
    ("48","밀양시"):"270",("48","거제시"):"310",("48","양산시"):"330",
    ("48","의령군"):"720",("48","함안군"):"730",("48","창녕군"):"740",
    ("48","고성군"):"820",("48","남해군"):"840",("48","하동군"):"850",
    ("48","산청군"):"860",("48","함양군"):"870",("48","거창군"):"880",
    ("48","합천군"):"890",
    # 제주 50
    ("50","제주시"):"110",("50","서귀포시"):"130",
}

# 용도코드 → 한글 (소분류 우선)
UTIL_CODE: dict[str, str] = {
    "10000":"기타건물",
    "20000":"주거용",   "20100":"아파트",     "20104":"아파트",
    "20200":"연립/다세대","20300":"단독주택",  "20400":"다가구주택",
    "30000":"상업용",   "30100":"상가",       "30200":"근린생활시설",
    "30300":"판매시설", "30400":"업무시설",   "30500":"숙박시설",
    "40000":"업무용",   "40100":"오피스텔",
    "50000":"공업용",   "50100":"공장",
    "60000":"토지",
}

# POST 바디 기본 템플릿 (캡처 데이터 기반)
_POST_TEMPLATE = {
    "dma_pageInfo": {
        "pageNo": 1, "pageSize": 10, "bfPageNo": "",
        "startRowNo": "", "totalCnt": "", "totalYn": "Y",
        "groupTotalCount": "",
    },
    "dma_srchGdsDtlSrchInfo": {
        "rletDspslSpcCondCd": "", "bidDvsCd": "",
        "mvprpRletDvsCd": "00031R",
        "cortAuctnSrchCondCd": "0004601",
        "rprsAdongSdCd": "",     # ← 시도 코드
        "rprsAdongSggCd": "",    # ← 시군구 코드
        "rprsAdongEmdCd": "", "rdnmSdCd": "", "rdnmSggCd": "",
        "rdnmNo": "", "mvprpDspslPlcAdongSdCd": "",
        "mvprpDspslPlcAdongSggCd": "", "mvprpDspslPlcAdongEmdCd": "",
        "rdDspslPlcAdongSdCd": "", "rdDspslPlcAdongSggCd": "",
        "rdDspslPlcAdongEmdCd": "", "cortOfcCd": "", "jdbnCd": "",
        "execrOfcDvsCd": "", "lclDspslGdsLstUsgCd": "",
        "mclDspslGdsLstUsgCd": "", "sclDspslGdsLstUsgCd": "",
        "cortAuctnMbrsId": "", "aeeEvlAmtMin": "", "aeeEvlAmtMax": "",
        "lwsDspslPrcRateMin": "", "lwsDspslPrcRateMax": "",
        "flbdNcntMin": "", "flbdNcntMax": "",
        "objctArDtsMin": "", "objctArDtsMax": "",
        "mvprpArtclKndCd": "", "mvprpArtclNm": "",
        "mvprpAtchmPlcTypCd": "", "notifyLoc": "", "lafjOrderBy": "",
        "pgmId": "PGJ151M01", "csNo": "", "cortStDvs": "2",
        "statNum": "", "bidBgngYmd": "", "bidEndYmd": "",
        "dspslDxdyYmd": "", "fstDspslHm": "", "scndDspslHm": "",
        "thrdDspslHm": "", "fothDspslHm": "", "dspslPlcNm": "",
        "lwsDspslPrcMin": "", "lwsDspslPrcMax": "",
        "grbxTypCd": "", "gdsVendNm": "", "fuelKndCd": "",
        "carMdyrMax": "", "carMdyrMin": "", "carMdlNm": "",
        "sideDvsCd": "",
    },
}


@dataclass
class AuctionItem:
    case_number:     str = ""
    court:           str = ""
    property_type:   str = ""
    property_desc:   str = ""       # dspslUsgNm: 실제 용도 텍스트 (근린생활시설, 상가 등)
    address:         str = ""       # 표시용 전체 주소
    geo_address:     str = ""       # 지오코딩 전용 (시도+시군구+동+지번만)
    appraised_value: int = 0
    min_bid:         int = 0
    won_bid:         int = 0        # 낙찰가 (진행중이면 0)
    auction_date:    str = ""
    status:          str = ""
    failure_count:   int = 0
    detail_url:      str = ""
    status:          str = ""       # "경매전" = 미시작, "" = 일반


class CourtAuctionScraper:

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60_000,
        debug: bool = False,
        log_fn=None,
    ):
        self.headless    = headless
        self.timeout_ms  = timeout_ms
        self.debug       = debug
        self.log         = log_fn or print

    # ────────────────────────────────────────────────────────────────
    def search_by_case_numbers(
        self,
        case_numbers: list[str],
        stat_num: str = "05",
    ) -> list[AuctionItem]:
        """
        사건번호 목록으로 직접 검색 (경매 미시작 물건 포함).
        case_numbers: ["2025타경1345", "2024타경9999", ...]
        """
        session = self._acquire_session()
        all_items: list[AuctionItem] = []
        seen: set[str] = set()

        for cs_no in case_numbers:
            cs_no = cs_no.strip()
            if not cs_no:
                continue
            self.log(f"🔍 사건번호 직접 조회: {cs_no}")
            body = copy.deepcopy(_POST_TEMPLATE)
            info = body["dma_srchGdsDtlSrchInfo"]
            info["csNo"]    = cs_no
            info["statNum"] = stat_num
            # 지역 필터 없이 사건번호만으로 검색
            info["rprsAdongSdCd"]  = ""
            info["rprsAdongSggCd"] = ""

            try:
                resp = session.post(
                    SEARCH_URL,
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers=self._post_headers(),
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                self.log(f"   ⚠️ [{cs_no}] 요청 실패: {exc}")
                continue

            if data.get("status") != 200:
                self.log(f"   ⚠️ [{cs_no}] 응답 오류: {data.get('message')}")
                continue

            items = self._parse_response(data)
            # 입력한 사건번호와 실제로 매칭되는 것만 (부분 포함)
            cs_core = cs_no.replace(" ", "")
            matched = [
                it for it in items
                if cs_core in it.case_number.replace(" ", "")
                or it.case_number.replace(" ", "") in cs_core
            ]
            added = 0
            for item in (matched or items):
                if item.case_number not in seen:
                    item.status = "경매전"  # 경매 미시작 표시
                    all_items.append(item)
                    seen.add(item.case_number)
                    added += 1
            if added:
                self.log(f"   ✅ [{cs_no}] {added}건 추가")
            else:
                self.log(f"   ℹ️ [{cs_no}] 검색 결과 없음 (statNum={stat_num!r})")

        return all_items

    def search_multi(
        self,
        sido: str,
        sigungu_list: list[str],
        max_pages: int = 5,
        util_code: str = "",
        stat_num: str = "05",
    ) -> list[AuctionItem]:
        """
        여러 시군구를 하나의 세션으로 검색 (중복 사건번호 자동 제거).
        sigungu_list에 빈 문자열("")을 포함하면 시도 전체를 검색함.
        stat_num: "05"=전체(낙찰완료 포함), ""=진행중만
        """
        sido_code = self._resolve_sido(sido)
        session   = self._acquire_session()
        all_items: list[AuctionItem] = []
        seen: set[str] = set()

        for sigungu in sigungu_list:
            sgg_code = self._resolve_sgg(sido_code, sigungu)
            label = sigungu or "시도전체"
            self.log(f"🔍 [{label}] 검색 중...")
            items = self._fetch_all_pages(
                session, sido_code, sgg_code, max_pages, util_code, stat_num
            )
            added = 0
            for item in items:
                if item.case_number not in seen:
                    all_items.append(item)
                    seen.add(item.case_number)
                    added += 1
            self.log(f"   [{label}] {added}건 추가 (누계 {len(all_items)}건)")

        return all_items

    # ────────────────────────────────────────────────────────────────
    def search(
        self,
        sido: str,
        sigungu: str = "",
        max_pages: int = 5,
        util_code: str = "",
        stat_num: str = "05",
    ) -> list[AuctionItem]:
        """
        util_code: 대분류 용도코드 (예: "30000" = 상업용, "" = 전체)
        stat_num:  "05"=전체(낙찰완료 포함), ""=진행중만
        """
        sido_code = self._resolve_sido(sido)
        sgg_code  = self._resolve_sgg(sido_code, sigungu)
        label = f"시도={sido_code}, 시군구={sgg_code or '전체'}, 용도={util_code or '전체'}, statNum={stat_num or '진행중'}"
        self.log(f"📍 코드: {label}")

        session = self._acquire_session()
        return self._fetch_all_pages(session, sido_code, sgg_code, max_pages, util_code, stat_num)

    # ────────────────────────────────────────────────────────────────
    # 코드 조회
    # ────────────────────────────────────────────────────────────────

    def _resolve_sido(self, sido: str) -> str:
        for key, code in SIDO_CODE.items():
            if key in sido or sido in key:
                return code
        raise ValueError(f"시도 코드를 찾을 수 없습니다: {sido}")

    def _resolve_sgg(self, sido_code: str, sigungu: str) -> str:
        if not sigungu:
            return ""
        # 정확 일치
        if (sido_code, sigungu) in SGG_CODE:
            return SGG_CODE[(sido_code, sigungu)]
        # 부분 일치 (포함 관계)
        for (sc, name), code in SGG_CODE.items():
            if sc == sido_code and (sigungu in name or name in sigungu):
                return code
        self.log(f"   ⚠️ 시군구 코드를 찾지 못했습니다: {sigungu} (전체 검색)")
        return ""

    # ────────────────────────────────────────────────────────────────
    # 세션 획득
    # ────────────────────────────────────────────────────────────────

    def _acquire_session(self) -> req_lib.Session:
        """requests.Session으로 JSESSIONID / WMONID 쿠키 획득"""
        s = req_lib.Session()
        s.headers.update({
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        self.log("🌐 세션 초기화 중...")
        try:
            s.get(ENTRY_URL, timeout=20)
        except Exception as e:
            self.log(f"   ⚠️ 메인 페이지 GET 실패: {e}")

        # WMONID 가 없으면 Playwright로 보완
        if "WMONID" not in s.cookies:
            self.log("   WMONID 없음 → Playwright로 쿠키 획득...")
            cookies = self._get_cookies_playwright()
            for k, v in cookies.items():
                s.cookies.set(k, v)

        self.log(f"   쿠키: {list(s.cookies.keys())}")
        return s

    def _get_cookies_playwright(self) -> dict[str, str]:
        """Playwright로 페이지 로드 후 쿠키만 추출 (10초)"""
        from playwright.sync_api import sync_playwright
        cookies: dict[str, str] = {}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                ctx = browser.new_context(user_agent=_UA)
                ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )
                page = ctx.new_page()
                page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(4)  # WebSquare 가 WMONID 쿠키 설정할 시간
                for c in ctx.cookies():
                    cookies[c["name"]] = c["value"]
                browser.close()
        except Exception as e:
            self.log(f"   ⚠️ Playwright 쿠키 획득 실패: {e}")
        return cookies

    # ────────────────────────────────────────────────────────────────
    # 검색 요청
    # ────────────────────────────────────────────────────────────────

    def _build_body(
        self, sido_code: str, sgg_code: str, page_no: int,
        util_code: str = "", stat_num: str = "05",
    ) -> dict:
        body = copy.deepcopy(_POST_TEMPLATE)
        body["dma_pageInfo"]["pageNo"]  = page_no
        body["dma_pageInfo"]["totalYn"] = "Y" if page_no == 1 else "N"
        info = body["dma_srchGdsDtlSrchInfo"]
        info["rprsAdongSdCd"]       = sido_code
        info["rprsAdongSggCd"]      = sgg_code
        info["lclDspslGdsLstUsgCd"] = util_code
        info["statNum"]             = stat_num   # "05"=전체, ""=진행중
        return body

    def _post_headers(self) -> dict[str, str]:
        return {
            "Content-Type":  "application/json;charset=UTF-8",
            "Accept":        "application/json",
            "Origin":        BASE_URL,
            "Referer":       ENTRY_URL + "?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml",
            "submissionid":  "mf_wfm_mainFrame_sbm_selectGdsDtlSrch",
            "sec-ch-ua":     '"Chromium";v="124","Not(A:Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def _fetch_all_pages(
        self,
        session: req_lib.Session,
        sido_code: str,
        sgg_code: str,
        max_pages: int,
        util_code: str = "",
        stat_num: str = "05",
    ) -> list[AuctionItem]:

        all_items: list[AuctionItem] = []
        total_cnt: Optional[int] = None
        page_size = _POST_TEMPLATE["dma_pageInfo"]["pageSize"]

        for page_no in range(1, max_pages + 1):
            body = self._build_body(sido_code, sgg_code, page_no, util_code, stat_num)
            self.log(f"   📄 페이지 {page_no} 요청 중...")

            try:
                resp = session.post(
                    SEARCH_URL,
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers=self._post_headers(),
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                self.log(f"   ⚠️ 요청 실패: {exc}")
                break

            if data.get("status") != 200:
                self.log(f"   ⚠️ 응답 오류: {data.get('message')}")
                break

            items = self._parse_response(data)
            all_items.extend(items)
            self.log(f"   ✅ 페이지 {page_no}: {len(items)}건")

            if total_cnt is None:
                try:
                    total_cnt = int(
                        data["data"]["dma_pageInfo"].get("totalCnt", 0) or 0
                    )
                    self.log(f"   총 {total_cnt}건")
                except Exception:
                    total_cnt = 0

            if not items or (total_cnt is not None and page_no * page_size >= total_cnt):
                break

            time.sleep(0.3)

        return all_items

    # ────────────────────────────────────────────────────────────────
    # 결과 파싱
    # ────────────────────────────────────────────────────────────────

    def _parse_response(self, data: dict) -> list[AuctionItem]:
        try:
            rows = data["data"]["dlt_srchResult"]
        except (KeyError, TypeError):
            return []
        return [item for r in rows if (item := self._row_to_item(r))]

    def _row_to_item(self, row: dict) -> Optional[AuctionItem]:
        case_num = row.get("srnSaNo", "").strip()
        if not case_num:
            return None

        item = AuctionItem()
        item.case_number = case_num
        item.court        = row.get("jiwonNm", "")

        # 표시용 전체 주소
        sido_  = row.get("hjguSido",    "").strip()
        sigu_  = row.get("hjguSigu",    "").strip()
        dong_  = row.get("hjguDong",    "").strip()
        lotno_ = row.get("daepyoLotno", "").strip()
        buld_  = row.get("buldNm",      "").strip()
        blist_ = row.get("buldList",    "").strip()
        item.address = " ".join(p for p in [sido_, sigu_, dong_, lotno_, buld_, blist_] if p)
        # 지오코딩 전용 주소 (시도+시군구+동+지번만 — 건물명/동호수 제외)
        item.geo_address = " ".join(p for p in [sido_, sigu_, dong_, lotno_] if p)

        # 물건 종류 (소→중→대 순)
        for key in ("sclsUtilCd", "mclsUtilCd", "lclsUtilCd"):
            code = row.get(key, "")
            if code and code in UTIL_CODE:
                item.property_type = UTIL_CODE[code]
                break
        if not item.property_type:
            item.property_type = row.get("lclsUtilCd", "")

        # 실제 용도 텍스트 (근린생활시설, 상가 등 직접 기재된 값)
        item.property_desc = row.get("dspslUsgNm", "").strip()

        item.appraised_value = self._to_int(row.get("gamevalAmt",  ""))
        item.min_bid         = self._to_int(row.get("minmaePrice", ""))
        item.won_bid         = self._to_int(row.get("maeAmt",      ""))
        item.failure_count   = self._to_int(row.get("yuchalCnt",   ""))

        d = row.get("maeGiil", "")
        item.auction_date = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d

        docid = row.get("docid", "")
        if docid:
            item.detail_url = (
                f"{BASE_URL}/pgj/index.on"
                f"?w2xPath=/pgj/ui/pgj100/PGJ101M01.xml&docid={docid}"
            )
        return item

    def _to_int(self, val) -> int:
        c = re.sub(r"[^0-9]", "", str(val or ""))
        return int(c) if c else 0
