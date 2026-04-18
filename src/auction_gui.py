"""
법원경매 데이터 수집기 — Windows 데스크톱 앱 (PySide6)

실행:
    .venv/Scripts/python.exe src/auction_gui.py
"""

import json
import logging
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime

# ── 로그 파일 설정 ────────────────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f"auction_gui_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    filename=_LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
_logger = logging.getLogger("auction_gui")

import folium

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QFont, QColor, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QComboBox, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QProgressBar, QGroupBox,
    QLineEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QAbstractItemView,
    QCheckBox, QSpinBox, QDoubleSpinBox, QSizePolicy,
    QStatusBar,
)

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SRC)

from dotenv import load_dotenv
load_dotenv(os.path.join(_SRC, "..", "env_thesharpcharm.env"))

from collector import SIDO_LIST, SIDO_BY_NAME, get_sigungu_list, collect_by_sigungu, _acquire_session
from db import (
    get_engine, init_db, upsert_records, test_connection,
    load_map_data, load_case_detail, update_geocode,
    get_distinct_sidos, get_distinct_sigungus,
    get_ungeocode_count, load_ungeocode_records,
)
from geocoder import geocode
from detail_scraper import fetch_case_detail_screenshot


# ══════════════════════════════════════════════════════════════════════════════
# 백그라운드 스레드
# ══════════════════════════════════════════════════════════════════════════════

class CollectThread(QThread):
    log_signal   = Signal(str)
    done_signal  = Signal(int)   # 완료된 레코드 수
    error_signal = Signal(str)

    def __init__(self, sido, sgus, years, util_code, delay, save_fn):
        super().__init__()
        self.sido      = sido
        self.sgus      = sgus
        self.years     = years
        self.util_code = util_code
        self.delay     = delay
        self.save_fn   = save_fn
        self._stop     = False

    def run(self):
        try:
            session = _acquire_session()
            records = collect_by_sigungu(
                session=session,
                sido_name=self.sido,
                sigungu_names=self.sgus,
                years=self.years,
                util_code=self.util_code,
                delay=self.delay,
                max_pages=1000,
                log_fn=self.log_signal.emit,
                save_fn=self.save_fn,
            )
            self.done_signal.emit(len(records))
        except Exception as e:
            tb = traceback.format_exc()
            _logger.error("수집 오류:\n%s", tb)
            self.error_signal.emit(f"{e}\n\n{tb}")


class GeocodeThread(QThread):
    log_signal  = Signal(str)
    done_signal = Signal(int, int)   # ok, fail

    def __init__(self, records, naver_id, naver_secret, engine):
        super().__init__()
        self.records      = records
        self.naver_id     = naver_id
        self.naver_secret = naver_secret
        self.engine       = engine

    def run(self):
        ok, fail = 0, 0
        for i, row in enumerate(self.records):
            addr = row.get("address", "")
            if not addr:
                continue
            try:
                loc = geocode(addr, self.naver_id, self.naver_secret)
                update_geocode(self.engine, row["case_no"], row["item_no"],
                               loc["lat"], loc["lng"])
                ok += 1
                time.sleep(0.05)
            except Exception as e:
                _logger.warning("지오코딩 실패 [%s]: %s", addr, e)
                fail += 1
            if (i + 1) % 10 == 0:
                self.log_signal.emit(f"  지오코딩 {i+1}/{len(self.records)}건 (성공 {ok}, 실패 {fail})")
        self.done_signal.emit(ok, fail)


class DetailThread(QThread):
    done_signal  = Signal(bytes)
    error_signal = Signal(str)

    def __init__(self, case_no, court, headless, navigate):
        super().__init__()
        self.case_no  = case_no
        self.court    = court
        self.headless = headless
        self.navigate = navigate

    def run(self):
        try:
            img = fetch_case_detail_screenshot(
                self.case_no, self.court, self.headless, self.navigate
            )
            self.done_signal.emit(img)
        except Exception as e:
            tb = traceback.format_exc()
            _logger.error("상세조회 오류:\n%s", tb)
            self.error_signal.emit(f"{e}\n\n{tb}")


# ══════════════════════════════════════════════════════════════════════════════
# 메인 윈도우
# ══════════════════════════════════════════════════════════════════════════════

class AuctionMainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("🏛️ 법원경매 데이터 수집기")
        self.resize(1200, 820)

        self.engine = None
        self._map_rows: list[dict] = []
        self._map_html_path = ""

        self._build_ui()
        self._connect_signals()

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_collect_tab(), "⚙️  수집")
        tabs.addTab(self._build_map_tab(),     "🗺️  지도")
        self.setCentralWidget(tabs)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"준비  |  로그: {_LOG_FILE}")
        _logger.info("=== auction_gui 시작 ===")

    # ── [수집] 탭 ─────────────────────────────────────────────────────────────

    def _build_collect_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # ── DB 연결 ────────────────────────────────────────────────────────
        db_box = QGroupBox("🗄️  MySQL 연결")
        db_layout = QGridLayout(db_box)

        self.db_host = QLineEdit(os.getenv("MYSQL_HOST", "localhost"))
        self.db_port = QLineEdit(os.getenv("MYSQL_PORT", "3306"))
        self.db_user = QLineEdit(os.getenv("MYSQL_USER", "root"))
        self.db_pass = QLineEdit(os.getenv("MYSQL_PASSWORD", ""))
        self.db_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.db_name = QLineEdit(os.getenv("MYSQL_DATABASE", "auction_db"))

        db_layout.addWidget(QLabel("Host"),     0, 0); db_layout.addWidget(self.db_host, 0, 1)
        db_layout.addWidget(QLabel("Port"),     0, 2); db_layout.addWidget(self.db_port, 0, 3)
        db_layout.addWidget(QLabel("User"),     1, 0); db_layout.addWidget(self.db_user, 1, 1)
        db_layout.addWidget(QLabel("Password"), 1, 2); db_layout.addWidget(self.db_pass, 1, 3)
        db_layout.addWidget(QLabel("Database"), 2, 0); db_layout.addWidget(self.db_name, 2, 1)

        self.btn_connect = QPushButton("🔌  연결 & 테이블 초기화")
        self.btn_connect.setFixedHeight(32)
        db_layout.addWidget(self.btn_connect, 2, 2, 1, 2)
        layout.addWidget(db_box)

        # ── 수집 설정 ──────────────────────────────────────────────────────
        col_box = QGroupBox("📋  수집 설정")
        col_layout = QGridLayout(col_box)

        # 시도
        col_layout.addWidget(QLabel("시도"), 0, 0)
        self.sido_combo = QComboBox()
        self.sido_combo.addItems([nm for nm, _ in SIDO_LIST])
        self.sido_combo.setCurrentText("경기")
        col_layout.addWidget(self.sido_combo, 0, 1)

        # 시군구 (다중선택)
        col_layout.addWidget(QLabel("시군구\n(Ctrl+클릭으로\n복수선택)"), 1, 0, Qt.AlignmentFlag.AlignTop)
        self.sgu_list = QListWidget()
        self.sgu_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.sgu_list.setFixedHeight(120)
        col_layout.addWidget(self.sgu_list, 1, 1)

        # 연도 (다중선택)
        col_layout.addWidget(QLabel("연도\n(복수선택)"), 0, 2, Qt.AlignmentFlag.AlignTop)
        self.year_list = QListWidget()
        self.year_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for y in [2022, 2023, 2024, 2025, 2026]:
            item = QListWidgetItem(str(y))
            self.year_list.addItem(item)
            if y >= 2024:
                item.setSelected(True)
        self.year_list.setFixedHeight(120)
        col_layout.addWidget(self.year_list, 0, 3, 2, 1)

        # 용도 / 딜레이
        col_layout.addWidget(QLabel("용도"), 2, 0)
        self.util_combo = QComboBox()
        self.util_combo.addItems(["전체", "주거용(20000)", "상업용(30000)", "업무용(40000)", "공업용(50000)", "토지(60000)"])
        col_layout.addWidget(self.util_combo, 2, 1)

        col_layout.addWidget(QLabel("요청간격(초)"), 2, 2)
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.1, 3.0); self.delay_spin.setValue(0.3); self.delay_spin.setSingleStep(0.1)
        col_layout.addWidget(self.delay_spin, 2, 3)

        # 버튼
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("🚀  수집 시작")
        self.btn_start.setFixedHeight(36)
        self.btn_start.setEnabled(False)
        self.btn_stop  = QPushButton("■  중지")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        col_layout.addLayout(btn_row, 3, 0, 1, 4)
        layout.addWidget(col_box)

        # ── 진행 & 로그 ───────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)   # indeterminate
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 9))
        self.log_edit.setFixedHeight(200)
        layout.addWidget(self.log_edit)

        return w

    # ── [지도] 탭 ─────────────────────────────────────────────────────────────

    def _build_map_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        # ── 필터 ──────────────────────────────────────────────────────────
        filter_box = QGroupBox("🔍  필터")
        fl = QGridLayout(filter_box)

        fl.addWidget(QLabel("시도"), 0, 0)
        self.map_sido = QComboBox(); self.map_sido.addItem("(전체)")
        fl.addWidget(self.map_sido, 0, 1)

        fl.addWidget(QLabel("시군구"), 0, 2)
        self.map_sgu = QComboBox(); self.map_sgu.addItem("(전체)")
        fl.addWidget(self.map_sgu, 0, 3)

        fl.addWidget(QLabel("연도(매각기일)"), 0, 4)
        self.map_year = QComboBox()
        self.map_year.addItems(["(전체)", "2022", "2023", "2024", "2025", "2026"])
        fl.addWidget(self.map_year, 0, 5)

        fl.addWidget(QLabel("용도"), 1, 0)
        self.map_util = QComboBox()
        self.map_util.addItems(["(전체)", "주거용(20000)", "상업용(30000)", "업무용(40000)", "공업용(50000)", "토지(60000)"])
        fl.addWidget(self.map_util, 1, 1)

        # 네이버 API
        fl.addWidget(QLabel("네이버 ID"), 1, 2)
        self.naver_id  = QLineEdit(os.getenv("NAVER_CLIENT_ID", ""))
        fl.addWidget(self.naver_id, 1, 3)
        fl.addWidget(QLabel("Secret"), 1, 4)
        self.naver_sec = QLineEdit(os.getenv("NAVER_CLIENT_SECRET", ""))
        self.naver_sec.setEchoMode(QLineEdit.EchoMode.Password)
        fl.addWidget(self.naver_sec, 1, 5)

        # 버튼들
        self.btn_load_map = QPushButton("🔍  지도 조회")
        self.btn_load_map.setFixedHeight(32)
        self.btn_load_map.setEnabled(False)
        self.btn_geocode  = QPushButton("📍  좌표 보완")
        self.btn_geocode.setFixedHeight(32)
        self.btn_geocode.setEnabled(False)
        fl.addWidget(self.btn_load_map, 2, 0, 1, 3)
        fl.addWidget(self.btn_geocode,  2, 3, 1, 3)
        layout.addWidget(filter_box)

        # ── 지도 + 테이블 분할 ─────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 지도 (QWebEngineView)
        self.web_view = QWebEngineView()
        self.web_view.setMinimumHeight(320)
        splitter.addWidget(self.web_view)

        # 테이블
        table_w = QWidget()
        table_lay = QVBoxLayout(table_w)
        table_lay.setContentsMargins(0, 0, 0, 0)

        self.map_table = QTableWidget(0, 9)
        self.map_table.setHorizontalHeaderLabels([
            "사건번호", "물건번호", "시군구", "동", "용도",
            "감정가(원)", "유찰", "매각기일", "상태",
        ])
        self.map_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.map_table.horizontalHeader().setStretchLastSection(True)
        self.map_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.map_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.map_table.setAlternatingRowColors(True)
        self.map_table.setMinimumHeight(180)
        table_lay.addWidget(self.map_table)

        # 상세보기 영역
        detail_row = QHBoxLayout()
        self.chk_headless = QCheckBox("브라우저 창 표시")
        self.chk_navigate = QCheckBox("상세 페이지까지 이동")
        self.chk_navigate.setChecked(True)
        self.btn_detail   = QPushButton("⚖️  법원경매 사이트 상세보기")
        self.btn_detail.setFixedHeight(34)
        self.btn_detail.setEnabled(False)
        detail_row.addWidget(self.chk_headless)
        detail_row.addWidget(self.chk_navigate)
        detail_row.addStretch()
        detail_row.addWidget(self.btn_detail)
        table_lay.addLayout(detail_row)

        splitter.addWidget(table_w)
        splitter.setSizes([400, 260])
        layout.addWidget(splitter)

        # 지도 로그
        self.map_log = QLabel("")
        self.map_log.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(self.map_log)

        return w

    # ── 시그널 연결 ────────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self._on_connect)
        self.sido_combo.currentTextChanged.connect(self._on_sido_changed)
        self.btn_start.clicked.connect(self._on_collect_start)
        self.btn_stop.clicked.connect(self._on_collect_stop)
        self.map_sido.currentTextChanged.connect(self._on_map_sido_changed)
        self.btn_load_map.clicked.connect(self._on_load_map)
        self.btn_geocode.clicked.connect(self._on_geocode)
        self.map_table.itemSelectionChanged.connect(self._on_table_select)
        self.btn_detail.clicked.connect(self._on_detail)

        # 초기 시군구 목록 로드
        self._on_sido_changed(self.sido_combo.currentText())

    # ── DB 연결 ───────────────────────────────────────────────────────────────

    def _on_connect(self):
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("연결 중...")
        QApplication.processEvents()
        try:
            self._log(f"DB 연결 시도: {self.db_host.text()}:{self.db_port.text()} / {self.db_name.text()}")
            eng = get_engine(
                self.db_host.text(), self.db_port.text(),
                self.db_user.text(), self.db_pass.text(),
                self.db_name.text(),
            )
            self._log("DB/테이블 초기화 중...")
            init_db(eng)
            self._log("연결 테스트 중...")
            ok, msg = test_connection(eng)
            if ok:
                self.engine = eng
                self.btn_connect.setText("✅  연결됨")
                self.btn_start.setEnabled(True)
                self.btn_load_map.setEnabled(True)
                self.btn_geocode.setEnabled(True)
                self.status_bar.showMessage(f"DB 연결 성공 — {msg}")
                self._refresh_map_sido()
                self._log(f"✅ DB 연결 성공: {msg}")
            else:
                raise RuntimeError(msg)
        except Exception as e:
            tb = traceback.format_exc()
            _logger.error("DB 연결 오류:\n%s", tb)
            self._log(f"❌ DB 연결 실패:\n{tb}")
            QMessageBox.critical(self, "DB 연결 실패",
                                 f"{e}\n\n자세한 내용은 로그 창 및\n{_LOG_FILE}\n을 확인하세요.")
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("🔌  연결 & 테이블 초기화")

    # ── 수집 탭 ───────────────────────────────────────────────────────────────

    def _on_sido_changed(self, sido_name: str):
        self.sgu_list.clear()
        for sgg_name, _ in get_sigungu_list(sido_name):
            self.sgu_list.addItem(sgg_name)

    def _on_collect_start(self):
        if not self.engine:
            QMessageBox.warning(self, "DB 미연결", "먼저 DB를 연결하세요.")
            return

        sido  = self.sido_combo.currentText()
        sgus  = [item.text() for item in self.sgu_list.selectedItems()]
        years = [int(item.text()) for item in self.year_list.selectedItems()]

        if not years:
            QMessageBox.warning(self, "연도 미선택", "수집할 연도를 선택하세요.")
            return

        util_map = {
            "전체": "", "주거용(20000)": "20000", "상업용(30000)": "30000",
            "업무용(40000)": "40000", "공업용(50000)": "50000", "토지(60000)": "60000",
        }
        util_code = util_map.get(self.util_combo.currentText(), "")

        self.log_edit.clear()
        self.progress.setVisible(True)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_bar.showMessage(f"수집 중: {sido} / {', '.join(sgus) or '전체'} / {years}")

        engine = self.engine
        save_fn = lambda recs: upsert_records(engine, recs)

        self._collect_thread = CollectThread(
            sido, sgus, years, util_code, self.delay_spin.value(), save_fn
        )
        self._collect_thread.log_signal.connect(self._log)
        self._collect_thread.done_signal.connect(self._on_collect_done)
        self._collect_thread.error_signal.connect(self._on_collect_error)
        self._collect_thread.start()

    def _on_collect_stop(self):
        if hasattr(self, "_collect_thread") and self._collect_thread.isRunning():
            self._collect_thread.terminate()
            self._log("⚠️ 수집 중지됨")
            self._collect_done_ui()

    def _on_collect_done(self, count: int):
        self._log(f"\n✅ 수집 완료: {count:,}건")
        self._collect_done_ui()
        self.status_bar.showMessage(f"수집 완료: {count:,}건")
        self._refresh_map_sido()

    def _on_collect_error(self, msg: str):
        self._log(f"❌ 오류: {msg}")
        self._collect_done_ui()
        QMessageBox.critical(self, "수집 오류", msg)

    def _collect_done_ui(self):
        self.progress.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_edit.append(line)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )
        _logger.info(msg)

    # ── 지도 탭 ───────────────────────────────────────────────────────────────

    def _refresh_map_sido(self):
        if not self.engine:
            return
        cur = self.map_sido.currentText()
        self.map_sido.blockSignals(True)
        self.map_sido.clear()
        self.map_sido.addItem("(전체)")
        self.map_sido.addItems(get_distinct_sidos(self.engine))
        idx = self.map_sido.findText(cur)
        if idx >= 0:
            self.map_sido.setCurrentIndex(idx)
        self.map_sido.blockSignals(False)

    def _on_map_sido_changed(self, sido: str):
        if not self.engine:
            return
        f_sido = "" if sido == "(전체)" else sido
        cur    = self.map_sgu.currentText()
        self.map_sgu.blockSignals(True)
        self.map_sgu.clear()
        self.map_sgu.addItem("(전체)")
        self.map_sgu.addItems(get_distinct_sigungus(self.engine, f_sido))
        idx = self.map_sgu.findText(cur)
        if idx >= 0:
            self.map_sgu.setCurrentIndex(idx)
        self.map_sgu.blockSignals(False)

    def _on_load_map(self):
        if not self.engine:
            return

        f_sido = "" if self.map_sido.currentText() == "(전체)" else self.map_sido.currentText()
        f_sgu  = "" if self.map_sgu.currentText()  == "(전체)" else self.map_sgu.currentText()
        f_year = "" if self.map_year.currentText() == "(전체)" else self.map_year.currentText()
        util_map = {
            "(전체)": "", "주거용(20000)": "20000", "상업용(30000)": "30000",
            "업무용(40000)": "40000", "공업용(50000)": "50000", "토지(60000)": "60000",
        }
        f_util = util_map.get(self.map_util.currentText(), "")

        self.status_bar.showMessage("DB 조회 중...")
        QApplication.processEvents()

        rows = load_map_data(
            self.engine,
            sido=f_sido, sigungu=f_sgu, year=f_year,
            usage_code=f_util, only_geocoded=True,
        )
        self._map_rows = rows

        ungeo = get_ungeocode_count(self.engine, f_sido, f_sgu)
        self.map_log.setText(
            f"지도 표시: {len(rows):,}건 (좌표 있음) | 좌표 없는 건: {ungeo:,}건"
        )

        if not rows:
            self.web_view.setHtml(
                "<h3 style='text-align:center;margin-top:80px;color:#888'>"
                "조회된 데이터가 없습니다.<br>수집 후 [좌표 보완]을 먼저 실행하세요.</h3>"
            )
            self.map_table.setRowCount(0)
            self.status_bar.showMessage("데이터 없음")
            return

        self._render_map(rows)
        self._fill_table(rows)
        self.status_bar.showMessage(f"지도 표시: {len(rows):,}건")

    def _render_map(self, rows: list[dict]):
        center_lat = sum(r["lat"] for r in rows) / len(rows)
        center_lng = sum(r["lng"] for r in rows) / len(rows)

        m = folium.Map(location=[center_lat, center_lng], zoom_start=13, tiles="CartoDB positron")

        STATUS_COLOR = {
            "진행중": "red", "낙찰": "blue", "재매각": "orange",
            "취하": "gray", "취소": "gray",
        }
        for row in rows:
            color = STATUS_COLOR.get(row.get("status", ""), "purple")
            appr  = row.get("appraisal") or 0
            mb    = row.get("min_bid")   or 0
            ratio = f"{mb/appr*100:.0f}%" if appr > 0 else "-"
            popup_html = (
                f"<b>{row['case_no']}</b> ({row.get('item_no',1)}번)<br>"
                f"<small>{row.get('usage','')}</small><br>"
                f"<hr style='margin:3px 0'>"
                f"📍 {row.get('sigungu','')} {row.get('dong','')}<br>"
                f"💰 감정가: {appr:,}원<br>"
                f"🔖 최저가: {mb:,}원 ({ratio})<br>"
                f"📅 {row.get('auction_date','-')} | 유찰 {row.get('fail_count',0)}회<br>"
                f"<b>{row.get('status','-')}</b>"
            )
            folium.CircleMarker(
                location=[row["lat"], row["lng"]],
                radius=7, color=color, fill=True, fill_opacity=0.75,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"{row['case_no']} ({row.get('status','')})",
            ).add_to(m)

        # 범례
        legend = """
        <div style='position:fixed;bottom:20px;left:20px;z-index:9999;
             background:white;padding:8px 12px;border-radius:6px;
             border:1px solid #ccc;font-size:12px;line-height:1.8'>
        🔴 진행중 &nbsp; 🔵 낙찰 &nbsp; 🟠 재매각 &nbsp; ⚫ 취하/취소 &nbsp; 🟣 기타
        </div>"""
        m.get_root().html.add_child(folium.Element(legend))

        tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
        m.save(tmp.name)
        tmp.close()
        self._map_html_path = tmp.name
        self.web_view.load(QUrl.fromLocalFile(tmp.name))

    def _fill_table(self, rows: list[dict]):
        self.map_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            appr = row.get("appraisal") or 0
            vals = [
                row.get("case_no", ""),
                str(row.get("item_no", 1)),
                row.get("sigungu", ""),
                row.get("dong", ""),
                row.get("usage", ""),
                f"{appr:,}",
                str(row.get("fail_count", 0)),
                row.get("auction_date", ""),
                row.get("status", ""),
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # 상태 색상
                if j == 8:
                    color_map = {
                        "진행중": QColor("#ffd6d6"),
                        "낙찰":   QColor("#d6eaff"),
                        "재매각": QColor("#ffe9cc"),
                    }
                    if v in color_map:
                        item.setBackground(color_map[v])
                self.map_table.setItem(i, j, item)

    def _on_table_select(self):
        self.btn_detail.setEnabled(bool(self.map_table.selectedItems()))

    # ── 좌표 보완 ─────────────────────────────────────────────────────────────

    def _on_geocode(self):
        if not self.engine:
            return
        nid = self.naver_id.text().strip()
        nsec = self.naver_sec.text().strip()
        if not nid or not nsec:
            QMessageBox.warning(self, "API 키 없음", "네이버 Client ID/Secret을 입력하세요.")
            return

        f_sido = "" if self.map_sido.currentText() == "(전체)" else self.map_sido.currentText()
        f_sgu  = "" if self.map_sgu.currentText()  == "(전체)" else self.map_sgu.currentText()

        records = load_ungeocode_records(self.engine, f_sido, f_sgu, limit=500)
        if not records:
            QMessageBox.information(self, "완료", "좌표 없는 레코드가 없습니다.")
            return

        self.map_log.setText(f"지오코딩 시작: {len(records)}건...")
        self.btn_geocode.setEnabled(False)
        self.status_bar.showMessage("지오코딩 중...")

        self._geo_thread = GeocodeThread(records, nid, nsec, self.engine)
        self._geo_thread.log_signal.connect(lambda m: self.map_log.setText(m))
        self._geo_thread.done_signal.connect(self._on_geocode_done)
        self._geo_thread.start()

    def _on_geocode_done(self, ok: int, fail: int):
        self.btn_geocode.setEnabled(True)
        msg = f"지오코딩 완료: 성공 {ok}건 / 실패 {fail}건"
        self.map_log.setText(msg)
        self.status_bar.showMessage(msg)

    # ── 상세보기 ──────────────────────────────────────────────────────────────

    def _on_detail(self):
        rows = self.map_table.selectedItems()
        if not rows:
            return

        row_idx  = self.map_table.currentRow()
        case_no  = self.map_table.item(row_idx, 0).text()
        item_no  = int(self.map_table.item(row_idx, 1).text())

        detail = load_case_detail(self.engine, case_no, item_no) if self.engine else {}
        court  = (detail or {}).get("court", "")

        headless = not self.chk_headless.isChecked()
        navigate = self.chk_navigate.isChecked()

        self.btn_detail.setEnabled(False)
        self.btn_detail.setText("조회 중... (~20초)")
        self.status_bar.showMessage(f"{case_no} 법원경매 사이트 조회 중...")

        self._det_thread = DetailThread(case_no, court, headless, navigate)
        self._det_thread.done_signal.connect(self._on_detail_done)
        self._det_thread.error_signal.connect(self._on_detail_error)
        self._det_thread.start()

    def _on_detail_done(self, img_bytes: bytes):
        self.btn_detail.setEnabled(True)
        self.btn_detail.setText("⚖️  법원경매 사이트 상세보기")
        self.status_bar.showMessage("상세 조회 완료")

        # 임시 파일에 저장 후 웹뷰로 표시
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(img_bytes)
        tmp.close()
        self.web_view.load(QUrl.fromLocalFile(tmp.name))

    def _on_detail_error(self, msg: str):
        self.btn_detail.setEnabled(True)
        self.btn_detail.setText("⚖️  법원경매 사이트 상세보기")
        self.status_bar.showMessage("상세 조회 실패")
        QMessageBox.critical(self, "상세 조회 실패", msg)


# ══════════════════════════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("맑은 고딕", 10))
    win = AuctionMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
