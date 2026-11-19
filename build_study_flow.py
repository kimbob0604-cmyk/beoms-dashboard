#!/usr/bin/env python3
"""Study 흐름(섹터 × 날짜) 데이터 만들기 — docs/study-timeline-plan.md

  python3 build_study_flow.py          # study/flow/<섹터>.json → public/data/study/flow/<섹터>.json + index.json
  (build_study.py 가 빌드 끝에 부른다)

- 원본 study/flow/<섹터>.json: 리포트마다 성격·시각·한 줄 결론·핵심 주장·목표가·흐름 숫자(사람이 씀).
- 날짜·하우스·제목은 study/reports.json(표지 발간일). 표지에 월만 있으면 원본의 date_used 로 놓는다.
- 리포트 ↔ 카드 연결은 자동:
  · 그림·표 카드 → study_src/<문서>/figures.json 의 pdf(리포트 키)
  · 글·차트·계산 카드 → 카드 src(예 '신한 p.18 · KB p.8')에 나온 하우스 이름
  · 줄 단위: 글 카드의 한 줄이 '하우스:' 또는 '하우스(…):' 로 시작하면 그 리포트의 줄로 모은다(견해 차이·하우스만의 시각).
- 주(월요일 시작)별로 묶고, 흐름 숫자(목표주가·이익 추정 등)를 발간일 순으로 늘어놓는다.
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'study'
EXTRACT = ROOT / 'study_src'
OUT = ROOT / 'public' / 'data' / 'study' / 'flow'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def day(s):
    return date.fromisoformat(s) if s and len(s) == 10 else None


def week_of(d: date):
    mon = d - timedelta(days=d.weekday())
    sun = mon + timedelta(days=6)
    return mon, f'{mon.month}월 {(mon.day - 1) // 7 + 1}주', f'{mon.month}/{mon.day}~{sun.month}/{sun.day}'


def dig(obj, path):
    for p in path:
        if not isinstance(obj, dict) or p not in obj:
            return None
        obj = obj[p]
    return obj if isinstance(obj, (int, float)) else None


def house_re(house: str):
    # '삼성' 이 '삼성전자'·'삼성전기'에 걸리지 않게, 'KB' 가 'KBS' 에 걸리지 않게 앞뒤 글자를 막는다
    return re.compile(rf'(?<![가-힣A-Za-z]){re.escape(house)}(?![가-힣A-Za-z])')


def build_sector(fsrc: Path, reports: dict):
    src = load(fsrc)
    sec = src['sector']
    rmeta = {}
    for k, v in src['reports'].items():
        base = reports.get(k, {})
        d = v.get('date_used') or base.get('date', '')
        rmeta[k] = {**{f: base.get(f, '') for f in ('house', 'analyst', 'title')}, 'date': d,
                    'cover_date': base.get('date', ''), **v, 'figs': [], 'cards': [], 'lines': []}
    houses = {}
    for k, m in rmeta.items():
        houses.setdefault(m['house'], []).append(k)
    hres = {h: house_re(h) for h in houses}

    for doc_id in src.get('docs', []):
        doc = load(SRC / 'docs' / f'{doc_id}.json')
        figp = EXTRACT / doc_id / 'figures.json'
        fig_pdf = {x['key']: x.get('pdf') for x in load(figp)} if figp.exists() else {}
        for ti, t in enumerate(doc['topics']):
            for ci, c in enumerate(t['cards']):
                ref = {'doc': doc_id, 'ti': ti, 'ci': ci, 'node': t['node'], 'topic': t['title'],
                       'h': c.get('h') or '', 'p': c.get('p')}
                if c.get('ref'):
                    k = fig_pdf.get(c['ref'])
                    if k in rmeta:
                        rmeta[k]['figs'].append(ref)
                    continue
                s = c.get('src') or ''
                hit = [h for h, rx in hres.items() if rx.search(s)]
                for h in hit:
                    for k in houses[h]:
                        rmeta[k]['cards'].append(ref)
                if c.get('t') == 'sec':
                    for line in c.get('body', []):
                        for h, rx in hres.items():
                            m = rx.match(line)
                            if m and re.match(r'\s*(\(|:|：| ·|·)', line[m.end():]):
                                for k in houses[h]:
                                    rmeta[k]['lines'].append({**ref, 't': line})

    # 날짜순, 주 묶음, '직전' 리포트(같은 성격)
    order = sorted(rmeta, key=lambda k: (rmeta[k]['date'] or '9999', rmeta[k]['house']))
    last_by_kind = {}
    for k in order:
        m = rmeta[k]
        m['prev'] = last_by_kind.get(m.get('kind'))
        last_by_kind[m.get('kind')] = k
    weeks = {}
    for k in order:
        d = day(rmeta[k]['date'])
        if not d:
            weeks.setdefault(('9999', '날짜 미상', ''), []).append(k)
            continue
        mon, label, span = week_of(d)
        weeks.setdefault((mon.isoformat(), label, span), []).append(k)
    week_list = [{'start': s, 'label': lab, 'span': sp, 'reports': ks[::-1]} for (s, lab, sp), ks in sorted(weeks.items(), reverse=True)]

    metrics = []
    for mdef in src.get('metrics', []):
        pts = [{'key': k, 'date': rmeta[k]['date'], 'house': rmeta[k]['house'], 'v': dig(rmeta[k], mdef['path'])} for k in order]
        pts = [p for p in pts if p['v'] is not None]
        metrics.append({**{f: mdef[f] for f in ('id', 'label', 'unit')}, 'points': pts})

    out = {'sector': sec, 'generated_at': datetime.now().isoformat(timespec='seconds'), 'docs': src.get('docs', []),
           'books': src.get('books', []), 'order': order, 'weeks': week_list, 'metrics': metrics, 'reports': rmeta}
    ds = [rmeta[k]['date'] for k in order if day(rmeta[k]['date'])]
    summary = {'n': len(order), 'from': ds[0] if ds else '', 'to': ds[-1] if ds else '',
               'stance': {s: sum(1 for m in rmeta.values() if m.get('stance') == s) for s in ('낙관', '중립', '신중')}}
    return sec, out, summary


def main(write=True) -> int:
    reports = {k: v for k, v in load(SRC / 'reports.json').items() if not k.startswith('_')} if (SRC / 'reports.json').exists() else {}
    files = sorted((SRC / 'flow').glob('*.json')) if (SRC / 'flow').exists() else []
    index = {}
    for f in files:
        sec, out, summary = build_sector(f, reports)
        miss = [k for k in out['order'] if k not in reports]
        if miss:
            print(f'  흐름 {sec}: reports.json 에 없는 리포트 {", ".join(miss)}')
        nolink = [k for k in out['order'] if not (out['reports'][k]['figs'] or out['reports'][k]['cards'] or out['reports'][k]['lines'])]
        index[sec] = summary
        print(f'  흐름 {sec}: 리포트 {summary["n"]}건 · {summary["from"]}~{summary["to"]} · 주 {len(out["weeks"])}개'
              f' · 카드 연결 {sum(len(r["figs"]) + len(r["cards"]) for r in out["reports"].values())}개'
              + (f' · 연결 없음 {", ".join(nolink)}' if nolink else ''))
        if write:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f'{sec}.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    if write and files:
        (OUT / 'index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main('--check' not in sys.argv))
