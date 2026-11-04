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

-- 네이버 리서치 종목분석 리포트 (m.stock.naver.com/api/research)
CREATE TABLE IF NOT EXISTS research (
    id          INTEGER PRIMARY KEY,  -- researchId
    code        TEXT NOT NULL,
    name        TEXT,
    broker      TEXT,
    date        TEXT NOT NULL,        -- 작성일 YYYY-MM-DD
    title       TEXT,
    opinion     TEXT,                 -- 매수 / Buy / 중립 …
    goal        REAL,                 -- 목표주가 (원)
    price       REAL,                 -- 작성일 주가 (원)
    heads       TEXT,                 -- 본문 소제목 JSON 배열
    body        TEXT,                 -- 본문 요약 (태그 제거)
    pdf         TEXT,
    fetched_at  TEXT
);
CREATE INDEX IF NOT EXISTS research_code ON research (code, date);

-- 종목별 투자자 순매수 (수량, 주) — stock.naver.com investor-trend
CREATE TABLE IF NOT EXISTS flow_daily (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    frgn        REAL,                 -- 외국인 순매수 수량
    org         REAL,                 -- 기관 순매수 수량
    ind         REAL,                 -- 개인 순매수 수량
    close       REAL,                 -- 종가 (금액 환산용)
    frgn_ratio  REAL,                 -- 외국인 지분율 %
    PRIMARY KEY (date, code)
);

-- 네이버 52주 신고가 목록 스냅샷 (그날 신고가를 낸 종목)
CREATE TABLE IF NOT EXISTS high52_daily (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    name        TEXT,
    market      TEXT,
    close       REAL,
    change_pct  REAL,
    mcap        REAL,                 -- 억원
    trd_val     REAL,                 -- 거래대금, 억원
    fetched_at  TEXT,
    PRIMARY KEY (date, code)
);

-- 지수 일별 (홈 탭). 순매수·프로그램(억원)·상승/하락 종목 수는 받은 날의 최근 거래일에만 채워진다
CREATE TABLE IF NOT EXISTS index_daily (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,        -- KOSPI / KOSDAQ
    close       REAL,
    change_pct  REAL,
    frgn        REAL,
    org         REAL,
    ind         REAL,
    prog        REAL,
    up          INTEGER,
    down        INTEGER,
    flat        INTEGER,
    fetched_at  TEXT,
    PRIMARY KEY (date, code)
);

-- 종목 일봉 (종목 패널 차트). KRX 일별매매정보와 같은 호출에서 받는다.
-- KRX 공개 전 네이버로 채운 날은 종가만 있고 시가·고가·저가·거래량이 비어 있다 (KRX 가 나중에 덮어씀)
CREATE TABLE IF NOT EXISTS ohlc_daily (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,                 -- 주
    PRIMARY KEY (date, code)
);

-- 지수 일봉 (홈 차트, 네이버 fchart)
CREATE TABLE IF NOT EXISTS index_ohlc (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,                 -- 천주
    PRIMARY KEY (date, code)
);

-- 지수 당일 분봉 (홈 차트)
CREATE TABLE IF NOT EXISTS index_minute (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    t           TEXT NOT NULL,        -- HH:MM
    price       REAL,
    PRIMARY KEY (date, code, t)
);

-- 장중 실행마다 받은 지수·투자자별 누적 순매수 스냅샷 (홈 당일 순매수 흐름)
CREATE TABLE IF NOT EXISTS index_snap (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    t           TEXT NOT NULL,        -- HH:MM (받은 시각)
    close       REAL,
    frgn        REAL,
    org         REAL,
    ind         REAL,
    prog        REAL,
    PRIMARY KEY (date, code, t)
);

-- 장중 전 종목 시세 (홈 실시간 갱신용, 받을 때마다 통째로 바꿈). 네이버 통합 시세
CREATE TABLE IF NOT EXISTS quote_live (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    market      TEXT,
    date        TEXT,
    close       REAL,
    change_pct  REAL,
    mcap        REAL,                 -- 억원
    trd_val     REAL,                 -- 억원
    at          TEXT
);
