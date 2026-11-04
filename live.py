"""
장중 갱신: 지수(분봉·투자자별 순매수) + 전 종목 시세 + DART 새 공시 → home.json·공시 JSON → GitHub Pages

launchd(com.kimbob.beomdashboard.live)가 10분마다 부른다. 평일에만 돈다.
- 07:00~19:30: DART 새 공시 (장전 공시 07:30~08:50, 장후 공시 15:30~19:00 무렵이 많다)
- 09:00~15:50: 지수·전 종목 시세
daily.py 가 돌고 있으면(같은 잠금 파일) 건너뛴다. GitHub Pages 빌드 한도(시간당 10회 안팎) 때문에 10분 간격이다.

  python3 live.py           # 장 시간 밖이면 아무것도 안 함
  python3 live.py --force   # 시간 상관없이 한 번
"""

import fcntl
import subprocess
import sys
from datetime import datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'
START, END = dtime(9, 0), dtime(15, 50)
DART_START, DART_END = dtime(7, 0), dtime(19, 30)


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and START <= now.time() <= END


def in_dart_hours(now: datetime) -> bool:
    return now.weekday() < 5 and DART_START <= now.time() <= DART_END


def run(args, log) -> int:
    log.write(f'--- {datetime.now():%H:%M:%S} {" ".join(args)}\n')
    log.flush()
    return subprocess.run([sys.executable, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode


def main() -> int:
    force = '--force' in sys.argv
    t = datetime.now()
    market, filings = force or in_session(t), force or in_dart_hours(t)
    if not (market or filings):
        return 0
    LOG_DIR.mkdir(exist_ok=True)
    lock = open(LOG_DIR / 'daily.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0   # 정기 실행 중
    with open(LOG_DIR / f'live_{datetime.now():%Y%m%d}.log', 'a', encoding='utf-8') as log:
        ok = False
        if market:
            a = run(['collect_naver.py', 'index'], log)
            b = run(['collect_naver.py', 'quotes'], log)
            ok |= a in (0, 1) or b in (0, 1)
        if filings:
            c = run(['collect_dart.py'], log)
            ok |= c in (0, 1)
            if run(['build_dart.py'], log) != 0:
                return 1
        if not ok:
            log.write('응답 없음, 배포 건너뜀\n')
            return 1
        if run(['build_home.py'], log) != 0 or run(['publish.py'], log) != 0:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
