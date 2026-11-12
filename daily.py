"""
매일 실행: 가격 → 컨센서스 → 네이버(리포트·신고가·수급·지수) → DART 공시·분기 추정치 → JSON 빌드(이익 성장·네이버·공시·이벤트 스터디·퀀트 팩터·조건 백테스트(아침)·전략 트래커·탐방 노트·소비재·바이오·홈·종목 차트) → GitHub Pages 배포(publish.py)
장중 10분 간격 홈 갱신은 live.py 가 따로 한다.

launchd(com.kimbob.beomdashboard.daily)가 월~토 07:10, 12:10, 평일 20:40에 부른다.
20:40 실행은 그날 네이버 수급·신고가·임시 종가를 받아 저녁에 화면을 갱신하기 위해서다.
네이버 수급은 넥스트레이드 시간외(~20:00)가 끝난 뒤 20:20 무렵 올라온다.
컨센서스는 월요일만 전체(약 1시간), 화~토는 추정치 있던 종목 + 신규만(약 15분) 받는다.
같은 날 다시 돌려도 안전하다. 컨센서스는 오늘 이미 받은 종목을 건너뛰고, 가격·빌드는 덮어쓴다.
KRX 일별 데이터는 보통 다음 날 아침에 열리므로 12:10 실행이 07:10에 못 받은 가격을 채운다.

- 컨센서스가 2(커버리지 급감·형식 변경 의심)면 빌드하지 않는다. 3(서버 응답 없음, 연속 실패로 중단)이면
  빌드는 하되, build_growth 가 추정치 종목 수가 모자란 스냅샷을 건너뛰어 덜 받은 값으로 화면을 덮어쓰지 않는다.
- 경고·실패는 macOS 알림으로 띄우고, 전체 출력은 logs/daily_YYYYMMDD.log 에 남긴다.

  python3 daily.py
"""

import fcntl
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'


def notify(title: str, msg: str):
    script = f'display notification {_as_str(msg)} with title {_as_str(title)}'
    subprocess.run(['osascript', '-e', script], check=False, capture_output=True)


def _as_str(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def run(step: str, args: list, log) -> int:
    log.write(f'\n=== {datetime.now():%H:%M:%S} {step}: {" ".join(args)}\n')
    log.flush()
    code = subprocess.run([sys.executable, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
    log.write(f'=== {datetime.now():%H:%M:%S} {step} 종료 코드 {code}\n')
    log.flush()
    return code


def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    lock = open(LOG_DIR / 'daily.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('이미 실행 중이라 건너뜀')
        return 0

    problems = []
    with open(LOG_DIR / f'daily_{datetime.now():%Y%m%d}.log', 'a', encoding='utf-8') as log:
        # 가격 먼저: 종목 목록(universe)이 최근 가격일 기준이라 신규 상장이 같은 날 컨센서스 수집에 들어간다
        if run('가격', ['collect_prices.py'], log) != 0:
            problems.append('KRX 가격 없음')

        # 월요일은 전체(새로 커버리지가 생긴 종목 포함), 나머지 날은 추정치 있던 종목 + 신규만 → 요청 수 약 1/4
        full = datetime.now().weekday() == 0
        cns = run('컨센서스', ['collect_consensus.py'] + ([] if full else ['--covered-only']), log)
        if cns == 1:
            problems.append('컨센서스 수집 오류가 많음')
        elif cns == 3:
            problems.append('컨센서스 서버 응답 없음 — 중단, 다음 실행에서 이어 받음')
        elif cns != 0:
            problems.append(f'컨센서스 점검 실패(코드 {cns}) — 빌드 건너뜀')

        # 3(중간에 끊김)이어도 빌드는 한다. build_growth 가 덜 받은 스냅샷을 건너뛰고 직전 완전한 스냅샷을 쓴다.
        # 이걸 막으면 컨센서스 서버가 며칠 막힐 때 가격·리비전 화면까지 멈춘다.
        built = False
        if cns in (0, 1, 3):
            if run('빌드', ['build_growth.py'], log) != 0:
                problems.append('이익 성장 JSON 빌드 실패')
            else:
                built = True

        # 네이버는 컨센서스와 다른 서버라 컨센서스가 막혀도 받는다
        nv = run('네이버', ['collect_naver.py', 'all'], log)
        if nv == 3:
            problems.append('네이버 서버 응답 없음 — 다음 실행에서 이어 받음')
        elif nv != 0:
            problems.append('네이버 수집 오류가 많음')
        # 기관 세부(금융투자·연기금·투신·사모…): 한국투자증권 API. 네이버 수급의 마지막 거래일 기준, 이미 받았으면 10으로 바로 끝
        if run('기관 세부', ['collect_kis_flow.py'], log) not in (0, 4, 10):
            problems.append('KIS 기관 세부 수급 일부 실패 — 다음 실행에서 이어 받음')
        if run('네이버 빌드', ['build_naver.py'], log) != 0:
            problems.append('리포트·수급·신고가 JSON 빌드 실패')
        else:
            built = True
        if run('리포트 정리', ['build_digest.py'], log) != 0:
            problems.append('리포트 탭 JSON 빌드 실패')
        # 공시: 어제·오늘 (어제 늦게 올라온 장후 공시 포함). 분기 추정치는 하루 한 번 받으면 다음 실행은 건너뛴다
        if run('DART 공시', ['collect_dart.py', '--days', '1'], log) not in (0, 1):
            problems.append('DART 응답 없음 — 다음 실행에서 이어 받음')
        run('분기 추정치', ['collect_dart.py', 'cns'], log)
        run('공시 시각', ['collect_dart.py', 'times'], log)   # KIND 오늘 공시 시각 → 이벤트 스터디 반응일
        if run('공시 빌드', ['build_dart.py'], log) != 0:
            problems.append('공시 JSON 빌드 실패')
        if run('이벤트 빌드', ['build_events.py'], log) != 0:
            problems.append('이벤트 스터디 JSON 빌드 실패')
        if run('팩터 빌드', ['build_factors.py'], log) != 0:
            problems.append('퀀트 팩터 JSON 빌드 실패')
        # 조건 백테스트(20년): 과거 DB(history.db)에 어제까지의 확정 가격을 복사. 다시 계산은 아침 실행에서만 (약 8분)
        run('백테스트 과거 가격', ['collect_history.py', 'sync'], log)
        if datetime.now().hour < 12:
            run('백테스트 수급', ['collect_history.py', 'flow', '--recent', '10'], log)
            if datetime.now().weekday() == 5:      # 분기 실적은 토요일에만 다시 받는다
                run('백테스트 실적', ['collect_history.py', 'fin'], log)
            if run('백테스트 빌드', ['build_backtest.py'], log) != 0:
                problems.append('조건 백테스트 JSON 빌드 실패')
        # 전략 트래커: 증권사 전략 리포트·퀀트 채널의 새 글 → 종목 추출 → 따라 샀을 때 성과. 과거 가격 DB 를 쓰므로 위 sync 뒤에
        if run('전략 수집', ['collect_strategy.py'], log) != 0:
            problems.append('전략 리포트·채널 수집 일부 실패 — 다음 실행에서 이어 받음')
        if run('전략 빌드', ['build_strategy.py'], log) != 0:
            problems.append('전략 트래커 JSON 빌드 실패')
        # 탐방 노트: 내 텔레그램 방의 '탐방' 글. 본인 계정 로그인이 필요하고, 설정 전이면 4로 조용히 건너뛴다.
        # 글 원문이 들어가므로 공개 배포에서는 빠진다 (publish_hold.txt)
        if run('탐방 수집', ['collect_visits.py'], log) not in (0, 4):
            problems.append('텔레그램 탐방 글 수집 실패 — 다음 실행에서 이어 받음')
        if run('탐방 빌드', ['build_visits.py'], log) != 0:
            problems.append('탐방 노트 JSON 빌드 실패')
        run('탐방 차트', ['collect_visits_chart.py'], log)   # 탐방 종목의 네이버 일봉 (하루 한 번, 실패해도 직전 파일이 남는다)
        # 소비재 탭: 관세청 수출 통계(올해 창은 14~21일에 하루 한 번, 그 밖엔 7일에 한 번만 다시 받는다 — 아니면 바로 끝난다),
        # 텔레그램 컨콜 노트, 그리고 빌드. 키·로그인이 없으면 4로 건너뛴다
        if run('수출 통계', ['collect_trade.py'], log) not in (0, 4):
            problems.append('관세청 수출 통계 일부 실패 — 다음 실행에서 이어 받음')
        if run('컨콜 수집', ['collect_visits.py', '--topic', 'concall'], log) not in (0, 4):
            problems.append('텔레그램 컨콜 글 수집 실패 — 다음 실행에서 이어 받음')
        if run('소비재 빌드', ['build_consumer.py'], log) != 0:
            problems.append('소비재 JSON 빌드 실패')
        # 바이오 탭: 미국 종목(yfinance·ClinicalTrials.gov)이라 위 한국 데이터와 독립. 실패해도 직전 값이 남는다
        if run('바이오 빌드', ['build_bio.py'], log) != 0:
            problems.append('바이오 JSON 빌드 실패')
        # 홈은 위 두 빌드의 결과 JSON 을 모으므로 마지막에
        if run('홈 빌드', ['build_home.py'], log) != 0:
            problems.append('홈 JSON 빌드 실패')
        if run('차트 빌드', ['build_charts.py'], log) != 0:
            problems.append('종목 차트 JSON 빌드 실패')

        if built and run('배포', ['publish.py'], log) != 0:
            problems.append('GitHub Pages 배포 실패')

        log.write(f'=== {datetime.now():%H:%M:%S} 끝: {"; ".join(problems) or "정상"}\n')
        # 60일 지난 로그 정리
        for f in LOG_DIR.glob('*_20*.log'):
            if (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).days > 60:
                f.unlink()

    if problems:
        notify("Beom's Dashboard", ' / '.join(problems) + ' (logs 확인)')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
