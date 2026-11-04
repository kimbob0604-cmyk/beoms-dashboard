"""
장중 홈 갱신: 지수(분봉·투자자별 순매수) + 전 종목 시세 → home.json → GitHub Pages

launchd(com.kimbob.beomdashboard.live)가 10분마다 부르고, 평일 09:00~15:50 밖이면 바로 끝난다.
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


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and START <= now.time() <= END


def run(args, log) -> int:
    log.write(f'--- {datetime.now():%H:%M:%S} {" ".join(args)}\n')
    log.flush()
    return subprocess.run([sys.executable, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode


def main() -> int:
    if '--force' not in sys.argv and not in_session(datetime.now()):
        return 0
    LOG_DIR.mkdir(exist_ok=True)
    lock = open(LOG_DIR / 'daily.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0   # 정기 실행 중
    with open(LOG_DIR / f'live_{datetime.now():%Y%m%d}.log', 'a', encoding='utf-8') as log:
        a = run(['collect_naver.py', 'index'], log)
        b = run(['collect_naver.py', 'quotes'], log)
        if a not in (0, 1) and b not in (0, 1):
            log.write('네이버 응답 없음, 배포 건너뜀\n')
            return 1
        if run(['build_home.py'], log) != 0 or run(['publish.py'], log) != 0:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
