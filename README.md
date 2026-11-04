# Beom's Dashboard

이익 성장 · 컨센 리비전 · 신고가 · 수급 대시보드. 종목을 누르면 차트·리포트 키워드·목표가·수급을 보는 상세 패널이 열린다.
구조: Python 수집기 → SQLite(`db/dashboard.db`) → 날짜별 JSON → 정적 프론트.

## 1단계: 연간 컨센서스 수집 (완료)

출처는 네이버 종목분석의 컨센서스 탭(navercomp.wisereport.co.kr, FnGuide 제공)이다.

| 응답 | 내용 |
|---|---|
| `c1050001_data.aspx?flag=2` | 연간 실적·추정 FY-4A ~ FY+2E (매출/영업이익/순이익(지배)/EPS/BPS/ROE) |
| `c1050001_data.aspx?flag=4&yymm=` | 추정 연도별 컨센서스 추이: 현재 / 1주 / 1개월 / 3개월 / 1년 전 |
| `c1010001.aspx` 헤더 | 시장(KOSPI/KOSDAQ), 거래소 업종, WICS |

- 주재무제표(보통 연결) 기준으로 먼저 받고, 추정치가 없으면 별도 기준으로 다시 받는다. 단 시총 500억 이상만.
- `sDT`(날짜) 파라미터는 무시되고 항상 최신값이 온다. 그래서 과거 백필은 안 되지만, 1주·1개월·3개월 전 비교값은 응답 자체에 들어 있다.
- 매일 실행하면 `as_of` 날짜별 스냅샷이 쌓인다. 이것이 대시보드의 기준일 선택에 쓰인다.
- 출처 고지: FnGuide는 사전 허가 없는 DB화·무단 사용을 금지한다. 화면 하단에 출처와 권리 고지를 단다(공개 배포는 3단계 참고).

```bash
python3 collect_consensus.py --codes 251970        # 특정 종목
python3 collect_consensus.py --limit 100            # 시총 상위 100
python3 collect_consensus.py                        # 전체 (오늘 이미 받은 종목은 건너뜀, 중단 후 재실행 가능)
python3 collect_consensus.py --check                # 오늘 결과 점검 (형식 변경 의심 시 exit 2)
python3 -m unittest discover -s tests -t .          # 파서 테스트
```

## 2단계: 가격·시총 + 성장률 JSON (완료)

```bash
python3 collect_prices.py                 # KRX 최근 거래일 종가·시총 (--days 30 으로 백필)
python3 build_growth.py                   # public/data/growth/{기준일}.json + dates.json
```

- 가격 출처는 KRX Open API 일별매매정보다. 시장별로 한 번 호출하면 전 종목이 온다. 키는 `.env`의 `KRX_API_KEY`이고, 없으면 `~/stock-dashboard/.env`에서 읽는다.
- 종가는 KRX 정규장 종가다. NXT 애프터마켓은 포함하지 않는다.
- 종목 목록(`universe.py`)은 최근 거래일 KRX 보통주를 쓴다. 가격 데이터가 없을 때만 기존 DB로 대체한다.
- 계산 로직은 `growth.py`(순수 함수, `tests/test_growth.py`)에 있다.
  - 올해 FY = 기준일 이후 처음 끝나는 결산기. 12월 결산이면 기준일의 연도다.
  - 기간은 y0 = 올해→내년, y1 = 내년→내후년이다.
  - 구간: 흑자전환 / 100% 이상 / 50~100% / 0~50% / 감익(적자전환 포함) / 적자 지속
  - 배수: 영업이익→POR, 순이익→PER, 매출→PSR은 시총(보통주+우선주) ÷ 값. EPS는 주가 ÷ EPS.
  - 기저: 출발값이 30억 미만이거나 시총의 1% 미만이면 표시한다. EPS는 EPS/주가가 1% 미만일 때.
  - 연속 증익은 화면 시계열(최근 5개 연도) 안에서 흑자 상태로 연속 증가한 햇수다.
  - 리비전은 '다음 연도' 추정치의 현재값을 1주·1개월·3개월 전과 비교한다.
  - 결산월이 섞여 있으면(결산월 변경, 반기 결산) 최신 결산월 행만 쓴다.
- 컨센서스는 기준일 이하가 컨센 기준일인 가장 최근 스냅샷을 쓴다. 미래 데이터를 끌어오지 않기 위해서다. 그래서 수집을 시작하기 전 날짜는 빌드할 수 없다.
- 시장·업종 합계와 필터·정렬은 프론트에서 계산한다.

## 3단계: 이익 성장 화면 (완료)

```bash
python3 serve.py                          # http://127.0.0.1:8765 (이 컴퓨터에서만 접속)
```

- 정적 페이지다: `public/growth.html`(2026-11-04 홈 탭이 생기며 index.html 에서 옮김), `public/css/app.css`, `public/js/util.js`(포맷·테마 공통), `public/js/growth.js`(이 탭).
- 빌드도 프레임워크도 없다. `data/growth/dates.json`과 `{기준일}.json`을 읽어 브라우저에서 필터·정렬·합계를 계산한다.
- 필터 상태는 URL 쿼리에 남는다. 예: `?metric=ni&market=KOSDAQ&sort=peg`. 북마크하면 같은 화면이 다시 열린다.
- 화면 규칙 (원본 스크린샷 형태: 시장별 흰 카드 안에 종목을 줄로 나열, 색은 성장률·변화율 숫자에만)
  - 성장률 순: 흑자전환 → 성장률 높은 순 → 기저 종목 → 적자 지속. 기저 종목은 출발값이 작아 성장률이 과장되므로 뒤로 보낸다. 흑자전환과 적자 지속은 성장률이 정의되지 않아 증가액 순으로 놓는다.
  - 배수 낮은 순: 내년 배수(POR/PER/PSR) 오름차순. 적자라 배수가 없으면 뒤로 간다.
  - 성장률+배수: 내년 배수 ÷ 성장률(%)의 오름차순(PEG 방식). 역성장·적자는 뒤로 간다.
  - 컨센 상향 순: 다음 연도 추정치의 1개월 변화가 큰 순이다. 같으면 3개월 변화로 가른다.
  - 구간 카운트는 구간 필터를 무시한다. 구간을 누르면 그 구간만 보인다.
  - 업종 합계는 업종·구간·검색 필터를 무시하고 시장·시총·체크 필터만 적용한다. WICS 2종목 이상만 보인다.
  - 합계 성장률은 Σ내년 ÷ Σ올해 − 1이다. EPS는 더할 수 없어서 중앙값을 쓴다.
  - 배지
    - 연속 증익: 화면 5개 연도 안에서 3년 이상일 때 붙는다.
    - 상향/하향: '다음 연도' 추정치가 1개월 전보다 ±1% 이상 바뀌었을 때 붙는다.
    - 기저: 2단계 기저 규칙을 따른다.
  - 필터 '연속 증익만', '상향만'은 배지 기준과 같다.
  - 보기 전환은 헤더 오른쪽에 있다.
    - 목록: 기본이다.
    - 간단히: 연도별 실적 줄을 숨긴다.
    - 표: 두 시장을 한 표에 모은다. 같은 기간의 다른 지표 성장률 열이 붙는다. 열 제목을 누르면 정렬되고, 한 번 더 누르면 반대 순서다(`dir=r`).
  - 요약과 업종 합계는 접을 수 있다. 펼침 상태는 브라우저에 기억된다(요약은 기본 펼침).
  - 글꼴은 Pretendard(jsDelivr CDN)를 쓴다. 오프라인이면 시스템 글꼴로 대체된다.
- 공개 사이트: https://kimbob0604-cmyk.github.io/beoms-dashboard/ (GitHub Pages, `gh-pages` 브랜치)
  - `publish.py`가 화면 파일과 최근 90일 데이터를 `gh-pages`에 커밋 하나로 강제 푸시한다. 매일 쌓이는 JSON 때문에 저장소 히스토리가 불어나지 않게 하기 위해서다.
  - `main` 브랜치에는 코드만 둔다. DB·`.env`·로그·`public/data/`는 `.gitignore`로 뺀다.
  - 수집은 맥에서 하고 배포만 GitHub이 맡는다. 맥이 꺼져 있어도 마지막으로 배포된 화면은 열린다.
  - 주의: FnGuide 약관은 사전 허가 없는 DB화·재배포를 금지한다. 공개 배포는 사용자 판단으로 했다.

## 4단계: 매일 자동 실행 (완료)

`daily.py`가 차례로 돌린다: 가격 → 컨센서스 → 이익 성장 빌드 → 네이버(리포트·신고가·수급·지수) 수집·빌드 → 홈·종목 차트 빌드 → GitHub Pages 배포. 장중 10분 간격 홈 갱신은 `live.py`(아래 6단계).
launchd가 월~토 07:10·12:10, 월~금 20:40에 부른다. 20:40은 그날 수급·신고가·임시 종가를 저녁에 반영하기 위해서다. 네이버 투자자별 매매동향은 넥스트레이드 시간외가 끝난 뒤 20:20 무렵 올라온다(2026-11-03 확인).
KRX 일별 가격은 다음 날 아침에 열리므로, 그 전까지는 네이버 전 종목 시세(시간외 포함 통합 가격)로 그날 종가를 임시로 채우고 KRX 가 열리면 덮어쓴다.

- 07:10 실행: 컨센서스를 받는다.
  - 월요일: 전체 약 2,700종목(약 1시간).
  - 화~토: 직전 스냅샷에서 추정치가 있던 종목과 아직 제대로 받아 본 적 없는 종목만 받는다(약 750종목, 15분 안팎, `--covered-only`). 요청 수를 줄여 서버 차단을 피하기 위해서다. 새로 커버리지가 생긴 종목은 다음 월요일에 들어온다.
- 12:10 실행: 07:10에 못 받은 종목과 아직 안 열렸던 KRX 가격을 채운다. 같은 날 다시 돌려도 안전하다.
- 맥이 잠자기 상태였다면 깨어난 뒤 바로 실행된다. 평일 06:05~22:05에는 `com.kbj.awake`가 잠자기를 막는다.
- 로그는 `logs/daily_YYYYMMDD.log`에 남는다. 경고·실패는 macOS 알림으로 뜬다.
- 안전장치
  - 컨센서스 서버가 연속 8종목 네트워크 실패를 내면 수집을 멈춘다(종료 코드 3). 다음 실행이 실패한 종목부터 이어 받는다. 막힌 서버에 계속 요청하지 않기 위해서다.
  - 컨센서스 점검이 2(커버리지 급감)나 3이면 빌드하지 않는다.
  - 빌드는 추정치 보유 종목 수가 역대 최대의 90% 미만인 스냅샷을 건너뛰고, 그 전의 온전한 스냅샷을 쓴다.
- 설치본은 `~/Library/LaunchAgents/`에 복사된 파일이다. `launchd/`의 plist를 고치면 다시 복사하고 bootout → bootstrap 한다.

```bash
# 설치 (한 번)
cp launchd/com.kimbob.beomdashboard.daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kimbob.beomdashboard.daily.plist

# 지금 한 번 돌려보기 / 상태 / 해제
launchctl kickstart gui/$(id -u)/com.kimbob.beomdashboard.daily
launchctl print gui/$(id -u)/com.kimbob.beomdashboard.daily | grep -E "state|last exit"
launchctl bootout gui/$(id -u)/com.kimbob.beomdashboard.daily
```

## 5단계: 종목 상세 · 컨센 리비전 · 신고가 · 수급 (완료)

출처는 네이버 증권이다. 네이버 API는 다른 사이트의 브라우저 호출을 막아서(CORS 403) 차트 이미지만 브라우저가 직접 받고, 나머지는 맥에서 받아 JSON으로 만든다.

| 응답 | 내용 |
|---|---|
| `m.stock.naver.com/api/research/company?page=&pageSize=100` | 종목분석 리포트 목록 (하루 약 50건) |
| `m.stock.naver.com/api/research/company/{id}` | 리포트 요약 본문·투자의견·목표주가 |
| `stock.naver.com/api/stockSecurity/investor-trend/v2/domestic/{code}?exchangeType=krx` | 일별 외국인·기관·개인 순매수 수량, 외국인 지분율 |
| `m.stock.naver.com/api/stocks/high52week/{KOSPI\|KOSDAQ}` | 그날 52주 신고가 종목 |
| `ssl.pstatic.net/imgfinance/chart/item/{area/day\|candle/day\|candle/week\|candle/month}/{code}.png` | 차트 이미지 (브라우저가 직접, 캐시 12초) |

```bash
python3 collect_naver.py research --days 90   # 리포트 백필 (평소엔 최근 14일 목록에서 새 리포트만)
python3 collect_naver.py flow                 # 수급 (처음 받는 종목은 60거래일, 이후 10거래일)
python3 collect_naver.py high                 # 52주 신고가 목록
python3 build_naver.py                        # flow/·high/·reports/·stocks/ JSON
```

- 종목 상세 패널: 어느 탭에서든 종목 이름을 누르면 오른쪽에 열린다. ⌘/Ctrl+클릭은 네이버 증권 새 탭이다. 주소 `#005930`으로 바로 열 수 있다.
  - 차트는 네이버 이미지라 장중(08:50~15:40)에는 30초마다 다시 받는다.
  - 리포트는 최근 90일이다. 목표가 변경은 같은 증권사의 직전 리포트와 비교한다. 네이버의 prevGoalPrice는 작성일 주가와 같은 값이라 쓰지 않는다.
  - 키워드(`keywords.py`, 형태소 분석기 없이 동작)
    - 리포트 글에서 조사·어미를 떼고, 숫자·기간 표기·흔한 말을 뺀다.
    - '이 종목의 여러 리포트가 함께 쓴 말 × 다른 종목 리포트엔 드문 말(idf)' 순으로 8개를 고른다.
    - 키워드마다 그 말이 든 문장을 최신 리포트부터 3개까지 붙인다. 종목명 조각은 키워드에서 뺀다.
- 컨센 리비전 탭: 이익 성장 JSON의 추정치 변화를 그대로 쓴다. 올해(FY0) 추정치 변화(`bw1/bm1/bm3`)를 빌드에 추가했다.
  - 추정치 보기: 연도·지표·기간별 상향/하향 종목, 시장별 상향·하향 종목 수와 합계 변화, 업종별 리비전.
  - 목표가 보기: 최근 1일/1주/1개월 리포트의 목표가 상향·하향. 상향(하향)이 많은 종목을 위에 칩으로 모은다.
- 수급 탭: 시총 1,000억 이상 보통주 + 컨센서스·리포트가 있는 종목(약 1,400종목)이 대상이다. 시장 전체 합계와는 다르다.
  - 금액은 순매수 수량 × 그날 정규장 종가로 어림한다. 주체는 외국인/기관/외국인+기관, 기간은 1·5·20·60일이다. 금액 순 또는 시총 대비 순으로 본다.
- 신고가 탭: 네이버 52주 신고가 목록을 매일 쌓는다. 신고가 횟수·연속 일수·'최근 20거래일 신고가'는 쌓기 시작한 날(2026-11-03)부터 센다.
  - 12:10 실행은 장중 목록을 저장하고, 20:40이나 다음 날 07:10 실행이 마감 목록으로 덮어쓴다.
- KRX 종가는 다음 날 아침에 열린다. 그 전에는 collect_prices.py 가 네이버 전 종목 시세로 그날 가격을 임시로 채운다.
- 안전장치: 네이버 요청은 0.2초 간격이다. 연속 8회 네트워크 실패면 멈춘다(종료 코드 3). 컨센서스 서버와 별개라 컨센서스가 막혀도 네이버는 받는다.
- 리포트 요약의 권리는 각 증권사에 있다. 화면에는 소제목·키워드 문장만 보이고 원문은 네이버·PDF 링크로 연결한다.

## 6단계: 홈 (완료)

`public/index.html` + `public/js/home.js`, 데이터는 `public/data/home.json`(build_home.py). 차트는 `public/js/plot.js`(SVG, 외부 라이브러리 없음)로 직접 그려 마우스·손가락을 올린 시각·날짜의 값을 보여준다.

```bash
python3 collect_naver.py index    # 지수 60거래일 종가·1년 일봉·당일 1분봉 + 그날 투자자별·프로그램 순매수 → index_daily·index_ohlc·index_minute·index_snap
python3 collect_naver.py quotes   # 전 종목 장중 시세 → quote_live
python3 build_home.py             # 다른 탭 JSON 과 DB 에서 홈에 보일 것만 모음 (build_growth·build_naver 뒤)
python3 build_charts.py           # 종목 패널 차트: public/data/chart/{code}.json (보통주 전부, 최근 260거래일 일봉)
python3 live.py --force           # 장중 갱신 한 번 (index + quotes → build_home → publish)
```

- 지수 카드(코스피·코스닥·코스피200 선물 최근월물): 당일(1분봉, 전일 종가 위는 빨강·아래는 파랑), 3개월(캔들 + 20·60일 이동평균 + 거래량), 1년(종가 선). 마우스를 올리면 헤더 숫자가 그 시각 값으로 바뀐다.
  선물은 네이버 `index/FUT` 응답을 쓴다. 선물 투자자별 순매수는 네이버가 단위를 표시하지 않아 받은 숫자 그대로 보여준다(지수는 억원). 거래량은 계약.
  당일 아래 칸은 투자자별 누적 순매수 흐름이다. 네이버의 시간대별 순매수 API 가 없어져서, 장중 실행(10분마다)이 받은 누적값을 이어 그린다. 그래서 장중 실행이 두 번 이상 돌아야 보인다.
- 업종 지도 / 시총 상위 지도: 크기 = 시총의 0.6제곱(반도체·삼성전자가 화면을 다 차지하지 않게), 색 = 등락률(±3%에서 가장 진함).
- 카드: 급등·급락, 외국인+기관, 52주 신고가, 추정치 리비전, 목표가 변경, 최신 리포트. 상승/하락 탭과 해당 탭으로 가는 링크.
- 종목 패널 차트: 3개월·6개월·1년 일봉, 주봉(1년). 5·20·60일(주봉은 13·26주) 이동평균과 거래량. 일봉은 KRX 일별매매정보(가격 수집과 같은 호출)에서 받는다(`ohlc_daily`).
  처음 한 번 `python3 collect_prices.py --ohlc-days 380` 으로 1년치를 채웠다(2026-11-05, 약 9분). KRX 공개 전 네이버로 채운 날은 종가만 있어 짧은 가로선으로 그린다.

### 장중 갱신 (live.py)

브라우저에서 네이버 JSON 을 바로 부를 수 없어서(CORS 403) 맥이 받아 올린다.
launchd(`com.kimbob.beomdashboard.live`)가 10분마다 부르고, 평일 09:00~15:50 밖이면 바로 끝난다. daily.py 가 돌고 있으면 건너뛴다.
화면은 장중에 1분마다 home.json 이 바뀌었는지 확인해 다시 그린다. GitHub Pages 반영까지 1분 안팎이 더 걸린다.
10분 간격은 GitHub Pages 빌드 한도(시간당 10회 안팎) 때문이다.

publish.py 는 배포용 저장소(`.publish/`, gitignore)를 지우지 않고 두어 원격에 이미 있는 파일은 다시 올리지 않는다. 장중 배포는 home.json 만 바뀌어 몇 초면 끝난다.

```bash
cp launchd/com.kimbob.beomdashboard.live.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kimbob.beomdashboard.live.plist
```

## 7단계: 공시 (DART)

`public/dart.html` + `public/js/dart.js`(화면) + `public/js/dartfmt.js`(공시 한 건 → 문장, 홈·종목 패널 공통). 데이터는 `public/data/dart/{접수일}.json`, 종목별 `data/dart/s/{code}.json`(build_dart.py).

```bash
python3 collect_dart.py             # 오늘·어제 공시 (처음 보는 공시만 원문을 받아 항목을 읽음) → dart_filing
python3 collect_dart.py --days 21   # 백필 (2026-11-05 에 3주치, 약 5분)
python3 collect_dart.py cns         # 컨센서스 있는 종목의 분기 추정치 스냅샷 → cns_quarter (하루 한 번, 약 3분)
python3 build_dart.py
```

- 종류: 단일판매·공급계약(체결·해지), 잠정실적, 투자판단 관련 주요경영사항(품목허가·임상 등), 주식소각, 자기주식 취득·신탁, CB·BW·EB 발행, 유상·무상증자, 최대주주 변경, 타법인 주식 취득, 배당, IR, 결산실적 공시 예고. 원문 XML 의 표 칸을 '항목 이름 → 다음 칸'으로 읽는다(`collectors/dart.py`). 유가증권·코스닥 서식이 조금 달라 둘 다 처리한다.
- 잠정실적 서프라이즈·쇼크: 네이버 종목 분기 재무의 추정(isConsensus=Y) 열(FnGuide)과 비교. 공시일까지 받은 마지막 스냅샷을 쓴다. 잠정실적이 들어오면 그 종목 추정치를 바로 한 번 더 받아 둔다(네이버가 발표 뒤에도 하루쯤 추정 열을 남겨 두는 것을 이용).
  영업이익 ±10% 이상이면 서프·쇼크, 추정 흑자인데 적자면 쇼크. 별도 실적인데 매출이 추정치와 50% 넘게 다르면 연결 추정치로 보고 비교하지 않는다(지주사 등).
  2026-11-04 공시를 사용자가 붙여 준 정리와 대조해 카카오뱅크·대웅제약·롯데하이마트·산일전기·고려아연 비율이 일치하는 것을 확인했다.
- '글로 복사' 버튼은 보이는 공시를 `[11월 4일(수) 주요 공시]` 양식 글로 클립보드에 넣는다(다음 거래일 실적발표 예정 종목 포함).
- 실적발표 예정: 결산실적 공시 예고와 '실적' 내용이 있는 IR 공시로 확인된 회사만. 이미 잠정실적을 낸 회사의 다음 날 컨퍼런스콜은 뺀다. 예고 없이 발표하는 대형주(HMM·카카오 등)는 빠진다.
- 장전·장후 표시는 장중 수집(live.py, 평일 07:00~19:30 10분마다)이 처음 본 시각 기준이다.
- 홈 '오늘의 공시' 카드: 서프·쇼크 실적(4개까지), 최대주주 변경, 매출액 대비 10%·500억 이상 수주, 100억 이상 자사주·자금조달, 주요경영사항. 정정 공시는 뺀다.
- DART 키는 `DART_API_KEY`(.env 또는 ~/stock-dashboard/.env).

## 테이블

- `consensus_annual`: (as_of, code, fy, fy_month)별 실적/추정
- `consensus_trend`: (as_of, code, fy, fy_month, metric)별 now / w1 / m1 / m3 / y1
- `stock_meta`: 시장, WICS (7일마다 갱신)
- `collect_log`: 종목별 수집 상태 (ok / no_data / error)
- `research`: 네이버 리서치 리포트 (id, 종목, 증권사, 날짜, 제목, 의견, 목표가, 소제목, 본문 요약)
- `flow_daily`: (date, code)별 외국인·기관·개인 순매수 수량, 종가, 외국인 지분율
- `high52_daily`: (date, code) 그날 52주 신고가 종목
- `index_daily`: (date, code) 코스피·코스닥 종가·등락률, 투자자별·프로그램 순매수(억원), 상승/하락/보합 종목 수
- `index_ohlc`: (date, code) 지수 일봉 / `index_minute`: (date, code, t) 당일 1분봉 / `index_snap`: (date, code, t) 장중 실행 때 누적 순매수
- `ohlc_daily`: (date, code) 종목 일봉 (시가·고가·저가·종가·거래량)
- `quote_live`: 전 종목 장중 시세 (받을 때마다 통째로 바꿈)
- `dart_filing`: (rcept_no) DART 공시, 종류(kind)와 원문에서 읽은 항목(data JSON)
- `cns_quarter`: (as_of, code, period) 네이버 분기 추정치 스냅샷
