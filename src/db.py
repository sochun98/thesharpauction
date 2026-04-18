"""
MySQL 연결 및 경매 데이터 저장/조회 유틸리티

환경변수 (env_thesharpcharm.env):
    MYSQL_HOST     = localhost
    MYSQL_PORT     = 3306
    MYSQL_USER     = root
    MYSQL_PASSWORD = (비밀번호)
    MYSQL_DATABASE = auction_db
"""

import os
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ── 테이블 DDL ────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS auction_cases (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    case_no       VARCHAR(30)  NOT NULL   COMMENT '사건번호',
    item_no       INT          NOT NULL DEFAULT 1 COMMENT '물건번호',
    court         VARCHAR(50)            COMMENT '법원',
    dept          VARCHAR(30)            COMMENT '경매계',
    sido          VARCHAR(20)            COMMENT '시도',
    sigungu       VARCHAR(30)            COMMENT '시군구',
    dong          VARCHAR(30)            COMMENT '동',
    lot_no        VARCHAR(50)            COMMENT '지번',
    building      VARCHAR(100)           COMMENT '건물명',
    unit          VARCHAR(200)           COMMENT '동호수',
    address       TEXT                   COMMENT '전체주소',
    usage         VARCHAR(50)            COMMENT '용도',
    usage_code_l  VARCHAR(10)            COMMENT '용도대분류코드',
    usage_code_m  VARCHAR(10)            COMMENT '용도중분류코드',
    struct_area   TEXT                   COMMENT '구조면적',
    area_min      FLOAT                  COMMENT '면적최소',
    area_max      FLOAT                  COMMENT '면적최대',
    appraisal     BIGINT       DEFAULT 0 COMMENT '감정가',
    min_bid       BIGINT       DEFAULT 0 COMMENT '최저매각가',
    won_bid       BIGINT       DEFAULT 0 COMMENT '낙찰가',
    min_bid_1     BIGINT       DEFAULT 0 COMMENT '1회최저가',
    min_bid_2     BIGINT       DEFAULT 0 COMMENT '2회최저가',
    min_bid_3     BIGINT       DEFAULT 0 COMMENT '3회최저가',
    min_bid_4     BIGINT       DEFAULT 0 COMMENT '4회최저가',
    min_bid_rate  INT          DEFAULT 0 COMMENT '1회최저가율(%)',
    fail_count    INT          DEFAULT 0 COMMENT '유찰횟수',
    auction_date  VARCHAR(12)            COMMENT '매각기일',
    decision_date VARCHAR(12)            COMMENT '매각결정기일',
    auction_place VARCHAR(100)           COMMENT '매각장소',
    auction_count INT          DEFAULT 0 COMMENT '매각기일횟수',
    status        VARCHAR(20)            COMMENT '물건상태',
    status_code   VARCHAR(5)             COMMENT '물건상태코드',
    ongoing       VARCHAR(1)             COMMENT '진행여부(Y/N)',
    target_no     INT          DEFAULT 1 COMMENT '목적물번호',
    merged_case   VARCHAR(30)            COMMENT '병합사건번호',
    court_tel     VARCHAR(50)            COMMENT '법원전화',
    lat           DOUBLE                 COMMENT '위도(WGS84)',
    lng           DOUBLE                 COMMENT '경도(WGS84)',
    collected_at  DATETIME               COMMENT '수집시각',
    UNIQUE KEY uk_case_item (case_no, item_no),
    INDEX idx_sido_sgg   (sido, sigungu),
    INDEX idx_auction_dt (auction_date),
    INDEX idx_usage_l    (usage_code_l),
    INDEX idx_status     (status_code),
    INDEX idx_latlon     (lat, lng)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='법원경매 사건 수집 데이터';
"""

# ── 한글 컬럼명 → DB 컬럼명 매핑 ─────────────────────────────────────────────
KR_TO_DB: dict[str, str] = {
    "사건번호":       "case_no",
    "물건번호":       "item_no",
    "법원":           "court",
    "경매계":         "dept",
    "시도":           "sido",
    "시군구":         "sigungu",
    "동":             "dong",
    "지번":           "lot_no",
    "건물명":         "building",
    "동호수":         "unit",
    "전체주소":       "address",
    "용도":           "usage",
    "용도대분류코드": "usage_code_l",
    "용도중분류코드": "usage_code_m",
    "구조면적":       "struct_area",
    "면적최소":       "area_min",
    "면적최대":       "area_max",
    "감정가":         "appraisal",
    "최저매각가":     "min_bid",
    "낙찰가":         "won_bid",
    "1회최저가":      "min_bid_1",
    "2회최저가":      "min_bid_2",
    "3회최저가":      "min_bid_3",
    "4회최저가":      "min_bid_4",
    "1회최저가율":    "min_bid_rate",
    "유찰횟수":       "fail_count",
    "매각기일":       "auction_date",
    "매각결정기일":   "decision_date",
    "매각장소":       "auction_place",
    "매각기일횟수":   "auction_count",
    "물건상태":       "status",
    "물건상태코드":   "status_code",
    "진행여부":       "ongoing",
    "목적물번호":     "target_no",
    "병합사건번호":   "merged_case",
    "법원전화":       "court_tel",
}

DB_TO_KR: dict[str, str] = {v: k for k, v in KR_TO_DB.items()}

# ── 엔진 ──────────────────────────────────────────────────────────────────────

def get_engine(
    host: str = "",
    port: str = "",
    user: str = "",
    password: str = "",
    database: str = "",
) -> Engine:
    host     = host     or os.getenv("MYSQL_HOST",     "localhost")
    port     = port     or os.getenv("MYSQL_PORT",     "3306")
    user     = user     or os.getenv("MYSQL_USER",     "root")
    password = password or os.getenv("MYSQL_PASSWORD", "")
    database = database or os.getenv("MYSQL_DATABASE", "auction_db")
    url = (
        f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        "?charset=utf8mb4"
    )
    return create_engine(url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    """DB가 없으면 생성, 테이블이 없으면 생성."""
    from sqlalchemy.engine import URL as SaURL

    url     = engine.url
    db_name = url.database

    # 데이터베이스 이름 없이 기본 연결 URL 재구성 (password 노출 없이)
    base_url = SaURL.create(
        drivername=url.drivername,
        username=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        query={"charset": "utf8mb4"},
    )
    base_engine = create_engine(base_url, pool_pre_ping=True)
    with base_engine.connect() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
        conn.commit()
    base_engine.dispose()

    with engine.connect() as conn:
        conn.execute(text(_DDL))
        conn.commit()


def upsert_records(engine: Engine, records: list[dict]) -> int:
    """
    한글 컬럼명 dict 목록을 auction_cases 테이블에 upsert.
    중복(case_no + item_no)이면 업데이트.
    반환: 처리된 행 수
    """
    if not records:
        return 0

    now = datetime.now()
    db_records: list[dict] = []
    for rec in records:
        db_rec: dict = {"collected_at": now}
        for kr_key, val in rec.items():
            db_key = KR_TO_DB.get(kr_key)
            if not db_key:
                continue
            # 빈 문자열 → None (NULL)
            if val == "" or val is None:
                db_rec[db_key] = None
            else:
                db_rec[db_key] = val
        db_records.append(db_rec)

    if not db_records:
        return 0

    cols    = list(db_records[0].keys())
    col_str = ", ".join(f"`{c}`" for c in cols)
    ph_str  = ", ".join(f":{c}" for c in cols)
    upd_str = ", ".join(
        f"`{c}` = VALUES(`{c}`)"
        for c in cols
        if c not in ("case_no", "item_no")
    )
    sql = (
        f"INSERT INTO auction_cases ({col_str}) "
        f"VALUES ({ph_str}) "
        f"ON DUPLICATE KEY UPDATE {upd_str}"
    )

    with engine.connect() as conn:
        conn.execute(text(sql), db_records)
        conn.commit()

    return len(db_records)


def test_connection(engine: Engine) -> tuple[bool, str]:
    """연결 테스트. (성공여부, 메시지) 반환."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM auction_cases"))
            cnt = result.scalar()
        return True, f"연결 성공 — auction_cases: {cnt:,}건"
    except Exception as exc:
        return False, str(exc)


# ── 조회 ──────────────────────────────────────────────────────────────────────

def load_map_data(
    engine: Engine,
    sido: str = "",
    sigungu: str = "",
    year: str = "",
    usage_code: str = "",
    only_geocoded: bool = True,
) -> list[dict]:
    """
    지도 표시용 데이터 조회.
    only_geocoded=True: lat/lng 있는 것만 반환.
    """
    where = ["1=1"]
    params: dict = {}
    if sido:
        where.append("sido = :sido")
        params["sido"] = sido
    if sigungu:
        where.append("sigungu = :sigungu")
        params["sigungu"] = sigungu
    if year:
        where.append("auction_date LIKE :year_pat")
        params["year_pat"] = f"{year}%"
    if usage_code:
        where.append("usage_code_l = :usage_code")
        params["usage_code"] = usage_code
    if only_geocoded:
        where.append("lat IS NOT NULL AND lng IS NOT NULL")

    sql = f"""
        SELECT
            case_no, item_no, court, sido, sigungu, dong, address,
            usage, usage_code_l, area_min, area_max,
            appraisal, min_bid, won_bid, fail_count,
            auction_date, status, status_code, ongoing,
            lat, lng
        FROM auction_cases
        WHERE {' AND '.join(where)}
        ORDER BY auction_date DESC
        LIMIT 5000
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def load_case_detail(engine: Engine, case_no: str, item_no: int = 1) -> dict | None:
    """단일 사건 상세 데이터 반환."""
    sql = """
        SELECT * FROM auction_cases
        WHERE case_no = :case_no AND item_no = :item_no
        LIMIT 1
    """
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"case_no": case_no, "item_no": item_no}).mappings().first()
    return dict(row) if row else None


def update_geocode(engine: Engine, case_no: str, item_no: int, lat: float, lng: float) -> None:
    """lat/lng 업데이트."""
    sql = """
        UPDATE auction_cases SET lat = :lat, lng = :lng
        WHERE case_no = :case_no AND item_no = :item_no
    """
    with engine.connect() as conn:
        conn.execute(text(sql), {"lat": lat, "lng": lng, "case_no": case_no, "item_no": item_no})
        conn.commit()


def get_distinct_sidos(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT sido FROM auction_cases WHERE sido IS NOT NULL ORDER BY sido"
        )).fetchall()
    return [r[0] for r in rows]


def get_distinct_sigungus(engine: Engine, sido: str = "") -> list[str]:
    if sido:
        sql = "SELECT DISTINCT sigungu FROM auction_cases WHERE sido=:sido AND sigungu IS NOT NULL ORDER BY sigungu"
        params = {"sido": sido}
    else:
        sql = "SELECT DISTINCT sigungu FROM auction_cases WHERE sigungu IS NOT NULL ORDER BY sigungu"
        params = {}
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [r[0] for r in rows]


def get_ungeocode_count(engine: Engine, sido: str = "", sigungu: str = "") -> int:
    """좌표 없는 레코드 수."""
    where = ["lat IS NULL"]
    params: dict = {}
    if sido:
        where.append("sido = :sido")
        params["sido"] = sido
    if sigungu:
        where.append("sigungu = :sigungu")
        params["sigungu"] = sigungu
    sql = f"SELECT COUNT(*) FROM auction_cases WHERE {' AND '.join(where)}"
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar() or 0


def load_ungeocode_records(engine: Engine, sido: str = "", sigungu: str = "", limit: int = 500) -> list[dict]:
    """좌표 없는 레코드 조회 (지오코딩 보완용)."""
    where = ["lat IS NULL", "address IS NOT NULL", "address != ''"]
    params: dict = {"limit": limit}
    if sido:
        where.append("sido = :sido")
        params["sido"] = sido
    if sigungu:
        where.append("sigungu = :sigungu")
        params["sigungu"] = sigungu
    sql = f"""
        SELECT case_no, item_no, sido, sigungu, dong, lot_no, address
        FROM auction_cases
        WHERE {' AND '.join(where)}
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]
