"""
장중 갱신: 지수(분봉·투자자별 순매수) + 전 종목 시세 + DART 새 공시 → home.json·공시 JSON → GitHub Pages

launchd(com.kimbob.beomdashboard.live)가 1분마다 부른다 (2026-11-19 사용자 요청으로 10분 → 1분).
- 09:00~15:50 (평일, 매분): 지수·전 종목 시세 → 신고가 탭(장중 잠정)·홈 → 배포
- 07:00~19:30 (평일, 매분): DART 새 공시·KIND 공시 시각·새 증권사 리포트. 새로 들어온 행이 있을 때만 공시·리포트를 다시 빌드한다
- 평일 장 마감 뒤: 장중에 맥이 자서 그날 시세가 하나도 없으면 한 번 받는다 → 그날 신고가(잠정)·홈 (저녁 수급이 오면 정규장 종가로 바뀜)
- 느린 수집(live.py --slow, 매분 부르되 따로 돌고 아래 간격마다): 1분 갱신을 막지 않게 별도 프로세스·잠금으로 돈다.
    5분  텔레그램 실적 글 → 실적 속보·오늘 발표 종목 분봉 → 실적 발표 덱, @DOC_POOL 리포트 → 리포트 탭
    15분 텔레그램 탐방 노트 → 탐방 탭, 컨콜 → 소비재 탭, 섹터 뉴스(네이버 검색 API) → 소비재 탭 뉴스
    30분 네이버 투자전략 리포트 → 전략 트래커 (평일 07:00~20:00)
  텔레그램 수집기들은 같은 로그인 세션 파일(db/tg_user.session)을 직접 열어서 둘이 동시에 돌면 안 된다 → 차례로 돌고,
  daily.py 가 돌고 있으면(같은 수집을 한다) 그동안 쉰다. 탐방·컨콜은 전체 방 검색이라 텔레그램이 속도 제한을 걸 수 있어 15분.
  바뀐 게 있을 때만(DB 행 수·파일 내용) 그 탭을 다시 빌드하고 배포한다.
- 09:00~ (평일): 맥이 자는 동안 GitHub Actions 가 받아 둔 지수 수급 스냅샷(snap 브랜치)으로 빈 시각을 채운다
- 맥이 자는 동안에는 GitHub Actions(.github/workflows/cloud-live.yml → cloud_live.py)가 사이트 홈·quotes.json 을
  장중 시세로 1분마다 대신 갱신한다. 맥이 깨어나 배포하면 맥 것이 우선 (gh-pages 를 새로 만들어 덮는다)
- 06:00~23:59 (매일, 매분): 종목별 수급이 새 거래일로 올라왔는지 확인(네이버 1번 호출)하고, 올라왔으면 전 종목 수급을 받아 다시 빌드한다.
  네이버가 KRX 종목별 투자자 매매동향을 올리는 시각이 날마다 달라서(20:20 무렵 ~ 다음 날) 정해진 실행 시각만으로는 놓친다.
daily.py 와는 따로 돈다(잠금 파일이 다르다 — 아침 정기 실행이 길어져도 장중 갱신이 멈추지 않게). 두 쪽의 배포는 publish.py 가 차례로 한다.
배포는 GitHub Actions 워크플로(.github/workflows/pages.yml)가 한다 — 브랜치 빌드의 시간당 10회 한도가 없어 1분마다 올릴 수 있다.
한 번 도는 데 1분이 넘으면(새 공시가 몰리거나 정기 실행과 겹칠 때) 다음 차례는 잠금에 걸려 조용히 건너뛴다.

  python3 live.py           # 장 시간 밖이면 아무것도 안 함
  python3 live.py --force   # 시간 상관없이 한 번 (느린 수집도 모두)
  python3 live.py --slow    # 느린 수집만 (간격이 된 것만)
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
AFTER_STAMP = LOG_DIR / 'live_after_close.stamp'   # 장 마감 뒤 시세를 한 번 받은 날
# 클라우드(cloud-data 워크플로)에 '맥 깨어 있음' 신호(5분)와 DB 사본(6시간)을 보낸다 — cloud_sync.py
BEAT_EVERY, SNAP_EVERY = 300, 6 * 3600
# 느린 수집: (이름, 간격 초, 시작, 끝, 평일만) — 마지막으로 돈 시각은 logs/live_slow_<이름>.stamp 의 수정 시각
SLOW = (('tg', 300, dtime(6, 0), dtime(23, 59), False),
        ('tgsearch', 900, dtime(6, 0), dtime(23, 59), False),
        ('news', 900, dtime(6, 0), dtime(23, 0), False),
        ('strategy', 1800, dtime(7, 0), dtime(20, 0), True))
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


def db_fp(path: Path, tables) -> tuple | None:
    """내용 표마다 (행 수, 마지막 rowid) — 새 글이 들어왔는지 보는 지문 (못 읽으면 None = 바뀐 것으로).
    수집기가 매번 고쳐 쓰는 meta(마지막 확인 시각)·다시 계산하는 표(전략 pick)는 넣지 않는다 — 넣으면 새 글이 없어도 매번 다시 빌드한다"""
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30)
        try:
            return tuple(con.execute(f'SELECT COUNT(*), MAX(rowid) FROM "{t}"').fetchone() for t in tables)
        finally:
            con.close()
    except sqlite3.Error:
        return None


def file_fp(path: Path) -> str | None:
    import hashlib
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def slow_due(name: str, every: int, start, end, weekday_only: bool, now: datetime) -> bool:
    if weekday_only and now.weekday() >= 5 or not start <= now.time() <= end:
        return False
    try:
        return time.time() - (LOG_DIR / f'live_slow_{name}.stamp').stat().st_mtime >= every - 30
    except OSError:
        return True


def stamp_age(name: str) -> float:
    try:
        return time.time() - (LOG_DIR / name).stat().st_mtime
    except OSError:
        return float('inf')


def spawn(*args):
    """따로 떠서 돈다 (1분 갱신을 기다리게 하지 않음)"""
    subprocess.Popen([sys.executable, *args], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def dart_gap() -> int:
    """마지막으로 받은 공시일부터 오늘까지 (맥이 며칠 잤어도 빈 날을 이어 받게, 최대 7일)"""
    try:
        con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
        try:
            last = con.execute('SELECT MAX(date) FROM dart_filing').fetchone()[0]
        finally:
            con.close()
        return max(1, min(7, (datetime.now().date() - datetime.fromisoformat(last).date()).days))
    except (sqlite3.Error, TypeError, ValueError):
        return 1


def quote_date() -> str:
    try:
        con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
        try:
            return con.execute('SELECT MAX(date) FROM quote_live').fetchone()[0] or ''
        finally:
            con.close()
    except sqlite3.Error:
        return ''


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
    if any(slow_due(*x, t) for x in SLOW) or force:   # 느린 수집은 따로 (1분 갱신을 막지 않게). 이미 돌고 있으면 그쪽이 바로 끝난다
        spawn('live.py', '--slow', *(['--force'] if force else []))
    if stamp_age('cloud_beat.stamp') >= BEAT_EVERY - 30:      # 클라우드에 '맥 깨어 있음' (실패해도 다음 분에 다시)
        (LOG_DIR / 'cloud_beat.stamp').touch()
        spawn('cloud_sync.py', 'beat')
    if stamp_age('cloud_snapshot.stamp') >= SNAP_EVERY and stamp_age('cloud_snapshot.try') >= 1800:   # DB 사본 (실패하면 30분 뒤 다시)
        (LOG_DIR / 'cloud_snapshot.try').touch()
        spawn('cloud_sync.py', 'snapshot')
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
        if not market and t.weekday() < 5 and t.time() > END:
            # 장중에 맥이 자서 오늘 시세가 하나도 없으면 한 번 받는다 → 오늘 신고가(잠정)·홈. 휴장일에 매분 다시 받지 않게 하루 한 번
            today = t.strftime('%Y-%m-%d')
            try:
                tried = AFTER_STAMP.read_text().strip() == today
            except OSError:
                tried = False
            if not tried and quote_date() < today:
                AFTER_STAMP.write_text(today)
                if got(run(['collect_naver.py', 'quotes'], log)) and quote_date() == today:
                    ok = high_only = True
        if force or (t.weekday() < 5 and t.time() >= START):
            # 맥이 자는 동안 GitHub Actions 가 받아 둔 지수 수급 스냅샷으로 빈 시각을 채운다 (index_snap.py).
            # 장 마감 뒤에 깨어나도 그날 치를 채우도록 저녁까지 확인한다. 채운 것이 있을 때만(0) 홈을 다시 만든다.
            ok |= run(['index_snap.py', 'merge'], log) == 0
        if filings:
            dart0, rep0 = fingerprint(DB, DART_FP), fingerprint(DB, RESEARCH_FP)
            run(['collect_dart.py', '--days', str(dart_gap())], log)
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


def slow_main() -> int:
    """느린 수집 (텔레그램·뉴스·전략). 바뀐 탭만 다시 빌드하고 배포한다"""
    force = '--force' in sys.argv
    t = datetime.now()
    LOG_DIR.mkdir(exist_ok=True)
    lock = open(LOG_DIR / 'live_slow.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    due = {x[0] for x in SLOW if force or slow_due(*x, t)}
    if not due:
        return 0
    with open(LOG_DIR / f'live_slow_{t:%Y%m%d}.log', 'a', encoding='utf-8') as log:
        if daily_running():   # 정기 실행이 같은 수집(텔레그램·뉴스·전략)을 하고 있다 — 세션 파일·DB 가 겹치지 않게 끝난 뒤에
            log.write(f'--- {t:%H:%M:%S} 정기 실행(daily.py)이 도는 중 — 느린 수집은 다음 차례에\n')
            return 0
        for name in due:
            (LOG_DIR / f'live_slow_{name}.stamp').touch()
        new = False
        if 'tg' in due:
            earn0 = fingerprint(EARN_DB, EARN_FP)
            if run(['collect_earn.py', 'posts'], log) == 0:
                run(['earn_alert.py', '--notify'], log)   # 관심 종목(소비재·의료기기) 실적 공시 속보 → 텔레그램
                run(['collect_earn.py', 'minutes', '--today'], log)
            if changed(earn0, fingerprint(EARN_DB, EARN_FP)):
                new |= run(['build_earn.py'], log) == 0
            pool = lambda: db_fp(ROOT / 'db' / 'docpool.db', ('post',))
            pool0 = pool()
            run(['collect_docpool.py'], log)
            if changed(pool0, pool()):
                new |= run(['build_docpool.py'], log) == 0
        if 'tgsearch' in due:
            vis, cc = (lambda: db_fp(ROOT / 'db' / 'visits.db', ('msg',))), (lambda: db_fp(ROOT / 'db' / 'concall.db', ('msg',)))
            v0, c0 = vis(), cc()
            run(['collect_visits.py'], log)
            if changed(v0, vis()):
                new |= run(['build_visits.py'], log) == 0
            run(['collect_visits.py', '--topic', 'concall'], log)
            if changed(c0, cc()):
                new |= run(['build_consumer.py'], log) == 0
        if 'news' in due:
            n0 = file_fp(PUBLIC / 'data' / 'news.json')
            run(['collect_news.py'], log)
            new |= changed(n0, file_fp(PUBLIC / 'data' / 'news.json'))
        if 'strategy' in due:
            stg = lambda: db_fp(ROOT / 'db' / 'strategy.db', ('doc', 'tgpost'))
            s0 = stg()
            run(['collect_strategy.py'], log)
            if changed(s0, stg()):
                new |= run(['build_strategy.py'], log) == 0
        if not new:
            log.write(f'{datetime.now():%H:%M:%S} 새로 받은 것 없음 ({", ".join(sorted(due)) or "-"})\n')
            return 0
        rc = run(['publish.py'], log)
        log.write(f'=== {datetime.now():%H:%M:%S} 끝 ({(datetime.now() - t).total_seconds():.0f}초)\n')
        return rc


if __name__ == '__main__':
    sys.exit(slow_main() if '--slow' in sys.argv else main())
