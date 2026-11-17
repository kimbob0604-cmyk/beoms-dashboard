"""
외국인 의료 소비 (한국관광 데이터랩 '의료관광 현황' — 외국인 카드 결제, 진료과목 8개) → db/trade.db 의 med 표

데이터랩은 공개 API 가 없지만, 화면이 부르는 조회 주소(POST /visualize/getTempleteData.do, 로그인 없음)를 그대로 쓴다.
- qid BY_TH_MEDIC_003_001_AMT / _CNT: 국적 × 진료과목 × 월 소비액(원)·건수. NAT_CD 000 = 글로벌(외국인 전체)
- 국적 목록은 /datalab/portal/theme/selectComNatList.do (25개국 + 기타)
- 진료과목: 피부과·성형외과·약국·대학/종합병원·치과·안과·한의학과·한약방
2018-01 부터 있다. 처음엔 전부, 그 뒤로는 하루 한 번 최근 13개월만 다시 받는다(국적마다 두 번 부른다, 1초씩 쉰다).
화면이 바뀌면 qid 가 바뀔 수 있다 — 그때는 실패로 끝나고 직전 값이 남는다.

  python3 collect_medical.py [--force|--status]
"""

import argparse
import sys
import time
from datetime import date, datetime

import requests

from collect_trade import connect

BASE = 'https://datalab.visitkorea.or.kr'
DATA = BASE + '/visualize/getTempleteData.do'
NATS = BASE + '/datalab/portal/theme/selectComNatList.do'
PAGE = BASE + '/datalab/portal/theme/getMedicalTourSearch.do'
START = '2018-01'
PAUSE = 1.0
SCHEMA = """
CREATE TABLE IF NOT EXISTS med (ym TEXT, nat_cd TEXT, nat TEXT, cat TEXT, amt REAL, cnt REAL, PRIMARY KEY (ym, nat_cd, cat));
"""


class MedError(RuntimeError):
    pass


def session() -> requests.Session:
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
    s.get(PAGE, timeout=30)                       # 세션 쿠키 (국적 목록이 쿠키 없이는 빈 응답)
    return s


def nations(s) -> list:
    r = s.post(NATS, timeout=30)
    try:
        lst = r.json()['list']
    except (ValueError, KeyError) as e:
        raise MedError(f'국적 목록 형식 오류: {r.text[:80]}') from e
    return [('000', '글로벌')] + [(x['natCd'], x['natNm']) for x in lst]


def query(s, kind: str, nat: str, ym1: str, ym2: str) -> list:
    """kind 'AMT'|'CNT' → [(ym, 진료과목, 값)]"""
    data = {'qid': f'BY_TH_MEDIC_003_001_{kind}', 'SGG_CD': '', 'SGG_NM': '', 'NAT_CD': nat,
            'BASE_YM1': ym1.replace('-', ''), 'BASE_YM2': ym2.replace('-', ''), 'srchAreaDate': '1', 'tabDiv': '3'}
    r = s.post(DATA, data=data, timeout=60)
    if r.status_code != 200:
        raise MedError(f'HTTP {r.status_code}')
    try:
        lst = r.json()['list']
    except (ValueError, KeyError) as e:
        raise MedError(f'형식 오류: {r.text[:80]}') from e
    key = 'CARD_COMPT_AMT_SUM' if kind == 'AMT' else 'CARD_COMPT_CNT_SUM'
    out = []
    for x in lst:
        ym, cat = str(x.get('BASE_YM', '')), x.get('KTO_CATE_SCLS_NM') or x.get('KTO_CATE_SCLS_CD')
        if len(ym) == 6 and cat and x.get(key) is not None:
            out.append((f'{ym[:4]}-{ym[4:]}', cat, float(x[key])))
    return out


def collect(conn, force: bool = False, today: date = None, log=print) -> int:
    today = today or date.today()
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT v FROM meta WHERE k = 'med_refreshed_at'").fetchone()
    if row and row[0][:10] == today.isoformat() and not force:
        log('외국인 의료 소비: 오늘 이미 받음')
        return 0
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    end = f'{y}-{m:02d}'
    empty = not conn.execute('SELECT 1 FROM med LIMIT 1').fetchone()
    start = START if empty else f'{y - 1}-{m:02d}'
    try:
        s = session()
        nats = nations(s)
    except (requests.RequestException, MedError) as e:
        log(f'외국인 의료 소비 실패: {str(e)[:120]} — 직전 값 유지')
        return 1
    n = fail = 0
    for cd, nm in nats:
        try:
            amt = query(s, 'AMT', cd, start, end)
            time.sleep(PAUSE)
            cnt = {(ym, cat): v for ym, cat, v in query(s, 'CNT', cd, start, end)}
            time.sleep(PAUSE)
        except (requests.RequestException, MedError) as e:
            fail += 1
            log(f'  실패 {nm}: {str(e)[:120]}')
            continue
        conn.executemany('INSERT OR REPLACE INTO med VALUES (?,?,?,?,?,?)',
                         [(ym, cd, nm, cat, v, cnt.get((ym, cat))) for ym, cat, v in amt])
        n += len(amt)
    if not fail:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('med_refreshed_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    conn.commit()
    log(f'외국인 의료 소비: {start}~{end} 국적 {len(nats)}, {n:,}줄, 실패 {fail} · 마지막 달 {conn.execute("SELECT MAX(ym) FROM med").fetchone()[0]}')
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    conn = connect()
    conn.executescript(SCHEMA)
    if a.status:
        r = conn.execute('SELECT COUNT(*), MIN(ym), MAX(ym), COUNT(DISTINCT nat_cd) FROM med').fetchone()
        print(f'med {r[0]:,}줄  {r[1]} ~ {r[2]}  국적 {r[3]}')
        return 0
    return collect(conn, a.force)


if __name__ == '__main__':
    sys.exit(main())
