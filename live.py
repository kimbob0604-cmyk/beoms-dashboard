"""
장중 갱신: 지수(분봉·투자자별 순매수) + 전 종목 시세 + DART 새 공시 → home.json·공시 JSON → GitHub Pages

launchd(com.kimbob.beomdashboard.live)가 1분마다 부른다 (2026-11-19 사용자 요청으로 10분 → 1분).
- 09:00~15:50 (평일, 매분): 지수·전 종목 시세 → 신고가 탭(장중 잠정)·홈 → 배포
- 07:00~19:30 (평일, 매분): DART 새 공시·KIND 공시 시각·새 증권사 리포트. 새로 들어온 행이 있을 때만 공시·리포트를 다시 빌드한다
- 07:00~19:30 (평일, 10분마다): 텔레그램 실적 글 → 실적 속보·오늘 발표 종목 분봉 → 실적 발표 덱 (바뀐 게 있을 때만 빌드, 40초)
  텔레그램 로그인 세션을 탐방 노트·Study 수집도 같이 쓴다. 매분 붙으면 세션이 겹쳐 끊길 위험이 커서 10분 간격을 지킨다.
- 09:00~ (평일): 맥이 자는 동안 GitHub Actions 가 받아 둔 지수 수급 스냅샷(snap 브랜치)으로 빈 시각을 채운다
- 맥이 자는 동안에는 GitHub Actions(.github/workflows/cloud-live.yml → cloud_live.py)가 사이트 홈·quotes.json 을
  장중 시세로 1분마다 대신 갱신한다. 맥이 깨어나 배포하면 맥 것이 우선 (gh-pages 를 새로 만들어 덮는다)
- 06:00~23:59 (매일, 매분): 종목별 수급이 새 거래일로 올라왔는지 확인(네이버 1번 호출)하고, 올라왔으면 전 종목 수급을 받아 다시 빌드한다.
  네이버가 KRX 종목별 투자자 매매동향을 올리는 시각이 날마다 달라서(20:20 무렵 ~ 다음 날) 정해진 실행 시각만으로는 놓친다.
daily.py 와는 따로 돈다(잠금 파일이 다르다 — 아침 정기 실행이 길어져도 장중 갱신이 멈추지 않게). 두 쪽의 배포는 publish.py 가 차례로 한다.
배포는 GitHub Actions 워크플로(.github/workflows/pages.yml)가 한다 — 브랜치 빌드의 시간당 10회 한도가 없어 1분마다 올릴 수 있다.
한 번 도는 데 1분이 넘으면(새 공시가 몰리거나 정기 실행과 겹칠 때) 다음 차례는 잠금에 걸려 조용히 건너뛴다.

  python3 live.py           # 장 시간 밖이면 아무것도 안 함
  python3 live.py --force   # 시간 상관없이 한 번 (텔레그램 포함)
"""

import fcntl
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'
DB = ROOT / 'db' / 'dashboard.db'
EARN_DB = ROOT / 'db' / 'earn.db'
START, END = dtime(9, 0), dtime(15, 50)
DART_START, DART_END = dtime(7, 0), dtime(19, 30)
FLOW_START = dtime(6, 0)
TG_EVERY = 600                          # 텔레그램 실적 글 확인 간격(초)
TG_STAMP = LOG_DIR / 'live_tg.stamp'    # 마지막으로 확인한 시각 (파일 수정 시각)
PUBLIC = ROOT / 'public'
STUDY_FILES = ('study.html', 'css/app.css', 'css/study.css', 'js/util.js', 'js/study_chart.js', 'js/study.js')
STUDY_STAMP = LOG_DIR / 'study_publish.stamp'   # Study 사이트에 마지막으로 올린 빌드의 지문

# 새로 들어온 행이 있는지 보는 지문 (행 수·마지막 rowid — INSERT OR REPLACE 도 rowid 가 커진다, 시각 채움은 COUNT(tm))
DART_FP = ('SELECT COUNT(*), MAX(rowid) FROM dart_filing', 'SELECT COUNT(*), MAX(rowid), COUNT(tm) FROM dart_event',
           'SELECT COUNT(*), MAX(rowid) FROM kind_disc')
RESEARCH_FP = ('SELECT COUNT(*), MAX(rowid) FROM research',)
EARN_FP = ('SELECT COUNT(*), MAX(rowid) FROM earn_post', 'SELECT COUNT(*), TOTAL(LENGTH(bars)), TOTAL(done) FROM minute_day')


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


def fingerprint(path: Path, queries) -> tuple | None:
    """표의 행 수 등. 못 읽으면 None — 그때는 바뀐 것으로 본다"""
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30)
        try:
            return tuple(tuple(con.execute(q).fetchone()) for q in queries)
        finally:
            con.close()
    except sqlite3.Error:
        return None


def changed(before, after) -> bool:
    return before is None or after is None or before != after


def tg_due(force: bool) -> bool:
    try:
        return force or time.time() - TG_STAMP.stat().st_mtime >= TG_EVERY - 30
    except OSError:
        return True


def study_sig() -> str:
    """Study 빌드(public/data/study + 화면 파일)의 지문: 파일 수·크기 합·마지막 수정 시각 (2천여 파일, 수십 ms)"""
    n = size = last = 0
    paths = [PUBLIC / rel for rel in STUDY_FILES] + [p for p in (PUBLIC / 'data' / 'study').rglob('*') if p.is_file()]
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        n, size, last = n + 1, size + st.st_size, max(last, st.st_mtime_ns)
    return f'{n}:{size}:{last}'


def publish_study_if_changed(log):
    """Study 빌드가 바뀌었으면 Study 사이트(beoms-study)로 올린다. 대시보드에 새 데이터가 없어도 1분 안에 올라가게
    (전에는 publish.py 가 대시보드를 배포할 때만 같이 올려, 저녁에 Study 만 다시 빌드하면 다음 대시보드 배포까지 기다렸다)"""
    sig = study_sig()
    try:
        if STUDY_STAMP.read_text() == sig:
            return
    except OSError:
        pass
    if run(['publish_study.py'], log) == 0:
        STUDY_STAMP.write_text(sig)


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
        ok = full_naver = high_only = False
        if flow:   # 새 거래일 종목별 수급이 올라왔을 때만 받는다 (없으면 종료 코드 10)
            new_flow = got(run(['collect_naver.py', 'flow', '--if-new'], log))
            # 기관 세부(KIS): 네이버 수급이 올라온 거래일을 아직 안 받았을 때만 호출한다 (받았으면 API 호출 없이 10)
            new_det = got(run(['collect_kis_flow.py'], log))
            ok |= new_flow or new_det
            full_naver |= new_flow or new_det
        if market:
            ok |= got(run(['collect_naver.py', 'index'], log))
            new_quotes = got(run(['collect_naver.py', 'quotes'], log))
            ok |= new_quotes
            high_only |= new_quotes       # 신고가 탭은 이 시세로 다시 계산한다 (build_naver --high — 장중에는 잠정 판정)
        if force or (t.weekday() < 5 and t.time() >= START):
            # 맥이 자는 동안 GitHub Actions 가 받아 둔 지수 수급 스냅샷으로 빈 시각을 채운다 (index_snap.py).
            # 장 마감 뒤에 깨어나도 그날 치를 채우도록 저녁까지 확인한다. 채운 것이 있을 때만(0) 홈을 다시 만든다.
            ok |= run(['index_snap.py', 'merge'], log) == 0
        if filings:
            dart0, rep0 = fingerprint(DB, DART_FP), fingerprint(DB, RESEARCH_FP)
            run(['collect_dart.py'], log)
            run(['collect_dart.py', 'times', '--latest'], log)   # KIND 최신 100건 공시 시각
            run(['collect_naver.py', 'research', '--days', '2'], log)
            new_dart = changed(dart0, fingerprint(DB, DART_FP))
            new_rep = changed(rep0, fingerprint(DB, RESEARCH_FP))
            ok |= new_dart or new_rep
            full_naver |= new_rep
            if new_dart:
                if run(['build_dart.py'], log) != 0:
                    return 1
                run(['build_events.py'], log)   # 이벤트 스터디 기업 리스트에 새 공시 (5초)
            # 실적 발표 덱: 새 실적 글 → 오늘 발표 종목의 분봉(가진 마지막 분 뒤만) → 바뀐 게 있으면 빌드. 배포는 위 공시와 함께
            if tg_due(force):
                TG_STAMP.touch()
                earn0 = fingerprint(EARN_DB, EARN_FP)
                if run(['collect_earn.py', 'posts'], log) == 0:
                    run(['earn_alert.py', '--notify'], log)   # 관심 종목(소비재·의료기기) 실적 공시 속보 → 텔레그램
                    run(['collect_earn.py', 'minutes', '--today'], log)
                if changed(earn0, fingerprint(EARN_DB, EARN_FP)):
                    run(['build_earn.py'], log)
                    ok = True
        if full_naver:
            if run(['build_naver.py'], log) != 0:
                return 1
            run(['build_digest.py'], log)   # 새 리포트·수급이 들어오면 리포트 탭도 (3초)
        elif high_only and run(['build_naver.py', '--high'], log) != 0:
            return 1
        rc = 0
        if not ok:
            log.write(f'{datetime.now():%H:%M:%S} 새로 받은 것 없음, 배포 건너뜀\n')
        else:
            if market:
                run(['build_bio.py', '--live'], log)   # 바이오 탭 국장 종목도 장중 가격으로 (네트워크 없음)
            if run(['build_home.py'], log) != 0 or run(['publish.py'], log) != 0:
                rc = 1
        publish_study_if_changed(log)   # publish.py 가 방금 올렸으면 '바뀐 파일 없음'으로 끝난다 (3초)
        if ok:
            log.write(f'=== {datetime.now():%H:%M:%S} 끝 ({(datetime.now() - t).total_seconds():.0f}초)\n')
    return rc


if __name__ == '__main__':
    sys.exit(main())
