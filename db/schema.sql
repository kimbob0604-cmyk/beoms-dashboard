-- Beom's Dashboard 스키마
-- 모든 수집 테이블은 as_of(수집일, YYYY-MM-DD)를 키에 포함 → 날짜별 스냅샷이 그대로 쌓임

-- 종목 기본정보 (네이버 종목분석 헤더: 시장, WICS)
CREATE TABLE IF NOT EXISTS stock_meta (
    code          TEXT PRIMARY KEY,
    name          TEXT,
    market        TEXT,          -- KOSPI / KOSDAQ / KONEX
    market_sector TEXT,          -- 거래소 업종 (예: 코스닥 화학)
    wics          TEXT,          -- WICS 업종 (예: 포장재)
    updated_at    TEXT
);

-- 연간 실적(A) + 컨센서스(E). FY-4A ~ FY+2E 7개 연도
CREATE TABLE IF NOT EXISTS consensus_annual (
    as_of        TEXT    NOT NULL,
    code         TEXT    NOT NULL,
    fy           INTEGER NOT NULL,   -- 결산연도 (2026.12 → 2026)
    fy_month     INTEGER NOT NULL,   -- 결산월 (12, 3 ...)
    is_estimate  INTEGER NOT NULL,   -- 1 = (E) 컨센서스
    basis        TEXT,               -- IFRS연결 / IFRS별도 ...
    revenue      REAL,               -- 억원
    op           REAL,               -- 영업이익, 억원
    ni           REAL,               -- 순이익(연결은 지배주주), 억원
    eps          REAL,               -- 원
    bps          REAL,
    roe          REAL,
    -- 반기 결산(리츠 등)은 한 해에 기간이 2개 → 결산월까지 키에 포함
    PRIMARY KEY (as_of, code, fy, fy_month)
);

-- 컨센서스 추이: 추정 연도별 현재 vs 1주/1개월/3개월/1년 전
CREATE TABLE IF NOT EXISTS consensus_trend (
    as_of     TEXT    NOT NULL,
    code      TEXT    NOT NULL,
    fy        INTEGER NOT NULL,
    fy_month  INTEGER NOT NULL,
    metric    TEXT    NOT NULL,      -- revenue / op / ni / eps / opinion
    cns_date  TEXT,                  -- 컨센서스 기준일 (YYYY-MM-DD)
    now       REAL,
    w1        REAL,
    m1        REAL,
    m3        REAL,
    y1        REAL,
    PRIMARY KEY (as_of, code, fy, fy_month, metric)
);

-- KRX 일별 종가·시총 (보통주 + 우선주 모두)
CREATE TABLE IF NOT EXISTS price_daily (
    date        TEXT NOT NULL,       -- YYYY-MM-DD
    code        TEXT NOT NULL,
    name        TEXT,
    market      TEXT,                -- KOSPI / KOSDAQ
    close       REAL,
    change_pct  REAL,
    mcap        REAL,                -- 억원 (해당 종목만, 우선주 미포함)
    shares      REAL,
    trd_val     REAL,                -- 거래대금, 억원
    PRIMARY KEY (date, code)
);

-- 종목별 수집 결과 (재실행 시 이어받기, 실패 추적)
CREATE TABLE IF NOT EXISTS collect_log (
    as_of       TEXT NOT NULL,
    code        TEXT NOT NULL,
    status      TEXT NOT NULL,       -- ok / no_data / error
    n_estimate  INTEGER,
    error       TEXT,
    fetched_at  TEXT,
    PRIMARY KEY (as_of, code)
);
