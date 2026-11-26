# 중국 대시보드 화면 구성 및 무료 자동 수집 경로 조사

조사일 2026-11-26. 검색 18회, 직접 호출 다수. 접속 시험은 한국(서울) IP의 맥에서 실행함. GitHub Actions 미국 IP 시험은 미실시이므로 '미국 IP'는 전부 `미확인`으로 둠.
akshare 함수명은 `pip install akshare`(v1.20.70) 후 `dir(akshare)`와 소스 docstring으로 확인한 값임.

## 1. 대시보드 화면 구성

| 대시보드 | 섹션 구성(순서) | 특징 | 근거 |
|---|---|---|---|
| Trading Economics China | Overview > GDP > Labour > Prices > Money > Trade > Government > (세율표) > Business > Consumer > Housing > Energy | 섹션당 지표 표 + 최근 기준월. Money에 LPR 5Y·TSF·신규대출·MLF, Trade에 컨테이너 물동량·화물 운송량(철도·항공·도로), Business에 PMI·철강/석탄/전력 생산, Housing에 신규주택판매·가격·착공·부동산투자 | https://tradingeconomics.com/china/indicators (2026-11-26 조회) |
| FRB 샌프란시스코 China Cyclical Activity Tracker | 단일 합성지수 1개 + 8개 구성 지표 | 소비자심리·전력생산·수출·고정투자·신규착공면적·산업생산·철도화물·소매판매의 YoY를 주성분분석(PCA)으로 합성. CSV·Excel 다운로드 제공, 갱신일 2026-06-09 표기 | https://www.frbsf.org/research-and-insights/data-and-indicators/china-cyclical-activity-tracker/ |
| Yicai 고빈도 지수(YHEI) | 8개 일간 구성 지수 > 주간 합성 | 30개 도시 혼잡도(AMAP), 지하철 승차(7개 도시), 석탄 소비(주요 발전소), 8개 도시 PM2.5, 30개 도시 신규주택 판매, 수입 건화물 운임(14개 항로), 바이두 '실업'·'파산' 검색량 | https://yicaiglobal.com/news/how-is-china-recovery-progressing (작성 시점 오래됨, 현재 발행 여부 미확인) |
| Capital Economics China Dashboards (유료 구독 추정) | China > China Activity Proxy > US 무역 우회 > Global Fracturing > 과잉설비 > 노동시장지표(CLMI) > 신삼양 수출(태양광·EV·배터리) | 자체 합성지표 중심. 개별 섹션·지표 상세는 비공개, 무료 여부 페이지에 미표기 | https://www.capitaleconomics.com/china-dashboards-1 |
| Rhodium/Atlantic Council China Pathfinder | 금융체계 > 혁신체계 > 시장경쟁 > 무역개방 > 직접투자개방 > 포트폴리오투자개방 | 구조개혁 점수화. 핵심 지표 연 1회, 정책 추적 분기. 경기 추적용 아님 | https://rhg.com/china-pathfinder/ |
| 동방재부(Eastmoney) 경제데이터 | 국내: CPI > PPI > GDP > PMI > 고정투자 > 신규주택가격 > 공업증가 > 소매 > 통화량 > 해관 수출입 > 외환보유 > 신규대출 > 예금 > 지준율 > LPR | 중국어 지표 목록 한 열. akshare 함수 대부분이 이 페이지를 소스로 씀 | https://data.eastmoney.com/cjsj/ |
| 애틀랜타 연준 China Macroeconomy | Overview > Downloads > Data Archives > Charts > FAQ | 대시보드 아님, 지출법 GDP·소득분배 시계열 ZIP, 반기 갱신. 원천 CEIC·Wind | https://www.atlantafed.org/cqer/research/china-macroeconomy |
| MacroMicro 중국(en.macromicro.me/macro/cn), CEIC China | 미확인 | 두 사이트 모두 WebFetch 403. 검색 결과로는 미국·중국·유럽·일본·대만 국가 메뉴 아래 차트형 구성까지만 확인. CEIC는 유료 | https://en.macromicro.me/macro/cn, https://www.ceicdata.com/en/country/china |
| Bloomberg China | 미확인 | 공개 대시보드 없음. 기사에서 Bloomberg Economics 초기 활동지표가 8개 지표 3개월 가중평균, 부동산은 1선 도시 판매면적 사용으로 확인. 터미널 유료 | https://www.bloomberg.com/news/articles/2023-07-28/china-s-weak-consumer-property-market-point-to-gloomy-economy |

화면 설계 시사점(필자 정리): 공통 순서는 `성장(GDP·산업·소비·투자) > 물가 > 통화·신용 > 무역 > 부동산 > 금리·환율·증시 > 고빈도`. 합성지수(CAT·YHEI)는 위에 한 줄, 아래에 구성 지표를 붙이는 구조임.

## 2. 지표별 무료 수집 경로

해외 접속 칸: `한국IP OK`는 2026-11-26 서울 IP에서 호출 성공을 뜻함. 미국 IP는 전부 `미확인`. akshare 공식 Q&A에 해외 접속 실패는 알려진 문제이며 프록시 또는 재시도 권고가 있다는 내용을 검색 요약으로 확인함(https://akshare.akfamily.xyz/answer.html, 원문 직접 열람은 실패).

| 지표 | 무료 출처 | 주기 | 지연 | 해외 접속 | akshare 함수 |
|---|---|---|---|---|---|
| 산업생산(공업증가) | 동방재부 데이터센터(원천 NBS) | 월 | NBS 발표 당일~수일, 시험 시 2026년 10월분까지 확보 | 한국IP OK, 미국 미확인 | `macro_china_industrial_value_added` |
| 소매판매 | 동방재부(원천 NBS) | 월 | 상동 | 한국IP OK | `macro_china_consumer_goods_retail` |
| 고정자산투자 | 동방재부 | 월(누적) | 상동. 정렬 순서·결측 있어 최신일 확인 필요 | 한국IP OK | `macro_china_fixed_asset_investment` |
| 부동산 판매·착공·투자 세부 | NBS 월간 발표문(www.stats.gov.cn, 한국IP 200). 구조화 API 미확인 | 월 | NBS 발표 시점 | 한국IP 200, 미국 미확인 | 전용 함수 없음. `macro_china_real_estate`(국방경기지수, 동방재부)만 존재 |
| 신규주택 가격(70개 도시) | 동방재부(원천 NBS) | 월 | 2026년 10월분 확보 | 한국IP OK | `macro_china_new_house_price` |
| CPI | 동방재부 | 월 | 당일~수일 | 한국IP OK | `macro_china_cpi` |
| CPI 세부(식품·코어 등) | NBS 범용 API(data.stats.gov.cn) | 월 | 미확인 | 한국IP 403(WAF UrlACL). 호출한 `macro_china_nbs_nation`은 ValueError, 원인(경로 오류/403) 미분리 | `macro_china_nbs_nation`, `macro_china_nbs_region` |
| PPI | 동방재부 | 월 | 당일~수일 | 한국IP OK | `macro_china_ppi` |
| PMI(NBS) | 동방재부 | 월 | 당월 말 | 한국IP OK | `macro_china_pmi` |
| 차신 PMI | 차신/S&P(yun.ccxe.com.cn) | 월 | 미확인 | 미확인 | `macro_china_pmi_manufacturing_cx`, `macro_china_pmi_services_cx` |
| TSF(사회융자 증량) | 상무부 데이터센터(data.mofcom.gov.cn) | 월 | 심함: 시험 시 마지막 행이 2026년 4월분(7개월 지연) | 한국IP OK(HTTP 200) | `macro_china_social_financing` |
| 신규대출 | 동방재부 | 월 | 당월 중순 | 한국IP OK | `macro_china_new_financial_credit` |
| M1·M2 | 동방재부 | 월 | 당월 중순 | 한국IP OK | `macro_china_money_supply_em` |
| 수출입(금액·YoY) | 동방재부(원천 해관) | 월 | 해관 발표 후 | 한국IP OK | `macro_china_customs_trade` |
| 원자재 수입(철광석·원유·구리 수량) | 해관 홈페이지(customs.gov.cn, 한국IP 200). 품목별 표는 HTML/Excel | 월 | 발표 후 | 미국 미확인 | 전용 함수 없음 |
| 30대 도시 신규주택 거래 | Wind 원천(유료). 무료는 증권사 주간 리포트 기사(10jqka)뿐 | 일/주 | 1주 | 미확인 | 전용 함수 없음 |
| 석탄 소비(발전소 일일 소모) | CCTD·Wind(유료). 무료 API 미확인 | 일 | - | 미확인 | 없음 |
| 지하철 이용 | 도시별 공개 통계 페이지. 통합 API 미확인 | 일 | - | 미확인 | 없음 |
| 항공 | 민항 객좌율은 Sina 매크로(월) | 월 | - | 미확인 | `macro_china_passenger_load_factor` |
| 전력 소비 | Sina 매크로 | 월 | 시험 시 2026.9까지 | 한국IP OK | `macro_china_society_electricity` |
| SCFI·CCFI | 상하이항운교역소(www.sse.net.cn). 지수 소개 페이지 HTTP 200, 이력 API는 미확인. 매주 금요일 공표, 속보는 동방재부·cnfin 기사 | 주 | 당일 | 한국IP 200, 미국 미확인 | 직접 함수 없음. 대용: `futures_zh_daily_sina(symbol='EC0')`(INE 유럽선 선물, 2026-11-26 종가 3253 확인), `index_wci_drewry`(Drewry WCI, 한국IP OK), `macro_china_freight_index`(BDI 등, 컨테이너 SCFI 없음) |
| 철강 재고 | 거래소 창고 재고(철근): 동방재부. 사회재고(Mysteel)는 유료 | 일 | 당일 | 한국IP OK | `futures_inventory_em(symbol='螺纹钢')`, `futures_inventory_99` |
| LPR(1년·5년) | 동방재부(원천 PBoC) | 월(20일) | 당일 | 한국IP OK. 2026-11-20 1Y 3.0, 5Y 3.5 확인 | `interest_rate_lpr_em` |
| 국채 10년 | 동방재부 중미 국채 비교 / 중국채권정보망 | 일 | 당일~1일 | 한국IP OK. 2026-11-26 1.5912% / 2026-11-25 1.5914% | `bond_zh_us_yield_em`, `bond_china_yield` |
| CNY 환율 | yfinance `CNY=X`, FRED `DEXCHUS` | 일 | 당일~1주 | 한국IP OK. CNY=X 6.6512 (11-26), DEXCHUS 6.677 (11-20) | `fx_hist_em`(미시험) |
| CSI300 | yfinance `000300.SS`(3900.55, 11-26 확인) | 일 | 당일 | 한국IP OK | `index_zh_hist_em`는 호출 시 동방재부 push2 IP 제한 오류, 대체 `index_zh_daily_sina` 미시험 |
| 항셍테크 | yfinance `HSTECH.HK`(3417.38, 11-26 확인). `^HSTECH`는 데이터 없음 | 일 | 당일 | 한국IP OK | `index_hk_daily_sina`(미시험) |

## 3. 해외 접속 불가 시 대체 출처 (한국IP 시험)

| 출처 | 결과 | 비고 |
|---|---|---|
| FRED CSV(fredgraph.csv) | 접속 OK. `DEXCHUS` 일간 2026-11-20, `XTEXVA01CNM667S`·`XTIMVA01CNM667S`(수출·수입 금액) 2026-09, `QCNR628BIS`(BIS 비금융 신용 등) 2026-04 | 중국 CPI(`CHNCPIALLMINMEI`)는 2025-04, M2(`MYAGM2CNM189N`)는 2019-08에서 끊김. OECD 계열 중단 시리즈 많음 |
| BIS Stats API(stats.bis.org) | 접속 OK. 중국 실질실효환율(`WS_EER`, `M.R.B.CN`) 2026-10 = 92.92 | 구조 코드를 맞춰야 함(WS_TC 임의 키는 오류) |
| IMF | `www.imf.org/external/datamapper` 403(Akamai 거부), `dataservices.imf.org` 접속 실패 | 한국IP 기준 미사용 권고. 미국 IP 미확인 |
| Trading Economics | 웹 페이지 접속 OK(지표 표 열람). API guest 키는 폐지(HTTP 410), 유료 플랜 필요 | 무료 자동 수집 불가 |
| yfinance | CSI300·CNY·HSI·KWEB·FXI 호출 OK | 비공식 API이므로 형식 변경 위험 |
| 세계은행 API | 접속 OK(HTTP 200) | 연간 위주 |

## 4. 미확보·확인 필요

- 미국 IP(GitHub Actions)에서 위 중국 호스트 접속: 전부 미확인. 첫 워크플로에서 호스트별 HTTP 코드 로그 필요.
- NBS 데이터포털(data.stats.gov.cn) 한국 IP 403(UrlACL). 미국 IP는 미확인이며 NBS 월간 발표문 HTML(www.stats.gov.cn, 200)을 대체 후보로 둠.
- 30대 도시 신규주택 거래, 석탄 소비, 지하철, 항공 일간: 무료 API 미확인.
- SCFI·CCFI 이력 데이터 무료 API 미확인(공식 사이트 이력 페이지는 열람만 확인).
- MacroMicro·CEIC·Bloomberg 화면 구성: 직접 열람 실패.
- 동방재부 push2 계열(시세) IP 제한 위험: akshare 오류 메시지에서 5분~40분 제한 확인. 지표 계열(datacenter-web)은 호출 성공.
- 소스 URL 중 akshare `macro_china_social_financing`(상무부)은 7개월 지연, `macro_china_fdi`는 2023-07에서 종료(akshare 문서).
- 산식·정렬: akshare 반환 표는 오름차순·내림차순이 함수마다 다름. 수집 코드에서 날짜 최대값 기준 정렬 필요.
