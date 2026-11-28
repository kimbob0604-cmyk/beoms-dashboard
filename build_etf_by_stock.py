"""
종목별 ETF 편입 — '이 종목을 담은 ETF 가 무엇이고, 그 ETF 가 얼마나 움직였고, 그 ETF 를 통해 이 종목에 돈이 얼마나 드나들었나'
→ public/data/etf/{종목코드}.json (종목 상세 패널의 'ETF 편입' 칸)

KBJ 컨테이너(kbj-scheduler-1)에서 kbj_etf_by_stock.py 로 ETF 마다 받는다:
  - 일별 순설정·환매(원) — KBJ 원장 계산(좌수 변화 × NAV, 분할·결측·검산 실패 날은 빠짐)
  - 종가(등락률용), 순자산, 기초지수
  - 구성 비중(운용사 PDF, 마지막 거래일 기준 ETF 마다 가장 최근 스냅)
여기서 '종목 → 담은 ETF' 로 뒤집는다.

이 종목을 ETF 가 사고판 금액 = 보유 주식 수 변화 × 주가 를 둘로 나눈다 (주식 수 장부, docs/etf-by-stock-plan.md §3):
  설정·환매 몫(억) = ETF 순설정·환매(그날) × 그날 바스켓(PDF) 비중 — LP·운용사가 바스켓째 사고판 금액
  리밸런싱 몫(억) = Δ(1 CU 당 수량) × 좌수 × 주가 — 설정·환매 없이 운용사가 바스켓을 바꾼 매매
    좌수 = 상장좌수 ÷ CU, CU = 수량 × 주가 ÷ (비중 × 전일 NAV) 의 중앙값을 반올림(KODEX 200 → 50,000)
    PDF 날짜 D 의 바스켓은 D 직전 거래일 장 마감 뒤 것 → D 와 그 앞 PDF 의 수량 차는 D 직전 거래일 매매로 본다.
    그래서 마지막 거래일 리밸런싱은 다음 거래일 PDF 가 와야 안다(None).
    PDF 가 며칠 비면 그 사이 차이를 다음 PDF 직전 거래일 하나에 몰아 적고 '구간 합'(g) 표시.
    주가 = 그날 PDF 금액 ÷ 수량(여러 ETF 중앙값). 주가가 갑자기 반·두 배가 되고 수량이 거꾸로 움직이면
    분할·병합으로 보고 뺀다. 펀드 하루 리밸런싱 순액이 순자산의 15% 를 넘으면 바스켓 재설정으로 보고 뺀다.
  ETF 보유액(억) = ETF 순자산 × 비중
정기변경(public/data/rebal.json — build_rebal.py)의 편입·편출 종목에는 'rebal' 을 붙인다:
  예상 = 추종 자금(1배 + TR ETF) × 편입 후 비중(편출은 − 지금 비중), 거래대금 며칠치
  실측 = 리밸런싱일(매매일)의 리밸런싱 몫 합 — 다음 거래일 PDF(적용일 PDF)가 들어온 뒤에야 나온다
  적용일 + REBAL_KEEP 달력일까지 붙인다.

한계: 운용사 PDF 를 받는 ETF(KODEX·TIGER·RISE·ACE·SOL·HANARO·PLUS·KoAct·TIMEFOLIO)만 들어가서 합계는 하한.
레버리지·인버스의 선물 노출은 PDF 에서 종목이 아니므로 빠진다.

  python3 build_etf_by_stock.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'public' / 'data' / 'etf'
CONTAINER = 'kbj-scheduler-1'       # KBJ 파이썬이 있는 컨테이너 (사이트용 kbj-api-1 은 안 띄운다)
N = 20                      # 순설정·환매를 받는 거래일 수 (1·5·20일 합)
STALE_DAYS = 7              # 마지막 거래일보다 이만큼 오래된 PDF 는 '비중 오래됨'
RESET_SHARE = 0.15          # 펀드 하루 리밸런싱 순액 ÷ 순자산이 이보다 크면 바스켓 재설정(매매 아님)
EV_MIN = 1e8                # 표에 '편입·편출·비중' 표시를 붙이는 리밸런싱 금액 하한(원)
REBAL = ROOT / 'public' / 'data' / 'rebal.json'
REBAL_KEEP = 30             # 정기변경 적용일 뒤 이 달력일까지 패널에 남긴다


def container_up() -> bool:
    try:
        r = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and r.stdout.strip() == 'true'
    except (OSError, subprocess.SubprocessError):
        return False


def fetch() -> dict:
    script = (ROOT / 'kbj_etf_by_stock.py').read_text(encoding='utf-8')
    r = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-', str(N)], input=script,
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f'kbj_etf_by_stock 실패 (종료 {r.returncode}): {r.stderr.strip().splitlines()[-1:]}')
    return json.loads(r.stdout)


def ret(cl, k):
    """마지막 종가 ÷ k 거래일 전 종가 − 1 (%). 모르면 None"""
    if len(cl) <= k or cl[-1] is None or not cl[-1 - k]:
        return None
    return round((cl[-1] / cl[-1 - k] - 1) * 100, 2)


def ksum(xs, k):
    """마지막 k 개 합(억). 그 기간 하루도 모르면 None"""
    v = [a for a in xs[-k:] if a is not None]
    return round(sum(v) / 1e8, 2) if v else None


def nice(v):
    """CU 반올림 — 유효숫자 2자리(안 맞으면 3자리)로 2% 안이면 그 값, 아니면 그대로"""
    from math import floor, log10
    for sig in (2, 3):
        k = 10 ** (floor(log10(v)) - sig + 1)
        r = round(v / k) * k
        if abs(v / r - 1) < 0.02:
            return r
    return v


def prices(snap):
    """{PDF 날짜: {종목: 주가}} — PDF 금액 ÷ 수량의 ETF 간 중앙값 (그 PDF 직전 거래일 종가)"""
    from statistics import median
    acc = {}
    for sn in snap.values():
        for d, rows in sn.items():
            m = acc.setdefault(d, {})
            for c, q, _w, v in rows:
                if v and q > 0:
                    m.setdefault(c, []).append(v / q)
    return {d: {c: median(v) for c, v in m.items()} for d, m in acc.items()}


def cu_of(sn, nav, tds, px):
    """ETF 의 CU(1 설정단위 좌수) — 비중 1% 넘는 종목마다 수량 × 주가 × 100 ÷ (비중 × 전일 NAV) 의 중앙값"""
    from bisect import bisect_left
    from statistics import median
    raw = []
    for d, rows in sn.items():
        j = bisect_left(tds, d) - 1                     # PDF 날짜 직전 거래일
        if j < 0 or not nav[j]:
            continue
        for c, q, w, _v in rows:
            p = px.get(d, {}).get(c)
            if w and w > 1 and p:
                raw.append(q * p * 100 / (w * nav[j]))
    return nice(median(raw)) if raw else None


def ledger(x):
    """ETF·종목·거래일별 리밸런싱 매매(원) → ({ETF: {종목: {i: [원, 구간합, 앞수량, 뒤수량, 앞비중, 뒤비중]}}}, 아는 마지막 i, 뺀 수)"""
    from bisect import bisect_left
    tds = x['days']
    px = prices(x['snap'])
    out, known, skipped = {}, -1, {'split': 0, 'reset': 0}
    for etf, sn in x['snap'].items():
        e = x['etfs'][etf]
        cu = cu_of(sn, e['nav'], tds, px)
        if not cu:
            continue
        ds = sorted(sn)
        for a, b in zip(ds, ds[1:]):
            i = bisect_left(tds, b) - 1                 # 매매일 = b 직전 거래일
            if i < 1:
                continue
            known = max(known, i)
            ls = e['ls'][i]
            if not ls:
                continue
            u = ls / cu
            qa = {c: (q, w) for c, q, w, _v in sn[a]}
            qb = {c: (q, w) for c, q, w, _v in sn[b]}
            gap = 1 if bisect_left(tds, a) != i else 0  # a 가 매매일 PDF 가 아니면(사이가 비면) 구간 합
            pa, pb = px.get(a, {}), px.get(b, {})
            day, net = {}, 0.0
            for c in qa.keys() | qb.keys():
                q0, w0 = qa.get(c, (0.0, None))
                q1, w1 = qb.get(c, (0.0, None))
                if q0 == q1:
                    continue
                p = pb.get(c) or pa.get(c)
                if not p:
                    continue
                if q0 and q1 and pa.get(c) and pb.get(c):
                    r = pb[c] / pa[c]
                    if (r < 0.7 or r > 1.4) and abs(q1 / q0 * r - 1) < 0.1:   # 분할·병합 — 금액은 그대로
                        skipped['split'] += 1
                        continue
                v = (q1 - q0) * u * p
                net += v
                day[c] = [v, gap, q0, q1, w0, w1]
            na = (e['nav'][i] or 0) * ls
            if na and abs(net) > RESET_SHARE * na:
                skipped['reset'] += 1
                continue
            for c, r in day.items():
                out.setdefault(etf, {}).setdefault(c, {})[i] = r
    return out, known, skipped


def rebal_marks(rb: dict | None, end: str) -> dict:
    """{종목코드: 정기변경 한 줄} — rebal.json 의 편입·편출. 적용일 + REBAL_KEEP 일이 지났으면 비운다"""
    from datetime import date, timedelta
    if not rb or not rb.get('event'):
        return {}
    ev = rb['event']
    if date.fromisoformat(end) > date.fromisoformat(ev['effective']) + timedelta(days=REBAL_KEEP):
        return {}
    out = {}
    for I in rb.get('idx', {}).values():
        a = (I['aum'].get('etf1') or 0) + (I['aum'].get('tr') or 0)          # 억 (신한식: 1배 + TR)
        for kind, xs in (('in', I.get('new', [])), ('out', I.get('out', []))):
            for s in xs:
                if s.get('w') is None:
                    continue
                v = a * s['w'] * (1 if kind == 'in' else -1)
                out[s['c']] = {'t': ev['title'], 'idx': I['name'], 'k': kind, 'rd': ev['rebalance'], 'ed': ev['effective'],
                               'w': round(s['w'] * 100, 3), 'wa': None if s.get('wa') is None else round(s['wa'] * 100, 3),
                               'exp': round(v, 1), 'tv': s.get('tv20'),
                               'n': s.get('n'), 'aum': round(a), 'aum_d': I['aum'].get('date')}
    return out


def build(x: dict, rb: dict | None = None) -> dict:
    """{종목코드: 파일 내용}"""
    from bisect import bisect_right
    from datetime import date, timedelta
    tds = x['days']
    days = tds[1:]                                     # 첫날은 등락률 기준일
    n = len(days)
    cut = (date.fromisoformat(x['end']) - timedelta(days=STALE_DAYS)).isoformat()
    reb, known, skipped = ledger(x)
    print(f'리밸런싱 장부: ETF {len(reb)}개 · 아는 마지막 매매일 {tds[known] if known >= 0 else None} · '
          f'분할로 뺀 {skipped["split"]} · 바스켓 재설정으로 뺀 {skipped["reset"]}')
    etf = {}
    for c, e in x['etfs'].items():
        f = e['f'][1:]
        etf[c] = {'n': e['n'], 'bi': e['bi'], 'na': e['na'], 'f': f,
                  'r': [ret(e['cl'], 1), ret(e['cl'], 5), ret(e['cl'], 20)],
                  's': [ksum(f, 1), ksum(f, 5), ksum(f, 20)]}
    # 그날 설정·환매에 쓰인 바스켓 비중 = 그날(또는 그 앞 가장 가까운) PDF. 앞 PDF 가 없으면 첫 PDF
    wts = {}
    for c, sn in x['snap'].items():
        ds = sorted(sn)
        wmap = {d: {k: w for k, _q, w, _v in sn[d] if w} for d in ds}
        row = []
        for t in days:
            j = bisect_right(ds, t) - 1
            row.append(wmap[ds[max(j, 0)]])
        wts[c] = row
    by = {}
    for c, h in x['hold'].items():
        if c not in etf:
            continue
        for code, name, wt in h['w']:
            if not ok_code(code, x['etfs']):
                continue
            by.setdefault(code, {'n': name, 'rows': {}})['rows'][c] = (wt, h['asof'])
    for c, m in reb.items():                          # 기간 안에 편출돼 지금 PDF 에 없는 ETF 도 넣는다
        for code in m:
            if ok_code(code, x['etfs']) and c in etf:
                by.setdefault(code, {'n': None, 'rows': {}})['rows'].setdefault(c, (0.0, None))
    last_known = known - 1                             # days 기준 i (tds 첫날을 뺐으므로 −1)
    marks = rebal_marks(rb, x['end'])
    for code, m in marks.items():                      # 담은 ETF 가 없는 편입 예정 종목도 파일을 만든다
        by.setdefault(code, {'n': m['n'], 'rows': {}})
    out = {}
    for code, s in by.items():
        cr, rb, gp = [0.0] * n, [0.0 if i <= last_known else None for i in range(n)], [0] * n
        rows = []
        for c, (wt, asof) in s['rows'].items():
            e = etf[c]
            cd = [None] * n
            for i, v in enumerate(e['f']):
                w = wts[c][i].get(code) if c in wts else wt
                if v is not None and w:
                    cd[i] = v * w / 100
                    cr[i] += cd[i]
            rd = [None if i > last_known else 0.0 for i in range(n)]
            ev = None
            for ti, (v, g, q0, q1, w0, w1) in reb.get(c, {}).get(code, {}).items():
                i = ti - 1
                if i < 0 or i >= n:
                    continue
                rd[i] = (rd[i] or 0.0) + v
                rb[i] = (rb[i] or 0.0) + v
                gp[i] = max(gp[i], g)
                if abs(v) >= EV_MIN and (ev is None or abs(v) > abs(ev[5])):
                    kind = 'NEW' if not q0 else 'DROP' if not q1 else 'ADD' if q1 > q0 else 'CUT'
                    ev = [kind, days[i], q0, q1, w1 if w1 is not None else w0, round(v / 1e8, 1)]
            if not any(cd) and not any(rd) and not wt:
                continue
            rows.append([c, e['n'], round(wt, 3), None if e['na'] is None else round(e['na'] * wt / 100 / 1e8, 1),
                         *e['r'], *e['s'], asof, 1 if asof and asof < cut else 0, e['bi'],
                         ksum(cd, 1), ksum(cd, 5), ksum(cd, 20), ksum(rd, 1), ksum(rd, 5), ksum(rd, 20), ev])
        m = marks.get(code)
        if not rows and not m:
            continue
        if m:
            m = dict(m)
            ri = days.index(m['rd']) if m['rd'] in days else None
            m['act'] = None if ri is None or rb[ri] is None else round(rb[ri] / 1e8, 1)   # 실측: 리밸런싱일 리밸런싱 몫 합
            m.pop('n')
        rows.sort(key=lambda r: -(r[3] or 0))           # ETF 보유액 큰 순
        out[code] = {'c': code, 'n': s['n'] or x.get('names', {}).get(code), 'd': x['end'], 'days': days,
                     'h': [round(v / 1e8, 2) for v in cr],
                     'rb': [None if v is None else round(v / 1e8, 2) for v in rb], 'g': gp,
                     'cols': ['etf', 'name', 'wt', 'held', 'r1', 'r5', 'r20', 'f1', 'f5', 'f20', 'asof', 'stale', 'base',
                              'c1', 'c5', 'c20', 'b1', 'b5', 'b20', 'ev'],
                     'rows': rows, 'rebal': m}
    return out


def ok_code(code, etfs):
    """국내 주식 종목코드만 (현금·선물·채권·다른 ETF 행은 뺀다)"""
    return len(code) == 6 and code[0].isdigit() and code.isalnum() and code not in etfs


def main() -> int:
    if not container_up():
        print(f'KBJ 컨테이너({CONTAINER})가 꺼져 있습니다. 건너뜁니다.')
        return 4
    x = fetch()
    try:
        rb = json.loads(REBAL.read_text(encoding='utf-8')) if REBAL.exists() else None
    except (OSError, ValueError):
        rb = None
    files = build(x, rb)
    OUT.mkdir(parents=True, exist_ok=True)
    keep = set()
    for code, d in files.items():
        p = OUT / f'{code}.json'
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        keep.add(p.name)
    for p in OUT.glob('*.json'):                        # 이제 아무 ETF 도 안 담은 종목 파일은 지운다
        if p.name not in keep:
            p.unlink()
    n_known = len(x['hold'])
    print(f"ETF 편입: {x['end']} · 종목 {len(files)}개 · 구성 아는 ETF {n_known}/{len(x['etfs'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
