# Beom's Dashboard

이익 성장 · 컨센 리비전 · 신고가 · 수급 대시보드.
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

- 정적 페이지다: `public/index.html`, `public/css/app.css`, `public/js/util.js`(포맷·테마 공통), `public/js/growth.js`(이 탭).
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

`daily.py`가 네 단계를 차례로 돌린다: 가격 → 컨센서스 → 빌드 → GitHub Pages 배포. launchd가 월~토 07:10과 12:10에 부른다.

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

## 테이블

- `consensus_annual`: (as_of, code, fy, fy_month)별 실적/추정
- `consensus_trend`: (as_of, code, fy, fy_month, metric)별 now / w1 / m1 / m3 / y1
- `stock_meta`: 시장, WICS (7일마다 갱신)
- `collect_log`: 종목별 수집 상태 (ok / no_data / error)
