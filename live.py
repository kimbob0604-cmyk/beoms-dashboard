"""
장중 갱신: 지수(분봉·투자자별 순매수) + 전 종목 시세 + DART 새 공시 → home.json·공시 JSON → GitHub Pages

launchd(com.kimbob.beomdashboard.live)가 10분마다 부른다. 평일에만 돈다.
- 07:00~19:30: DART 새 공시 (장전 공시 07:30~08:50, 장후 공시 15:30~19:00 무렵이 많다), 새 증권사 리포트
- 09:00~15:50: 지수·전 종목 시세 (신고가 탭은 이 시세로 다시 계산)
- 06:00~23:59 (매일): 종목별 수급이 새 거래일로 올라왔는지 1번 확인하고, 올라왔으면 전 종목 수급을 받아 다시 빌드한다.
  네이버가 KRX 종목별 투자자 매매동향을 올리는 시각이 날마다 달라서(20:20 무렵 ~ 다음 날) 정해진 실행 시각만으로는 놓친다.
daily.py 와는 따로 돈다(잠금 파일이 다르다 — 아침 정기 실행이 길어져도 장중 갱신이 멈추지 않게). 두 쪽의 배포는 publish.py 가 차례로 한다.
GitHub Pages 빌드 한도(시간당 10회 안팎) 때문에 10분 간격이다.

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
FLOW_START = dtime(6, 0)


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and START <= now.time() <= END


def in_dart_hours(now: datetime) -> bool:
    return now.weekday() < 5 and DART_START <= now.time() <= DART_END


def daily_running() -> bool:
    """daily.py 가 잠금을 쥐고 있는가 (기록용 — 장중 갱신을 막지는 않는다)"""
    try:
        with open(LOG_DIR / 'daily.lock', 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def run(args, log) -> int:
    log.write(f'--- {datetime.now():%H:%M:%S} {" ".join(args)}\n')
    log.flush()
    return subprocess.run([sys.executable, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode


def main() -> int:
    force = '--force' in sys.argv
    t = datetime.now()
    market, filings = force or in_session(t), force or in_dart_hours(t)
    flow = force or t.time() >= FLOW_START
    if not (market or filings or flow):
        return 0
    LOG_DIR.mkdir(exist_ok=True)
    # 자기 잠금만 건다: 전에는 daily.py 와 같은 잠금 파일을 써서, 아침 정기 실행이 길어지면(백테스트 수급 35분 등)
    # 장 초반 내내 장중 갱신이 조용히 건너뛰어졌다 (2026-11-12 07:17~09:4x). 배포가 겹치는 것은 publish.py 의 잠금이 막는다.
    lock = open(LOG_DIR / 'live.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0   # 직전 장중 갱신이 아직 도는 중
    with open(LOG_DIR / f'live_{datetime.now():%Y%m%d}.log', 'a', encoding='utf-8') as log:
        if daily_running():
            log.write(f'--- {datetime.now():%H:%M:%S} 정기 실행(daily.py)이 도는 중 — 장중 갱신은 그대로 진행\n')
        got = lambda code: code in (0, 1)   # 0 정상, 1 일부 오류 — 둘 다 새로 받은 것이 있다
        ok = need_naver = False
        if flow:   # 새 거래일 종목별 수급이 올라왔을 때만 받는다 (없으면 종료 코드 10)
            new_flow = got(run(['collect_naver.py', 'flow', '--if-new'], log))
            ok |= new_flow
            need_naver |= new_flow
            # 기관 세부(KIS): 네이버 수급이 올라온 거래일을 아직 안 받았을 때만 호출한다 (받았으면 API 호출 없이 10)
            new_det = got(run(['collect_kis_flow.py'], log))
            ok |= new_det
            need_naver |= new_det
        if market:
            ok |= got(run(['collect_naver.py', 'index'], log))
            new_quotes = got(run(['collect_naver.py', 'quotes'], log))
            ok |= new_quotes
            need_naver |= new_quotes      # 신고가 탭은 이 시세로 다시 계산한다 (build_newhigh — 장중에는 잠정 판정)
        if filings:
            ok |= got(run(['collect_dart.py'], log))
            run(['collect_dart.py', 'times', '--latest'], log)   # KIND 최신 100건 공시 시각
            new_rep = got(run(['collect_naver.py', 'research', '--days', '2'], log))
            ok |= new_rep
            need_naver |= new_rep
            if run(['build_dart.py'], log) != 0:
                return 1
            run(['build_events.py'], log)   # 이벤트 스터디 기업 리스트에 새 공시 (1초)
            # 실적 발표 덱: 새 실적 글 → 오늘 발표 종목의 분봉(가진 마지막 분 뒤만) → 빌드. 배포는 위 공시와 함께
            if run(['collect_earn.py', 'posts'], log) == 0:
                run(['collect_earn.py', 'minutes', '--today'], log)
            run(['build_earn.py'], log)
        if need_naver and run(['build_naver.py'], log) != 0:
            return 1
        if need_naver:
            run(['build_digest.py'], log)   # 새 리포트가 들어오면 리포트 탭도 (3초)
        if not ok:
            log.write('새로 받은 것 없음, 배포 건너뜀\n')
            return 0
        run(['build_factors.py'], log)   # 수급·공시·가격이 바뀌면 퀀트 팩터도 (0.5초)
        if market:
            run(['build_bio.py', '--live'], log)   # 바이오 탭 국장 종목도 장중 가격으로 (네트워크 없음)
        if run(['build_home.py'], log) != 0 or run(['publish.py'], log) != 0:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
