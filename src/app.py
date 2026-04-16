"""
주변 상가 법원경매 조회 앱
대법원 법원경매정보(courtauction.go.kr) + 카카오 Maps API
"""

import os
import time
import sys
import json
import pathlib
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

LOG_DIR = pathlib.Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def save_log(
    address: str,
    radius_m: int,
    raw_count: int,
    filtered: list,
    all_with_dist: list | None = None,
    geo_fail_list: list | None = None,
):
    """검색 결과를 logs/ 폴더에 JSON + CSV로 저장"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_addr = address.replace(" ", "_").replace("/", "-")[:40]
    stem = LOG_DIR / f"{ts}_{safe_addr}"

    def _strip(row):
        return {k: v for k, v in row.items() if not k.startswith("_")}

    meta = {
        "검색시각": datetime.now().isoformat(timespec="seconds"),
        "기준주소": address,
        "검색반경_m": radius_m,
        "전체수집건수": raw_count,
        "반경내건수": len(filtered),
        "결과": [_strip(r) for r in filtered],
        "전체거리목록": sorted(
            [_strip(r) for r in (all_with_dist or [])], key=lambda r: r["거리(m)"]
        ),
        "지오코딩실패": geo_fail_list or [],
    }
    with open(f"{stem}.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # CSV: 반경 내 결과
    df_log = pd.DataFrame([_strip(r) for r in filtered]).drop(
        columns=["상세링크"], errors="ignore"
    )
    df_log.to_csv(f"{stem}.csv", index=False, encoding="utf-8-sig")

    # CSV: 전체 거리 목록 (디버그)
    if all_with_dist:
        df_all = pd.DataFrame(
            sorted([_strip(r) for r in all_with_dist], key=lambda r: r["거리(m)"])
        ).drop(columns=["상세링크"], errors="ignore")
        df_all.to_csv(f"{stem}_all.csv", index=False, encoding="utf-8-sig")

    return f"{stem}.json"

# src 폴더를 패스에 추가
sys.path.insert(0, os.path.dirname(__file__))

from geocoder import geocode, haversine, boundary_point, reverse_geocode
from scraper import CourtAuctionScraper

load_dotenv()

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="주변 상가 경매 조회",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("⚖️ 주변 상가 법원경매 조회")
st.caption(
    "입력 주소 반경 내 법원경매 진행 중 또는 완료된 상가 물건을 조회합니다. "
    "지오코딩: 네이버 Maps API | 데이터 출처: [대법원 법원경매정보](https://www.courtauction.go.kr)"
)

# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("🔑 API 설정")
    naver_client_id = st.text_input(
        "네이버 Client ID",
        value=os.getenv("NAVER_CLIENT_ID", ""),
        help="console.ncloud.com → Maps → Geocoding",
    )
    naver_client_secret = st.text_input(
        "네이버 Client Secret",
        value=os.getenv("NAVER_CLIENT_SECRET", ""),
        type="password",
    )

    st.divider()
    st.header("🔍 검색 옵션")

    address_input = st.text_input(
        "기준 주소 (내 약국/상가)",
        placeholder="예: 서울특별시 강남구 역삼동 123-4",
    )

    radius_m = st.select_slider(
        "검색 반경",
        options=[500, 1000, 2000, 3000, 5000],
        value=2000,
        format_func=lambda x: f"{x // 1000}km" if x >= 1000 else f"{x}m",
    )

    max_pages = st.number_input(
        "최대 조회 페이지",
        min_value=1,
        max_value=50,
        value=30,
        help="페이지당 10건. 수원시 영통구 전체 이력(239건)은 24페이지 필요. 30이면 여유있게 커버됩니다.",
    )

    stat_num = st.radio(
        "조회 범위",
        options=["05", ""],
        format_func=lambda x: "전체 (낙찰완료 포함)" if x == "05" else "진행중만",
        index=0,
        help="'전체'는 과거 낙찰 완료 사례까지 포함합니다.",
    )

    extra_sigungu_input = st.text_input(
        "추가 시군구 (인접 구·군)",
        placeholder="예: 용인시 수지구, 수원시 팔달구",
        help="기준 주소 반경이 다른 시군구에 걸칠 경우 직접 추가하세요.",
    )

    show_browser = st.checkbox(
        "브라우저 보이기 (디버그)",
        value=False,
        help="체크하면 Playwright 브라우저 창이 보입니다.",
    )

    st.divider()
    st.header("📋 경매전 물건 추가")
    extra_cases_input = st.text_area(
        "사건번호 직접 입력 (경매 미시작 포함)",
        placeholder="예:\n2025타경1345\n2024타경9999",
        height=100,
        help="사건번호가 있지만 경매 기일이 아직 잡히지 않은 물건을 줄 단위로 입력하세요.\n"
             "지도에 주황색 마커로 별도 표시됩니다.",
    )
    use_playwright_fallback = st.checkbox(
        "API 실패 시 Playwright 자동 보완",
        value=True,
        help="API로 사건번호를 찾지 못하면 법원경매 사이트에 직접 접속해서\n"
             "주소·감정가 등을 파싱합니다. 건당 약 20~30초 소요됩니다.",
    )

    st.divider()
    search_btn = st.button("🔍 검색 시작", width="stretch", type="primary")

    st.divider()
    with st.expander("사용 방법"):
        st.markdown(
            """
1. 카카오 REST API 키 입력
2. 내 약국/상가 주소 입력
3. 검색 반경 설정 (기본 1km)
4. **검색 시작** 클릭

**API 키 발급 방법**
- [console.ncloud.com](https://console.ncloud.com) 접속
- AI·NAVER API → Maps → Geocoding 신청
- Application 등록 후 Client ID / Secret 복사
- 무료 (월 3,000건)
            """
        )

# ─────────────────────────────────────────────
# 검색 실행 (session_state로 결과 캐싱)
# ─────────────────────────────────────────────
import concurrent.futures

_CACHE_KEY = "auction_search_cache"

if search_btn:
    # 새 검색 → 기존 캐시 초기화
    st.session_state.pop(_CACHE_KEY, None)

# 캐시가 없고 검색 버튼도 안 눌렸으면 안내 후 종료
if not search_btn and _CACHE_KEY not in st.session_state:
    st.info("왼쪽 사이드바에서 주소와 검색 반경을 설정한 후 **검색 시작**을 눌러주세요.")
    st.stop()

# ── 실제 검색 (search_btn 클릭 시만) ──────────
if search_btn:
    # 입력 검증
    if not naver_client_id or not naver_client_secret:
        st.error("네이버 Client ID와 Client Secret을 입력해주세요.")
        st.stop()
    if not address_input:
        st.error("기준 주소를 입력해주세요.")
        st.stop()

    # ── Step 1: 주소 지오코딩 ──────────────────────
    with st.status("📍 주소 변환 중...", expanded=True) as status_box:
        try:
            my_loc = geocode(address_input, naver_client_id, naver_client_secret)
            status_box.update(label=f"📍 기준 위치: {my_loc['full_address']}", state="complete")
        except Exception as e:
            st.error(f"주소 변환 실패: {e}")
            st.info("네이버 Client ID / Secret과 주소를 확인해 주세요.")
            st.stop()

    col1, col2, col3 = st.columns(3)
    col1.metric("시/도", my_loc["sido"])
    col2.metric("시/군/구", my_loc["sigungu"])
    col3.metric("읍/면/동", my_loc["eupmyeondong"])

    # ── Step 1-b: 인접 시군구 결정 ──────────────────────────────────
    sigungu_to_search = [my_loc["sigungu"]]  # 항상 primary 포함

    # 역지오코딩으로 자동 감지 시도
    _adj_detected = []
    _adj_api_ok = True
    for bearing in [0, 90, 180, 270]:   # 북·동·남·서 방향 경계
        try:
            bp_lat, bp_lng = boundary_point(
                my_loc["lat"], my_loc["lng"], radius_m, bearing
            )
            adj = reverse_geocode(bp_lat, bp_lng, naver_client_id, naver_client_secret)
            if adj["sido"] == my_loc["sido"] and adj["sigungu"] and adj["sigungu"] not in sigungu_to_search:
                sigungu_to_search.append(adj["sigungu"])
                _adj_detected.append(adj["sigungu"])
        except Exception:
            _adj_api_ok = False

    # 사용자가 수동으로 입력한 추가 시군구 반영
    for _sg in [s.strip() for s in extra_sigungu_input.split(",") if s.strip()]:
        if _sg not in sigungu_to_search:
            sigungu_to_search.append(_sg)

    if not _adj_api_ok and not _adj_detected:
        st.warning(
            "역지오코딩 API를 사용할 수 없어 인접 시군구를 자동 감지하지 못했습니다. "
            "**추가 시군구** 입력란에 직접 입력하세요 (예: 용인시 수지구).",
            icon="⚠️",
        )

    st.info(f"🗺️ 검색 시군구: **{', '.join(sigungu_to_search)}**")

    # ── Step 2: 경매 데이터 스크래핑 ─────────────────
    with st.status(
        f"⚖️ {', '.join(sigungu_to_search)} 경매 물건 검색 중...",
        expanded=True,
    ) as status_box:
        try:
            scraper = CourtAuctionScraper(
                headless=not show_browser,
                debug=show_browser,
            )

            # Streamlit asyncio 충돌 방지: 별도 스레드에서 실행
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    scraper.search_multi,
                    sido=my_loc["sido"],
                    sigungu_list=sigungu_to_search,
                    max_pages=max_pages,
                    stat_num=stat_num,
                )
                raw_items = future.result(timeout=300)

            status_box.update(
                label=f"⚖️ 경매 물건 {len(raw_items)}건 수집 완료",
                state="complete",
            )
        except Exception as e:
            status_box.update(label="경매 검색 실패", state="error")
            st.error("경매 정보 검색 실패")
            st.code(str(e), language="text")
            st.stop()

    # ── Step 2-b: 추가 사건번호 직접 조회 (경매 미시작 포함) ──────────
    extra_case_list = [
        c.strip() for c in extra_cases_input.replace(",", "\n").splitlines()
        if c.strip()
    ]
    if extra_case_list:
        _pw_note = " (API 실패 시 Playwright 자동 보완, 건당 ~25초)" if use_playwright_fallback else ""
        with st.status(
            f"📋 추가 사건번호 {len(extra_case_list)}건 조회 중{_pw_note}...",
            expanded=True,
        ) as _cs_status:
            try:
                # Playwright 폴백 포함 시 timeout을 건당 40초로 여유있게 설정
                _timeout = 60 + len(extra_case_list) * 40 if use_playwright_fallback else 120
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    extra_items = executor.submit(
                        scraper.search_by_case_numbers,
                        extra_case_list,
                        "05",
                        use_playwright_fallback,
                    ).result(timeout=_timeout)
                existing_ids = {it.case_number for it in raw_items}
                new_extra = [it for it in extra_items if it.case_number not in existing_ids]
                raw_items = raw_items + new_extra
                _cs_status.update(
                    label=f"📋 추가 사건번호 {len(new_extra)}건 추가 (누계 {len(raw_items)}건)",
                    state="complete",
                )
            except Exception as _cs_err:
                _cs_status.update(label="추가 사건번호 조회 실패", state="error")
                st.warning(f"추가 사건번호 조회 중 오류: {_cs_err}")

    if not raw_items:
        st.warning(
            f"{', '.join(sigungu_to_search)} 에서 경매 물건을 찾지 못했습니다. "
            "검색 페이지 수를 늘려보세요."
        )
        st.stop()

    # ── Step 3: 결과 주소 지오코딩 + 거리 필터링 ──────
    with st.status(
        f"📏 {len(raw_items)}건 주소 변환 및 거리 계산 중...", expanded=True
    ) as status_box:
        filtered = []
        all_with_dist = []
        geocode_cache: dict = {}
        progress = st.progress(0)
        geo_fail = 0
        geo_fail_list = []
        out_of_range = 0

        for idx, item in enumerate(raw_items):
            progress.progress((idx + 1) / len(raw_items))

            addr_for_geo = item.geo_address or item.address
            if not addr_for_geo:
                geo_fail += 1
                geo_fail_list.append({"사건번호": item.case_number, "소재지": item.address, "이유": "주소없음"})
                continue

            cache_key = addr_for_geo[:40]
            try:
                if cache_key not in geocode_cache:
                    loc = geocode(addr_for_geo, naver_client_id, naver_client_secret)
                    geocode_cache[cache_key] = loc
                    time.sleep(0.05)
                else:
                    loc = geocode_cache[cache_key]

                dist = haversine(my_loc["lat"], my_loc["lng"], loc["lat"], loc["lng"])

                row = {
                    "사건번호": item.case_number,
                    "법원":     item.court,
                    "물건종류": item.property_type,
                    "용도설명": item.property_desc,
                    "소재지": item.address,
                    "감정가(원)": item.appraised_value,
                    "최저매각가(원)": item.min_bid,
                    "낙찰가(원)": item.won_bid,
                    "매각기일": item.auction_date or "미정",
                    "유찰횟수": item.failure_count,
                    "거리(m)": int(dist),
                    "상세링크": item.detail_url,
                    "_lat": loc["lat"],
                    "_lng": loc["lng"],
                    "_status": item.status,   # "경매전" or ""
                }
                all_with_dist.append(row)

                if dist <= radius_m:
                    filtered.append(row)
                else:
                    out_of_range += 1
            except Exception as _geo_exc:
                geo_fail += 1
                geo_fail_list.append({"사건번호": item.case_number, "소재지": item.address, "이유": str(_geo_exc)[:80]})
                continue

        progress.empty()
        status_box.update(
            label=(
                f"📏 반경 {radius_m}m 내 {len(filtered)}건 발견 "
                f"(반경 외 {out_of_range}건 / 주소변환실패 {geo_fail}건)"
            ),
            state="complete"
        )

    if not filtered:
        st.warning(
            f"반경 {radius_m}m 내 경매 물건이 없습니다. "
            f"검색 반경을 늘려보세요. (전체 수집: {len(raw_items)}건)"
        )
        st.stop()

    # ── 로그 저장 + session_state 캐시 ──────────────
    log_path = save_log(
        address_input, radius_m, len(raw_items), filtered,
        all_with_dist=all_with_dist,
        geo_fail_list=geo_fail_list,
    )

    st.session_state[_CACHE_KEY] = {
        "filtered":      filtered,
        "all_with_dist": all_with_dist,
        "raw_count":     len(raw_items),
        "my_loc":        my_loc,
        "geo_fail_list": geo_fail_list,
        "radius_m":      radius_m,
        "address_input": address_input,
        "log_path":      log_path,
        "extra_cases":   extra_case_list,
    }

# ── 캐시에서 결과 로드 (검색 후 리렌더링 포함) ────────
_cache       = st.session_state[_CACHE_KEY]
filtered     = _cache["filtered"]
all_with_dist = _cache["all_with_dist"]
my_loc       = _cache["my_loc"]
radius_m     = _cache["radius_m"]
address_input = _cache["address_input"]
log_path     = _cache["log_path"]

st.success(f"총 **{len(filtered)}건** 발견 (반경 {radius_m}m 이내)")
st.caption(f"📝 로그 저장: `{log_path}`")

# ── Step 4: 지도 표시 ──────────────────────────
st.subheader("🗺️ 지도")

m = folium.Map(
    location=[my_loc["lat"], my_loc["lng"]],
    zoom_start=15,
    tiles="CartoDB positron",
)

# 기준 위치 (파란색 집 아이콘)
folium.Marker(
    [my_loc["lat"], my_loc["lng"]],
    popup=folium.Popup(f"<b>내 약국</b><br>{address_input}", max_width=200),
    tooltip="내 위치",
    icon=folium.Icon(color="blue", icon="home", prefix="fa"),
).add_to(m)

# 반경 원
folium.Circle(
    [my_loc["lat"], my_loc["lng"]],
    radius=radius_m,
    color="#3388ff",
    fill=True,
    fill_opacity=0.06,
).add_to(m)

# 경매 물건 마커
for row in filtered:
    ratio = (
        f"{row['최저매각가(원)'] / row['감정가(원)'] * 100:.0f}%"
        if row["감정가(원)"] > 0
        else "-"
    )
    won = row.get("낙찰가(원)", 0)
    won_str = f"🏆 낙찰가: {won:,}원<br>" if won else ""
    is_pre = row.get("_status") == "경매전"
    status_badge = '<span style="background:#f90;color:#fff;padding:1px 5px;border-radius:3px;font-size:11px">경매전</span> ' if is_pre else ""
    popup_html = f"""
    <b>{status_badge}{row['사건번호']}</b><br>
    <small>{row.get('용도설명') or row['물건종류']}</small><br>
    <hr style="margin:4px 0">
    📍 {row['소재지']}<br>
    💰 감정가: {row['감정가(원)']:,}원<br>
    🔖 최저가: {row['최저매각가(원)']:,}원 ({ratio})<br>
    {won_str}📅 매각기일: {row['매각기일']}<br>
    🔄 유찰: {row['유찰횟수']}회 &nbsp; 거리: {row['거리(m)']}m
    {f'<br><a href="{row["상세링크"]}" target="_blank">상세보기 →</a>' if row['상세링크'] else ''}
    """
    marker_color = "orange" if is_pre else "red"
    tooltip_prefix = "[경매전] " if is_pre else ""
    folium.Marker(
        [row["_lat"], row["_lng"]],
        popup=folium.Popup(popup_html, max_width=280),
        tooltip=f"{tooltip_prefix}{row['사건번호']} ({row['거리(m)']}m)",
        icon=folium.Icon(color=marker_color, icon="gavel", prefix="fa"),
    ).add_to(m)

st_folium(m, width="100%", height=520, returned_objects=[])

# ── Step 5: 결과 테이블 ────────────────────────
st.subheader("📋 경매 목록")

# 거리 순 정렬
sorted_filtered = sorted(filtered, key=lambda r: r["거리(m)"])

df_display = (
    pd.DataFrame(sorted_filtered)
    .drop(columns=["_lat", "_lng", "상세링크", "법원", "_status"], errors="ignore")
    .reset_index(drop=True)
)
df_display.index = df_display.index + 1  # 1-based 번호

st.dataframe(
    df_display,
    width="stretch",
    column_config={
        "감정가(원)": st.column_config.NumberColumn("감정가(원)", format="%d"),
        "최저매각가(원)": st.column_config.NumberColumn("최저매각가(원)", format="%d"),
        "낙찰가(원)": st.column_config.NumberColumn("낙찰가(원)", format="%d"),
        "거리(m)": st.column_config.NumberColumn("거리(m)", format="%d m"),
    },
)

# ── Step 6: 앱 내 상세보기 ─────────────────────
st.subheader("🔍 상세보기")
st.caption("사건번호를 선택하면 수집된 정보와 법원경매 사이트 상세 화면을 확인할 수 있습니다.")

from detail_scraper import fetch_case_detail_screenshot

case_options = [r["사건번호"] for r in sorted_filtered]
selected_case = st.selectbox("사건번호 선택", case_options, index=0)

if selected_case:
    row = next(r for r in sorted_filtered if r["사건번호"] == selected_case)
    appraised = row["감정가(원)"]
    min_bid   = row["최저매각가(원)"]
    ratio_str = f"{min_bid / appraised * 100:.1f}%" if appraised > 0 else "-"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("거리", f"{row['거리(m)']}m")
    c2.metric("용도", row.get("용도설명") or row["물건종류"])
    c3.metric("유찰횟수", f"{row['유찰횟수']}회")
    c4.metric("매각기일", row["매각기일"])

    st.markdown(f"**소재지** : {row['소재지']}")

    won_bid = row.get("낙찰가(원)", 0)
    if won_bid:
        won_ratio = f"{won_bid / appraised * 100:.1f}%" if appraised > 0 else "-"
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("감정가", f"{appraised:,}원")
        c6.metric("최저매각가", f"{min_bid:,}원")
        c7.metric("낙찰가", f"{won_bid:,}원")
        c8.metric("낙찰가율", won_ratio)
    else:
        c5, c6, c7 = st.columns(3)
        c5.metric("감정가", f"{appraised:,}원")
        c6.metric("최저매각가", f"{min_bid:,}원")
        c7.metric("감정가 대비", ratio_str)

    st.divider()

    # ── 법원 사이트 상세보기 (Playwright 자동화) ──────────────────
    col_btn, col_opt = st.columns([2, 1])
    with col_opt:
        detail_headless = not st.checkbox(
            "브라우저 창 표시",
            value=False,
            key="detail_headless_cb",
            help="체크하면 Playwright 브라우저 창이 보입니다.",
        )
        go_to_detail = st.checkbox(
            "상세 페이지까지 이동",
            value=True,
            key="detail_navigate_cb",
            help="체크 해제 시 검색 결과 목록에서 멈춥니다.",
        )
    with col_btn:
        fetch_detail_btn = st.button(
            "⚖️ 법원경매 사이트에서 상세보기",
            key="fetch_detail_btn",
            type="primary",
            help=(
                f"대법원 법원경매정보 사이트의 경매사건검색 페이지에서 "
                f"{selected_case} 를 자동으로 조회합니다."
            ),
        )

    if fetch_detail_btn:
        court_name = row.get("법원", "")
        with st.spinner(f"{selected_case} 법원 사이트 조회 중... (약 15~20초)"):
            try:
                # Playwright sync_api는 Streamlit 이벤트 루프와 충돌하므로
                # 별도 스레드에서 실행
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _det_exec:
                    img_bytes = _det_exec.submit(
                        fetch_case_detail_screenshot,
                        selected_case,
                        court_name,
                        detail_headless,
                        go_to_detail,
                    ).result(timeout=60)
                st.image(img_bytes, caption=f"{selected_case} 법원경매 사이트 화면", use_container_width=True)
                st.download_button(
                    "📷 스크린샷 저장",
                    data=img_bytes,
                    file_name=f"{selected_case.replace(' ', '_')}_법원경매.png",
                    mime="image/png",
                )
            except Exception as _det_err:
                st.error(f"상세 조회 실패: {_det_err}")
                st.info(
                    f"직접 조회: [경매사건검색 열기](https://www.courtauction.go.kr/pgj/index.on"
                    f"?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml)"
                )

    st.caption(f"사건번호: `{row['사건번호']}` — 위 버튼 또는 사이트에서 직접 검색 가능합니다.")

# CSV 다운로드
csv_data = df_display.to_csv(encoding="utf-8-sig")
st.download_button(
    "📥 CSV 다운로드",
    data=csv_data,
    file_name=f"경매결과_{my_loc['sigungu']}.csv",
    mime="text/csv",
)

# ── 진단: 반경 외 근접 물건 ─────────────────────
nearby_outside = [
    r for r in all_with_dist
    if r["거리(m)"] > radius_m and r["거리(m)"] <= radius_m * 3
]
nearby_outside.sort(key=lambda r: r["거리(m)"])

with st.expander(f"🔎 진단: 반경 외 근접 물건 ({len(nearby_outside)}건, 반경 {radius_m}m~{radius_m*3}m)"):
    if nearby_outside:
        df_nearby = pd.DataFrame([
            {k: v for k, v in r.items() if not k.startswith("_") and k != "상세링크"}
            for r in nearby_outside
        ])
        st.dataframe(df_nearby, hide_index=True, width="stretch")
        st.caption("이 목록에 상가 물건이 있다면 반경을 늘리거나 검색 기준 주소를 조정하세요.")
    else:
        st.write("반경 3배 이내에도 추가 물건이 없습니다.")

if geo_fail_list:
    with st.expander(f"⚠️ 주소 변환 실패 목록 ({len(geo_fail_list)}건)"):
        st.dataframe(pd.DataFrame(geo_fail_list), hide_index=True, width="stretch")
        st.caption(f"전체 수집 {len(raw_items)}건 중 {len(geo_fail_list)}건은 지오코딩에 실패했습니다.")
