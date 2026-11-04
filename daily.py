"""
매일 실행: 가격 → 컨센서스 → 네이버(리포트·신고가·수급·지수) → JSON 빌드(이익 성장·네이버·홈) → GitHub Pages 배포(publish.py)

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
        if run('네이버 빌드', ['build_naver.py'], log) != 0:
            problems.append('리포트·수급·신고가 JSON 빌드 실패')
        else:
            built = True
        # 홈은 위 두 빌드의 결과 JSON 을 모으므로 마지막에
        if run('홈 빌드', ['build_home.py'], log) != 0:
            problems.append('홈 JSON 빌드 실패')

        if built and run('배포', ['publish.py'], log) != 0:
            problems.append('GitHub Pages 배포 실패')

        log.write(f'=== {datetime.now():%H:%M:%S} 끝: {"; ".join(problems) or "정상"}\n')

    if problems:
        notify("Beom's Dashboard", ' / '.join(problems) + ' (logs 확인)')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
