"""
종목별 ETF 편입 — '이 종목을 담은 ETF 가 무엇이고, 그 ETF 가 얼마나 움직였고, 그 ETF 를 통해 이 종목에 돈이 얼마나 드나들었나'
→ public/data/etf/{종목코드}.json (종목 상세 패널의 'ETF 편입' 칸)

KBJ 컨테이너(kbj-scheduler-1)에서 kbj_etf_by_stock.py 로 ETF 마다 받는다:
  - 일별 순설정·환매(원) — KBJ 원장 계산(좌수 변화 × NAV, 분할·결측·검산 실패 날은 빠짐)
  - 종가(등락률용), 순자산, 기초지수
  - 구성 비중(운용사 PDF, 마지막 거래일 기준 ETF 마다 가장 최근 스냅)
여기서 '종목 → 담은 ETF' 로 뒤집는다.

  이 종목 몫(억) = ETF 순설정·환매 × 비중 — 설정·환매 때 LP·운용사가 바스켓으로 이 종목을 사고판 금액 추정
  ETF 보유액(억) = ETF 순자산 × 비중

한계: 비중은 지금 PDF 하나로 지난 20일에 모두 곱한다(그 사이 리밸런싱은 반영 안 됨).
운용사 PDF 를 받는 ETF(KODEX·TIGER·RISE·ACE·SOL·HANARO·PLUS·KoAct·TIMEFOLIO)만 들어가서 합계는 하한.
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


def fsum(f, k):
    """마지막 k 거래일 순설정·환매 합(억). 그 기간 하루도 모르면 None"""
    xs = [v for v in f[-k:] if v is not None]
    return round(sum(xs) / 1e8, 2) if xs else None


def build(x: dict) -> dict:
    """{종목코드: 파일 내용}"""
    from datetime import date, timedelta
    days = x['days'][1:]                               # 첫날은 등락률 기준일
    cut = (date.fromisoformat(x['end']) - timedelta(days=STALE_DAYS)).isoformat()
    etf = {}
    for c, e in x['etfs'].items():
        f = e['f'][1:]
        etf[c] = {'n': e['n'], 'bi': e['bi'], 'na': e['na'], 'f': f,
                  'r': [ret(e['cl'], 1), ret(e['cl'], 5), ret(e['cl'], 20)],
                  's': [fsum(f, 1), fsum(f, 5), fsum(f, 20)]}
    by = {}
    for c, h in x['hold'].items():
        e = etf.get(c)
        if e is None:
            continue
        for code, name, wt in h['w']:
            if not code.isdigit() or len(code) != 6 or code in x['etfs']:     # 현금·선물·채권·다른 ETF 행은 뺀다
                continue
            by.setdefault(code, {'n': name, 'rows': []})['rows'].append((c, wt, h['asof']))
    out = {}
    for code, s in by.items():
        rows, daily = [], [0.0] * len(days)
        for c, wt, asof in s['rows']:
            e = etf[c]
            w = wt / 100
            for i, v in enumerate(e['f']):
                if v is not None:
                    daily[i] += v * w
            rows.append([c, e['n'], round(wt, 3), None if e['na'] is None else round(e['na'] * w / 1e8, 1),
                         *e['r'], *e['s'], asof, 1 if asof < cut else 0, e['bi']])
        rows.sort(key=lambda r: -(r[3] or 0))           # ETF 보유액 큰 순
        out[code] = {'c': code, 'n': s['n'], 'd': x['end'], 'days': days, 'h': [round(v / 1e8, 2) for v in daily],
                     'cols': ['etf', 'name', 'wt', 'held', 'r1', 'r5', 'r20', 'f1', 'f5', 'f20', 'asof', 'stale', 'base'],
                     'rows': rows}
    return out


def main() -> int:
    if not container_up():
        print(f'KBJ 컨테이너({CONTAINER})가 꺼져 있습니다. 건너뜁니다.')
        return 4
    x = fetch()
    files = build(x)
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
