"""
법원경매 데이터 수집 GUI

실행:
    streamlit run src/collector_app.py

기능:
    [수집] 탭 - 시도/시군구/연도 선택 → 수집 → MySQL 저장
    [지도] 탭 - DB 데이터 지도 표시 → 클릭 → 상세보기
"""

import concurrent.futures
import os
import sys
import time
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from collector import (
    SIDO_LIST, SIDO_BY_NAME,
    get_sigungu_list, collect_by_sigungu, _acquire_session,
)
from db import (
    get_engine, init_db, upsert_records,
    load_map_data, load_case_detail,
    update_geocode, get_distinct_sidos, get_distinct_sigungus,
    get_ungeocode_count, load_ungeocode_records,
)
from geocoder import geocode, haversine
from detail_scraper import fetch_case_detail_screenshot

# ── 페이지 설정 ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="경매 데이터 수집기",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("🏛️ 법원경매 데이터 수집 & 지도")

# ── 사이드바: DB 연결 ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🗄️ MySQL 연결")
    with st.expander("연결 설정", expanded=False):
        db_host = st.text_input("Host",     value=os.getenv("MYSQL_HOST",     "localhost"))
        db_port = st.text_input("Port",     value=os.getenv("MYSQL_PORT",     "3306"))
        db_user = st.text_input("User",     value=os.getenv("MYSQL_USER",     "root"))
        db_pass = st.text_input("Password", value=os.getenv("MYSQL_PASSWORD", ""), type="password")
        db_name = st.text_input("Database", value=os.getenv("MYSQL_DATABASE", "auction_db"))

    if st.button("🔌 DB 연결 & 테이블 초기화"):
        try:
            _eng = get_engine(db_host, db_port, db_user, db_pass, db_name)
            init_db(_eng)
            st.session_state["db_engine"] = _eng
            st.success("연결 성공 & 테이블 준비 완료")
        except Exception as e:
            st.error(f"연결 실패: {e}")

    st.divider()
    st.header("🔑 네이버 API (지오코딩)")
    naver_id     = st.text_input("Client ID",     value=os.getenv("NAVER_CLIENT_ID",     ""))
    naver_secret = st.text_input("Client Secret", value=os.getenv("NAVER_CLIENT_SECRET", ""), type="password")


def _get_engine():
    """session_state에서 engine 반환, 없으면 새로 생성."""
    if "db_engine" not in st.session_state:
        try:
            eng = get_engine(db_host, db_port, db_user, db_pass, db_name)
            init_db(eng)
            st.session_state["db_engine"] = eng
        except Exception as e:
            st.error(f"DB 연결 필요: {e}")
            st.stop()
    return st.session_state["db_engine"]


# ── 탭 ────────────────────────────────────────────────────────────────────────
tab_collect, tab_map = st.tabs(["⚙️ 수집", "🗺️ 지도"])


# ══════════════════════════════════════════════════════════════════════════════
# [수집] 탭
# ══════════════════════════════════════════════════════════════════════════════
with tab_collect:
    st.subheader("시군구 단위 데이터 수집 → MySQL 저장")

    col1, col2, col3 = st.columns(3)

    with col1:
        sido_options = [name for name, _ in SIDO_LIST]
        sido_sel = st.selectbox("시도 선택", sido_options, index=8)  # 기본: 경기

    with col2:
        sgg_list = get_sigungu_list(sido_sel)
        sgg_names = [nm for nm, _ in sgg_list]
        sgg_sel = st.multiselect(
            "시군구 선택 (비어있으면 전체)",
            sgg_names,
            default=[],
            help="선택하지 않으면 해당 시도의 모든 시군구를 수집합니다.",
        )

    with col3:
        years_sel = st.multiselect(
            "수집 연도",
            [2022, 2023, 2024, 2025, 2026],
            default=[2024, 2025, 2026],
        )

    col4, col5 = st.columns(2)
    with col4:
        util_options = {
            "전체": "",
            "주거용 (20000)": "20000",
            "상업용 (30000)": "30000",
            "업무용 (40000)": "40000",
            "공업용 (50000)": "50000",
            "토지 (60000)":   "60000",
        }
        util_sel = st.selectbox("용도 필터", list(util_options.keys()))

    with col5:
        delay_sel = st.number_input(
            "요청 간격(초)", min_value=0.1, max_value=2.0,
            value=0.3, step=0.1,
            help="너무 낮으면 서버에서 차단될 수 있습니다.",
        )

    collect_btn = st.button("🚀 수집 시작", type="primary", disabled=not years_sel)

    if collect_btn:
        engine = _get_engine()
        util_code = util_options[util_sel]

        # 로그를 session_state에 누적
        log_lines: list[str] = []

        def _log(msg: str):
            log_lines.append(msg)

        save_fn = lambda recs: upsert_records(engine, recs)

        status_area = st.status(
            f"⚙️ {sido_sel} / {', '.join(sgg_sel) or '전체'} / {years_sel} 수집 중...",
            expanded=True,
        )

        log_placeholder = st.empty()

        with status_area:
            session = _acquire_session()
            t0 = time.time()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(
                    collect_by_sigungu,
                    session,
                    sido_sel,
                    sgg_sel,
                    years_sel,
                    util_code,
                    delay_sel,
                    1000,        # max_pages
                    _log,
                    save_fn,
                )
                # 진행 로그를 실시간 표시
                while not future.done():
                    if log_lines:
                        log_placeholder.text("\n".join(log_lines[-60:]))
                    time.sleep(1)

                records = future.result()

            elapsed = time.time() - t0
            log_placeholder.text("\n".join(log_lines[-60:]))

        status_area.update(
            label=f"✅ 수집 완료: {len(records):,}건 / {elapsed:.0f}초",
            state="complete",
        )

        if records:
            st.success(f"MySQL에 **{len(records):,}건** 저장 완료")
            df_preview = pd.DataFrame(records[:20])
            st.dataframe(df_preview, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# [지도] 탭
# ══════════════════════════════════════════════════════════════════════════════
with tab_map:
    st.subheader("수집 데이터 지도 조회")

    # ── 필터 ──────────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns(4)

    with fc1:
        engine = _get_engine()
        db_sidos = ["(전체)"] + get_distinct_sidos(engine)
        map_sido = st.selectbox("시도", db_sidos, key="map_sido")

    with fc2:
        if map_sido != "(전체)":
            db_sgus = ["(전체)"] + get_distinct_sigungus(engine, map_sido)
        else:
            db_sgus = ["(전체)"] + get_distinct_sigungus(engine)
        map_sgu = st.selectbox("시군구", db_sgus, key="map_sgu")

    with fc3:
        map_year = st.selectbox("연도(매각기일)", ["(전체)", "2022", "2023", "2024", "2025", "2026"])

    with fc4:
        map_usage = st.selectbox("용도", {
            "(전체)": "", "주거용": "20000", "상업용": "30000",
            "업무용": "40000", "공업용": "50000", "토지": "60000",
        }.keys())
        map_usage_code = {
            "(전체)": "", "주거용": "20000", "상업용": "30000",
            "업무용": "40000", "공업용": "50000", "토지": "60000",
        }[map_usage]

    # ── 지오코딩 보완 ──────────────────────────────────────────────────────────
    f_sido  = "" if map_sido == "(전체)" else map_sido
    f_sgu   = "" if map_sgu  == "(전체)" else map_sgu
    f_year  = "" if map_year == "(전체)" else map_year

    ungeo_cnt = get_ungeocode_count(engine, f_sido, f_sgu)
    if ungeo_cnt > 0:
        geo_col1, geo_col2 = st.columns([3, 1])
        geo_col1.caption(f"⚠️ 좌표 없는 레코드 {ungeo_cnt:,}건 (필터 기준)")
        if geo_col2.button("📍 좌표 보완 (최대 500건)"):
            if not naver_id or not naver_secret:
                st.error("사이드바에서 네이버 API 키를 입력하세요.")
            else:
                to_geo = load_ungeocode_records(engine, f_sido, f_sgu, limit=500)
                geo_ok, geo_fail = 0, 0
                bar = st.progress(0)
                for i, row in enumerate(to_geo):
                    bar.progress((i + 1) / len(to_geo))
                    addr = row.get("address") or ""
                    if not addr:
                        continue
                    try:
                        loc = geocode(addr, naver_id, naver_secret)
                        update_geocode(engine, row["case_no"], row["item_no"], loc["lat"], loc["lng"])
                        geo_ok += 1
                        time.sleep(0.05)
                    except Exception:
                        geo_fail += 1
                bar.empty()
                st.success(f"좌표 보완: 성공 {geo_ok}건 / 실패 {geo_fail}건")
                st.rerun()

    # ── 데이터 조회 ───────────────────────────────────────────────────────────
    load_btn = st.button("🔍 지도 데이터 조회", type="primary")
    if load_btn or "map_rows" in st.session_state:
        if load_btn:
            with st.spinner("DB 조회 중..."):
                rows = load_map_data(
                    engine,
                    sido=f_sido, sigungu=f_sgu, year=f_year,
                    usage_code=map_usage_code, only_geocoded=True,
                )
            st.session_state["map_rows"] = rows
        else:
            rows = st.session_state.get("map_rows", [])

        if not rows:
            st.warning("좌표가 있는 데이터가 없습니다. 위 [좌표 보완] 버튼을 먼저 실행하세요.")
        else:
            st.info(f"지도 표시: **{len(rows):,}건** (좌표 있는 것만)")

            # ── 지도 생성 ──────────────────────────────────────────────────────
            center_lat = sum(r["lat"] for r in rows) / len(rows)
            center_lng = sum(r["lng"] for r in rows) / len(rows)

            m = folium.Map(
                location=[center_lat, center_lng],
                zoom_start=12,
                tiles="CartoDB positron",
            )

            # 상태별 마커 색상
            STATUS_COLOR = {
                "진행중": "red",
                "낙찰":   "blue",
                "재매각": "orange",
                "취하":   "gray",
                "취소":   "gray",
            }

            for row in rows:
                color = STATUS_COLOR.get(row.get("status", ""), "purple")
                appraisal = row.get("appraisal") or 0
                min_bid   = row.get("min_bid")   or 0
                ratio_str = (
                    f"{min_bid / appraisal * 100:.0f}%"
                    if appraisal > 0 else "-"
                )
                popup_html = f"""
                <b>{row['case_no']}</b> ({row.get('item_no', 1)}번)<br>
                <small>{row.get('usage', '')}</small><br>
                <hr style='margin:4px 0'>
                📍 {row.get('sigungu', '')} {row.get('dong', '')}<br>
                💰 감정가: {appraisal:,}원<br>
                🔖 최저가: {min_bid:,}원 ({ratio_str})<br>
                📅 매각기일: {row.get('auction_date', '-')}<br>
                🔄 유찰: {row.get('fail_count', 0)}회<br>
                <b>상태: {row.get('status', '-')}</b>
                """
                folium.CircleMarker(
                    location=[row["lat"], row["lng"]],
                    radius=7,
                    color=color,
                    fill=True,
                    fill_opacity=0.75,
                    popup=folium.Popup(popup_html, max_width=260),
                    tooltip=f"{row['case_no']} ({row.get('status', '')})",
                ).add_to(m)

            map_result = st_folium(
                m, width="100%", height=520,
                returned_objects=["last_object_clicked_popup"],
            )

            # ── 범례 ──────────────────────────────────────────────────────────
            st.caption(
                "🔴 진행중 &nbsp;|&nbsp; 🔵 낙찰 &nbsp;|&nbsp; 🟠 재매각 "
                "&nbsp;|&nbsp; ⚫ 취하/취소 &nbsp;|&nbsp; 🟣 기타"
            )

            # ── 데이터 테이블 ─────────────────────────────────────────────────
            st.subheader("📋 목록")
            df_map = pd.DataFrame([
                {
                    "사건번호":   r["case_no"],
                    "물건번호":   r.get("item_no", 1),
                    "시군구":     r.get("sigungu", ""),
                    "동":         r.get("dong", ""),
                    "용도":       r.get("usage", ""),
                    "감정가(원)": r.get("appraisal", 0),
                    "최저매각가": r.get("min_bid", 0),
                    "낙찰가(원)": r.get("won_bid", 0),
                    "유찰횟수":   r.get("fail_count", 0),
                    "매각기일":   r.get("auction_date", ""),
                    "상태":       r.get("status", ""),
                }
                for r in rows
            ])
            df_map = df_map.sort_values("매각기일", ascending=False).reset_index(drop=True)
            df_map.index += 1
            st.dataframe(
                df_map,
                use_container_width=True,
                column_config={
                    "감정가(원)":  st.column_config.NumberColumn(format="%d"),
                    "최저매각가":  st.column_config.NumberColumn(format="%d"),
                    "낙찰가(원)":  st.column_config.NumberColumn(format="%d"),
                },
            )

            # ── 상세보기 ──────────────────────────────────────────────────────
            st.subheader("🔍 상세보기")
            case_options = [
                f"{r['case_no']} ({r.get('item_no', 1)}번)"
                for r in rows
            ]
            selected_str = st.selectbox("사건번호 선택", case_options)

            if selected_str:
                sel_case = selected_str.split(" (")[0]
                sel_item = int(selected_str.split("(")[1].replace("번)", ""))
                detail   = load_case_detail(engine, sel_case, sel_item)

                if detail:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("감정가",   f"{detail.get('appraisal',0):,}원")
                    c2.metric("최저매각가", f"{detail.get('min_bid',0):,}원")
                    c3.metric("유찰횟수",  f"{detail.get('fail_count',0)}회")
                    c4.metric("매각기일",  detail.get("auction_date", "-"))

                    st.markdown(f"**소재지**: {detail.get('address', '')}")
                    st.markdown(
                        f"**용도**: {detail.get('usage', '')} | "
                        f"**상태**: {detail.get('status', '')} | "
                        f"**법원**: {detail.get('court', '')} {detail.get('dept', '')}"
                    )

                    st.divider()

                    det_col1, det_col2 = st.columns([1, 2])
                    with det_col1:
                        headless_cb = not st.checkbox("브라우저 창 표시", key="det_headless")
                        navigate_cb = st.checkbox("상세 페이지까지 이동", value=True, key="det_nav")

                    with det_col2:
                        detail_btn = st.button(
                            "⚖️ 법원경매 사이트 상세보기",
                            type="primary",
                            key="detail_fetch_btn",
                        )

                    if detail_btn:
                        court_name = detail.get("court", "")
                        with st.spinner(f"{sel_case} 조회 중... (약 20초)"):
                            try:
                                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                                    img = ex.submit(
                                        fetch_case_detail_screenshot,
                                        sel_case,
                                        court_name,
                                        headless_cb,
                                        navigate_cb,
                                    ).result(timeout=60)
                                st.image(img, caption=f"{sel_case} 법원경매 화면", use_container_width=True)
                                st.download_button(
                                    "📷 스크린샷 저장",
                                    data=img,
                                    file_name=f"{sel_case.replace(' ', '_')}.png",
                                    mime="image/png",
                                )
                            except Exception as e:
                                st.error(f"상세 조회 실패: {e}")
