"""
전국 법원경매 사건 전수 수집기

전략:
  - 시도(17개) × 연도(지정) 조합으로 bidBgngYmd/bidEndYmd 필터링
  - statNum="05" (전체: 진행중 + 낙찰완료)
  - 결과를 CSV / JSON으로 저장

사용법:
  python src/collector.py --years 2024 2025 2026 --output data/nationwide
  python src/collector.py --years 2026 --sido 경기 --output data/gyeonggi_2026
"""

import argparse
import copy
import json
import pathlib
import re
import time
from datetime import datetime
from typing import Optional

import requests

BASE_URL   = "https://www.courtauction.go.kr"
ENTRY_URL  = f"{BASE_URL}/pgj/index.on"
SEARCH_URL = f"{BASE_URL}/pgj/pgjsearch/searchControllerMain.on"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── 시도 코드 ──────────────────────────────────────────────────────────────
SIDO_LIST = [
    ("서울",  "11"), ("부산",  "26"), ("대구",  "27"), ("인천",  "28"),
    ("광주",  "29"), ("대전",  "30"), ("울산",  "31"), ("세종",  "36"),
    ("경기",  "41"), ("강원",  "51"), ("충북",  "43"), ("충남",  "44"),
    ("전북",  "52"), ("전남",  "46"), ("경북",  "47"), ("경남",  "48"),
    ("제주",  "50"),
]
SIDO_BY_NAME = {name: code for name, code in SIDO_LIST}
SIDO_BY_CODE = {code: name for name, code in SIDO_LIST}

# ── POST 바디 템플릿 ────────────────────────────────────────────────────────
_TEMPLATE = {
    "dma_pageInfo": {
        "pageNo": 1, "pageSize": 20, "bfPageNo": "",
        "startRowNo": "", "totalCnt": "", "totalYn": "Y",
        "groupTotalCount": "",
    },
    "dma_srchGdsDtlSrchInfo": {
        "rletDspslSpcCondCd": "", "bidDvsCd": "",
        "mvprpRletDvsCd": "00031R",
        "cortAuctnSrchCondCd": "0004601",
        "rprsAdongSdCd": "", "rprsAdongSggCd": "",
        "rprsAdongEmdCd": "", "rdnmSdCd": "", "rdnmSggCd": "", "rdnmNo": "",
        "mvprpDspslPlcAdongSdCd": "", "mvprpDspslPlcAdongSggCd": "",
        "mvprpDspslPlcAdongEmdCd": "", "rdDspslPlcAdongSdCd": "",
        "rdDspslPlcAdongSggCd": "", "rdDspslPlcAdongEmdCd": "",
        "cortOfcCd": "", "jdbnCd": "", "execrOfcDvsCd": "",
        "lclDspslGdsLstUsgCd": "", "mclDspslGdsLstUsgCd": "",
        "sclDspslGdsLstUsgCd": "", "cortAuctnMbrsId": "",
        "aeeEvlAmtMin": "", "aeeEvlAmtMax": "",
        "lwsDspslPrcRateMin": "", "lwsDspslPrcRateMax": "",
        "flbdNcntMin": "", "flbdNcntMax": "",
        "objctArDtsMin": "", "objctArDtsMax": "",
        "mvprpArtclKndCd": "", "mvprpArtclNm": "", "mvprpAtchmPlcTypCd": "",
        "notifyLoc": "", "lafjOrderBy": "",
        "pgmId": "PGJ151M01", "csNo": "", "cortStDvs": "2",
        "statNum": "05",
        "bidBgngYmd": "", "bidEndYmd": "",
        "dspslDxdyYmd": "", "fstDspslHm": "", "scndDspslHm": "",
        "thrdDspslHm": "", "fothDspslHm": "", "dspslPlcNm": "",
        "lwsDspslPrcMin": "", "lwsDspslPrcMax": "",
        "grbxTypCd": "", "gdsVendNm": "", "fuelKndCd": "",
        "carMdyrMax": "", "carMdyrMin": "", "carMdlNm": "", "sideDvsCd": "",
    },
}

# ── 저장할 필드 정의 ────────────────────────────────────────────────────────
SAVE_FIELDS = [
    ("사건번호",        "srnSaNo"),
    ("법원",            "jiwonNm"),
    ("경매계",          "jpDeptNm"),
    ("시도",            "hjguSido"),
    ("시군구",          "hjguSigu"),
    ("동",              "hjguDong"),
    ("지번",            "daepyoLotno"),
    ("건물명",          "buldNm"),
    ("동호수",          "buldList"),
    ("전체주소",        "printSt"),
    ("용도",            "dspslUsgNm"),
    ("용도대분류코드",  "lclsUtilCd"),
    ("용도중분류코드",  "mclsUtilCd"),
    ("구조면적",        "pjbBuldList"),
    ("면적최소",        "minArea"),
    ("면적최대",        "maxArea"),
    ("감정가",          "gamevalAmt"),
    ("최저매각가",      "minmaePrice"),
    ("낙찰가",          "maeAmt"),
    ("1회최저가",       "notifyMinmaePrice1"),
    ("2회최저가",       "notifyMinmaePrice2"),
    ("3회최저가",       "notifyMinmaePrice3"),
    ("4회최저가",       "notifyMinmaePrice4"),
    ("1회최저가율",     "notifyMinmaePriceRate1"),
    ("유찰횟수",        "yuchalCnt"),
    ("매각기일",        "maeGiil"),
    ("매각결정기일",    "maegyuljGiil"),
    ("매각장소",        "maePlace"),
    ("매각기일횟수",    "maeGiilCnt"),
    ("물건상태코드",    "mulStatcd"),
    ("진행여부",        "mulJinYn"),
    ("물건번호",        "maemulSer"),
    ("목적물번호",      "mokmulSer"),
    ("병합사건번호",    "byungSaNo"),
    ("법원전화",        "tel"),
]

# mulStatcd 코드 → 한글
MULSTAT_KR = {
    "01": "진행중",
    "02": "입찰완료",
    "03": "낙찰",
    "04": "낙찰",
    "05": "기각",
    "06": "재매각",
    "07": "취하",
    "08": "취소",
    "09": "기타",
}


def _post_headers():
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


def _acquire_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        s.get(ENTRY_URL, timeout=20)
    except Exception:
        pass
    return s


def _row_to_record(row: dict) -> dict:
    """API 응답 row → 저장용 dict."""
    rec = {}
    for col_name, api_key in SAVE_FIELDS:
        v = row.get(api_key, "")
        # 날짜 포맷 변환 (YYYYMMDD → YYYY-MM-DD)
        if api_key in ("maeGiil", "maegyuljGiil") and len(str(v)) == 8:
            v = f"{v[:4]}-{v[4:6]}-{v[6:]}"
        # 물건상태 한글 추가
        if api_key == "mulStatcd":
            rec["물건상태"] = MULSTAT_KR.get(str(v), str(v))
        rec[col_name] = v
    # 구조면적 줄바꿈 정리
    rec["구조면적"] = str(rec.get("구조면적", "")).replace("\n", " ").strip()
    return rec


def collect_sido_year(
    session: requests.Session,
    sido_code: str,
    year: int,
    util_code: str = "",
    delay: float = 0.5,
    log_fn=print,
) -> list[dict]:
    """
    특정 시도 + 연도 전체 수집.
    pageSize=20, 최대 500페이지(10,000건)까지 순회.
    """
    sido_name = SIDO_BY_CODE.get(sido_code, sido_code)
    bid_start = f"{year}0101"
    bid_end   = f"{year}1231"
    all_records: list[dict] = []
    seen_cases: set[str] = set()
    total_cnt: Optional[int] = None
    page_size = _TEMPLATE["dma_pageInfo"]["pageSize"]

    for page_no in range(1, 501):
        body = copy.deepcopy(_TEMPLATE)
        pi   = body["dma_pageInfo"]
        info = body["dma_srchGdsDtlSrchInfo"]

        pi["pageNo"]  = page_no
        pi["totalYn"] = "Y" if page_no == 1 else "N"
        info["rprsAdongSdCd"]       = sido_code
        info["lclDspslGdsLstUsgCd"] = util_code
        info["bidBgngYmd"]          = bid_start
        info["bidEndYmd"]           = bid_end

        try:
            resp = session.post(
                SEARCH_URL,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=_post_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log_fn(f"    ⚠️ p{page_no} 요청 실패: {exc}")
            break

        if data.get("status") != 200:
            log_fn(f"    ⚠️ p{page_no} 응답 오류: {data.get('message')}")
            break

        rows = data.get("data", {}).get("dlt_srchResult", []) or []
        if total_cnt is None:
            try:
                total_cnt = int(data["data"]["dma_pageInfo"].get("totalCnt") or 0)
                log_fn(f"  [{sido_name} {year}] 총 {total_cnt:,}건")
            except Exception:
                total_cnt = 0

        added = 0
        for row in rows:
            case_no = row.get("srnSaNo", "")
            mul_ser = str(row.get("maemulSer", ""))
            uid = f"{case_no}_{mul_ser}"
            if uid not in seen_cases:
                all_records.append(_row_to_record(row))
                seen_cases.add(uid)
                added += 1

        log_fn(f"    p{page_no}: {added}건 추가 (누계 {len(all_records):,})")

        if not rows or (total_cnt and page_no * page_size >= total_cnt):
            break

        time.sleep(delay)

    return all_records


def collect_nationwide(
    years: list[int],
    sido_names: Optional[list[str]] = None,
    util_code: str = "",
    output_dir: str = "data/nationwide",
    delay: float = 0.5,
    log_fn=print,
) -> dict[str, list[dict]]:
    """
    전국(또는 지정 시도) × 지정 연도 전수 수집.

    Returns
    -------
    dict: { "2024": [...records...], "2025": [...], "2026": [...] }
    """
    out_path = pathlib.Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    target_sidos = (
        [(n, SIDO_BY_NAME[n]) for n in sido_names if n in SIDO_BY_NAME]
        if sido_names else SIDO_LIST
    )

    session  = _acquire_session()
    all_data: dict[str, list[dict]] = {str(y): [] for y in years}
    seen_global: dict[str, set[str]] = {str(y): set() for y in years}

    ts_start = datetime.now().strftime("%Y%m%d_%H%M%S")

    for sido_name, sido_code in target_sidos:
        for year in years:
            y_str = str(year)
            log_fn(f"\n{'='*55}")
            log_fn(f"  수집: {sido_name}({sido_code}) / {year}년")
            log_fn(f"{'='*55}")

            records = collect_sido_year(
                session, sido_code, year,
                util_code=util_code, delay=delay, log_fn=log_fn,
            )

            # 중복 제거 (사건번호+물건번호 기준)
            for rec in records:
                uid = f"{rec.get('사건번호')}_{rec.get('물건번호')}"
                if uid not in seen_global[y_str]:
                    all_data[y_str].append(rec)
                    seen_global[y_str].add(uid)

            log_fn(f"  → {sido_name} {year}: {len(records):,}건 (전체 {len(all_data[y_str]):,}건)")
            time.sleep(delay)

    # ── 저장 ──────────────────────────────────────────────────────────────
    import csv

    for year in years:
        y_str   = str(year)
        records = all_data[y_str]
        if not records:
            continue

        # JSON
        json_path = out_path / f"{ts_start}_{y_str}_전국경매사건.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"수집시각": ts_start, "연도": year, "총건수": len(records), "데이터": records},
                f, ensure_ascii=False, indent=2,
            )

        # CSV
        csv_path = out_path / f"{ts_start}_{y_str}_전국경매사건.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            if records:
                writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
                writer.writeheader()
                writer.writerows(records)

        log_fn(f"\n✅ {year}년 저장 완료: {len(records):,}건")
        log_fn(f"   JSON: {json_path}")
        log_fn(f"   CSV : {csv_path}")

    return all_data


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="전국 법원경매 사건 전수 수집기")
    parser.add_argument(
        "--years", nargs="+", type=int, default=[2024, 2025, 2026],
        help="수집 연도 목록 (기본: 2024 2025 2026)",
    )
    parser.add_argument(
        "--sido", nargs="*", default=None,
        help="수집 시도 이름 (기본: 전국). 예: --sido 경기 서울",
    )
    parser.add_argument(
        "--util", default="",
        help="용도대분류코드 (기본: 전체). 예: 30000=상업용, 20000=주거용",
    )
    parser.add_argument(
        "--output", default="data/nationwide",
        help="저장 폴더 (기본: data/nationwide)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="페이지 간 대기 시간(초) (기본: 0.5)",
    )
    args = parser.parse_args()

    print(f"수집 연도: {args.years}")
    print(f"수집 시도: {args.sido or '전국(17개 시도)'}")
    print(f"용도 코드: {args.util or '전체'}")
    print(f"저장 경로: {args.output}")
    print()

    collect_nationwide(
        years=args.years,
        sido_names=args.sido,
        util_code=args.util,
        output_dir=args.output,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
