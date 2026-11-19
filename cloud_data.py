#!/usr/bin/env python3
"""
맥이 자는 동안 GitHub Actions(.github/workflows/cloud-data.yml)가 공시·리포트·수급을 받아 사이트에 올린다 (2026-11-19).
맥과 같은 수집·빌드 코드를 돌린다 — 결과 모양이 같고, 맥이 깨어나 배포하면 맥 것으로 바뀐다.

전제 (워크플로가 마련):
  - db/dashboard.db  = 맥이 올린 DB 사본 (cloud_sync.py fetch)
  - public/data      → gh-pages 작업 폴더의 data 로 링크. 빌더가 사이트 파일(이익 성장·신고가 등)을 읽고, 바뀐 파일만 고쳐 쓴다
  - DART_API_KEY     = 저장소 비밀값

한 차례(cycle):
  - 매일 06:00~: 종목별 수급 새 거래일 (collect_naver flow --if-new). 기관 세부(KIS)는 키가 없어 빠진다 → 수급 탭은 외국인·기관만
  - 평일 07:00~19:30: DART 새 공시·KIND 시각, 네이버 증권사 리포트. 사본 뒤 빈 날도 이어 받는다(최대 7일)
  - 새로 들어온 것이 있으면 build_dart·build_events / build_naver --no-high·build_digest,
    홈은 공시·리포트·수급·목표가 카드만 갈아 끼운다(지수·시세 칸은 cloud_live 가 1분마다). 신고가는 cloud_live 가 따로 계산한다.
  - 빌드했는데 아직 못 올린 것이 있으면(dirty) 새로 받은 게 없어도 다시 빌드한다 → 워크플로가 푸시에 성공하면 `pushed`

  python3 cloud_data.py cycle [--force]   # 종료 코드: 0 빌드함(커밋할 것 있을 수 있음), 10 받은 것 없음, 1 실패
  python3 cloud_data.py pushed            # 올렸음 → dirty 지움
"""
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time as dtime
from pathlib import Path

import live   # 지문(fingerprint·DART_FP·RESEARCH_FP)과 실행 도우미를 같이 쓴다 (불러오기만 하면 아무것도 안 함)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'public' / 'data'
STATE = ROOT / '.cloud_state.json'
FLOW_START = dtime(6, 0)
DART_START, DART_END = dtime(7, 0), dtime(19, 30)
CATCHUP_MAX = 7
HOME_KEYS = ('tgt', 'flow', 'dart', 'reports')   # 클라우드가 갈아 끼우는 홈 카드


def run(args) -> int:
    print(f'--- {datetime.now():%H:%M:%S} {" ".join(args)}', flush=True)
    return subprocess.run([sys.executable, *args], cwd=ROOT).returncode


def state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save(s: dict):
    STATE.write_text(json.dumps(s))


def gap_days() -> int:
    """DB 사본의 마지막 공시일부터 오늘까지 (사본이 오래됐으면 그 사이도 받는다)"""
    try:
        con = sqlite3.connect(f'file:{live.DB}?mode=ro', uri=True)
        last = con.execute('SELECT MAX(date) FROM dart_filing').fetchone()[0]
        con.close()
        return max(1, min(CATCHUP_MAX, (date.today() - date.fromisoformat(last)).days))
    except (sqlite3.Error, TypeError, ValueError):
        return 1


def patch_home():
    """사이트 home.json 에 공시·리포트·수급·목표가 카드만 새로 (built·by·지수 칸은 그대로 — cloud_live 의 '맥이 배포함' 판정을 건드리지 않게)"""
    import build_home
    path = DATA / 'home.json'
    try:
        home = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        print('home.json 없음 — 홈 카드는 건너뜀')
        return
    cards = build_home.json_cards()
    new = {k: cards[k] for k in HOME_KEYS if cards.get(k)}
    if all(home.get(k) == v for k, v in new.items()):
        return
    home.update(new)
    path.write_text(json.dumps(home, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('홈 카드 갱신:', ', '.join(new))


def cycle(force: bool = False) -> int:
    if not live.DB.exists() or not DATA.exists():
        print('DB 사본이나 public/data(사이트 작업 폴더)가 없음')
        return 1
    t = datetime.now()
    st = state()
    got = lambda code: code in (0, 1)
    new_flow = new_dart = new_rep = False
    if force or t.time() >= FLOW_START:
        new_flow = got(run(['collect_naver.py', 'flow', '--if-new']))
    if force or (t.weekday() < 5 and DART_START <= t.time() <= DART_END):
        n = gap_days()
        dart0, rep0 = live.fingerprint(live.DB, live.DART_FP), live.fingerprint(live.DB, live.RESEARCH_FP)
        run(['collect_dart.py', '--days', str(n)])
        run(['collect_dart.py', 'times', '--latest'])
        run(['collect_naver.py', 'research', '--days', str(n + 1)])
        new_dart = live.changed(dart0, live.fingerprint(live.DB, live.DART_FP))
        new_rep = live.changed(rep0, live.fingerprint(live.DB, live.RESEARCH_FP))
    redo = bool(st.get('dirty')) or force
    built = False
    if new_dart or redo:
        if run(['build_dart.py']) != 0:
            return 1
        run(['build_events.py'])
        built = True
    if new_flow or new_rep or redo:
        if run(['build_naver.py', '--no-high']) != 0:
            return 1
        run(['build_digest.py'])
        built = True
    if not built:
        print(f'{datetime.now():%H:%M:%S} 새로 받은 것 없음')
        return 10
    patch_home()
    save({**st, 'dirty': True, 'built': datetime.now().isoformat(timespec='seconds')})
    return 0


def pushed() -> int:
    st = state()
    st.pop('dirty', None)
    save(st)
    return 0


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'cycle':
        sys.exit(cycle('--force' in sys.argv))
    if cmd == 'pushed':
        sys.exit(pushed())
    print(__doc__)
    sys.exit(2)
