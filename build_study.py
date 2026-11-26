"""
Beom's Study 빌드: study/ (손으로 쓰는 원본) → public/data/study/ (화면용 JSON)

  python3 build_study.py            # 검증 + 빌드
  python3 build_study.py --check    # 검증만

입력
  study/tree.json              분류 트리 (섹터 → 주제)
  study/entities.json          공통 색인 (개념 c: · 약물 d: · 기업 co: · 임상 tr: · 적응증 ind:)
  study/docs/{doc}.json        문서별 카드
  study/media/manifest.json    공개 이미지(위키미디어·RCSB PDB) 출처·저작자·라이선스 + 정리한 파일
  섹터별 조각(병렬 작업용): study/tree/<섹터>.json, study/entities/<섹터>.json, study/media/manifest-<섹터>.json
  study_src/{doc}/figures.json study_extract.py 가 만든 그림·표 목록 (번호·쪽·이미지·표 데이터)
출력
  public/data/study/index.json       트리(노드별 주제 목록) + 문서 목록 + 색인(어느 카드에 나왔는지)
  public/data/study/docs/{doc}.json  카드 (그림·표 정보를 붙여서)

검증
  오류(빌드 중단): 없는 노드, 없는 그림·표 번호, 없는 색인 키, 같은 그림을 두 카드에서 씀,
                  없는 설명 그림(study/diagrams/*.svg), 재구성 차트 데이터 길이 불일치
  경고: 작성 끝난 쪽 범위(done) 안에 카드가 없는 그림·표
"""

import argparse
import collections
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'study'
EXTRACT = ROOT / 'study_src'
OUT = ROOT / 'public' / 'data' / 'study'

KINDS = {'c': '개념', 'd': '약물', 'co': '기업', 'tr': '임상', 'ind': '적응증', 'n': '국가'}


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def check_chart(ch):
    """재구성 차트 데이터 모양 검사 → 문제 목록"""
    out = []
    t = ch.get('type')
    if t in ('bar', 'stack', 'line'):
        n = len(ch.get('x', []))
        for s in ch.get('series', []):
            if len(s.get('values', [])) != n:
                out.append(f'{s.get("name")}: 값 {len(s.get("values", []))}개 ≠ 항목 {n}개')
        if ch.get('color_by') and len(ch['color_by']) != n:
            out.append('color_by 길이가 항목 수와 다름')
    elif t == 'range':
        n = len(ch.get('x', []))
        for s in ch.get('series', []):
            if len(s.get('lo', [])) != n or len(s.get('hi', [])) != n:
                out.append(f'{s.get("name")}: lo/hi 길이 ≠ 항목 {n}개')
    elif t == 'scatter':
        if not ch.get('points'):
            out.append('점이 없음')
    else:
        out.append(f'모르는 종류 {t}')
    if ch.get('src') not in ('label', 'pixel', 'table', 'calc', 'ext'):
        out.append('src 는 label·pixel·table·calc·ext 중 하나')
    return out


def walk(nodes, prefix=''):
    for n in nodes:
        path = f'{prefix}/{n["id"]}' if prefix else n['id']
        yield path, n
        yield from walk(n.get('children', []), path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()

    tree = load(SRC / 'tree.json')
    errs, warns = [], []
    # 섹터별 조각 합치기: 병렬 세션이 서로 다른 파일만 고치도록
    #   study/tree/<섹터>.json   {"sector": "semi", "children": [...]}  → 그 섹터 아래에 붙인다
    #   study/entities/<섹터>.json  색인 추가분 (키가 겹치면 오류)
    #   study/media/manifest-<섹터>.json  공개 이미지 추가분
    for f in sorted((SRC / 'tree').glob('*.json')) if (SRC / 'tree').exists() else []:
        frag = load(f)
        sec = next((s for s in tree['sectors'] if s['id'] == frag.get('sector')), None)
        if not sec:
            errs.append(f'{f.name}: 트리에 없는 섹터 {frag.get("sector")}')
            continue
        have = {c['id'] for c in sec.get('children', [])}
        for c in frag.get('children', []):
            if c['id'] in have:
                errs.append(f'{f.name}: {frag["sector"]}/{c["id"]} 가 이미 있음')
            sec.setdefault('children', []).append(c)
    ents = {k: v for k, v in load(SRC / 'entities.json').items() if not k.startswith('_')}
    for f in sorted((SRC / 'entities').glob('*.json')) if (SRC / 'entities').exists() else []:
        for k, v in load(f).items():
            if k.startswith('_'):
                continue
            if k in ents:
                errs.append(f'{f.name}: 색인 {k} 가 이미 있음 (entities.json 또는 다른 조각)')
            ents[k] = v
    # 반도체 탭 칸 (semi_assets.json, 다른 세션 소유 — 읽기만): 색인·카드의 semi: [칸 id] → 이름 붙여 링크
    semi_cells = {}
    sa = ROOT / 'semi_assets.json'
    if sa.exists():
        semi_cells = {c['id']: c['name'] for c in load(sa).get('cells', [])}

    def link_cells(obj, where):
        ids = obj.get('semi') or []
        if isinstance(ids, str):
            ids = [ids]
        bad = [i for i in ids if i not in semi_cells]
        if bad and semi_cells:
            warns.append(f'{where}: 반도체 탭에 없는 칸 {", ".join(bad)}')
        obj['semi_cells'] = [{'id': i, 'name': semi_cells[i]} for i in ids if i in semi_cells]

    nodes = {}
    for s in tree['sectors']:
        for path, n in walk([s]):
            nodes[path] = n

    # 색인 키 자체 검사
    for k, e in ents.items():
        kind = k.split(':')[0]
        if kind not in KINDS:
            errs.append(f'색인 {k}: 앞머리를 모름 ({", ".join(KINDS)})')
        e['kind'] = kind
        for r in e.get('co', []) + e.get('tags', []):
            if r not in ents:
                errs.append(f'색인 {k}: 연결된 {r} 가 색인에 없음')
        e['refs'] = []
        if e.get('semi'):
            link_cells(e, f'색인 {k}')

    # 공개 이미지 목록 (위키미디어·RCSB PDB 등, 출처·라이선스 포함)
    media = {}
    for mf in sorted((SRC / 'media').glob('manifest*.json')) if (SRC / 'media').exists() else []:
        for k, v in load(mf).items():
            if k.startswith('_'):
                continue
            if k in media:
                errs.append(f'{mf.name}: 공개 이미지 {k} 가 이미 있음')
            media[k] = v
    used_media = set()
    for k, m in media.items():
        if not (SRC / 'media' / m.get('file', '')).exists():
            errs.append(f'공개 이미지 {k}: 파일 {m.get("file")} 없음')
        for need in ('source', 'page', 'license'):
            if not m.get(need):
                errs.append(f'공개 이미지 {k}: {need} 없음 (출처·라이선스는 반드시 적는다)')

    docs_meta, doc_out = {}, {}
    node_topics = {p: [] for p in nodes}
    # 리포트 표지 발간일 (study/reports.json): 여러 리포트를 합친 문서의 그림마다 [하우스 · YY.MM.DD] 로 붙고, 문서 쪽에 목록으로 나온다
    try:   # 새로 쓰인 리포트는 표지에서 발간일을 읽어 목록에 자동으로 넣는다 (study_reports.py)
        import study_reports
        for k, e in study_reports.sync():
            warns.append(f'리포트 발간일 자동 추가: {k} {e["date"] or "?"} {e["house"]} — 표지와 맞는지 확인' + (f' ({e["check"]})' if e.get('check') else ''))
    except Exception as e:
        warns.append(f'리포트 발간일 자동 추가 실패: {e}')
    REPORTS = {k: v for k, v in load(SRC / 'reports.json').items() if not k.startswith('_')} if (SRC / 'reports.json').exists() else {}
    for f in sorted((SRC / 'docs').glob('*.json')):
        d = load(f)
        fig_path = EXTRACT / d['id'] / 'figures.json'
        figs = {x['key']: x for x in load(fig_path)} if fig_path.exists() else {}
        doc_reports = {}
        for x in figs.values():   # 그림의 pdf 가 리포트 키(문자열)면 그 리포트의 날짜를 붙인다 (책·단일 리포트는 쪽 번호라 건너뜀)
            rk = x.get('pdf') if isinstance(x.get('pdf'), str) else None
            if rk:
                if rk in REPORTS:
                    x['date'] = REPORTS[rk]['date']
                    doc_reports[rk] = REPORTS[rk]
                else:
                    warns.append(f'{d["id"]}: 리포트 {rk} 의 발간일이 study/reports.json 에 없음')
        for rk in d.get('source', {}).get('reports', []):   # 그림 없이 글만 쓴 리포트는 문서 source.reports 에 적는다
            if rk in REPORTS:
                doc_reports[rk] = REPORTS[rk]
            else:
                warns.append(f'{d["id"]}: source.reports 의 {rk} 발간일이 study/reports.json 에 없음')
        if not doc_reports and d['id'] in REPORTS:   # 리포트 한 건짜리 문서
            doc_reports[d['id']] = REPORTS[d['id']]
        if not figs:
            warns.append(f'{d["id"]}: {fig_path} 없음 — study_extract.py 를 먼저 실행')
        used = {}
        ncards = 0
        # 애널리스트 필터(2026-11-26 사용자): 카드마다 '하우스 애널리스트' 이름표(c['an']) — 그림은 그림의 리포트 키로, 글 카드는 src 에 적힌 하우스 이름으로
        an_of = lambda rk: f"{REPORTS[rk]['house']} {REPORTS[rk].get('analyst') or ''}".strip() if rk in REPORTS else None
        by_house = collections.defaultdict(set)
        for k, v in doc_reports.items():
            if v.get('house'):
                by_house[v['house']].add(an_of(k))
        # 같은 하우스 리포트가 여럿이면 글 카드는 누구 것인지 모른다 → '하우스 (여러 리포트)' 로 묶는다 (그림 카드는 리포트 키로 정확히 붙음)
        house_re = [(re.compile(rf"(?<![가-힣A-Za-z]){re.escape(h)}(?:투자증권|증권)?(?![가-힣A-Za-z])"), next(iter(a)) if len(a) == 1 else f'{h} (여러 리포트)') for h, a in by_house.items()]
        only = an_of(next(iter(doc_reports))) if len(doc_reports) == 1 else None
        for ti, t in enumerate(d['topics']):
            if t['node'] not in nodes:
                errs.append(f'{d["id"]} 주제 "{t["title"]}": 트리에 없는 노드 {t["node"]}')
                continue
            for ci, c in enumerate(t['cards']):
                ncards += 1
                where = f'{d["id"]} / {t["title"]} / 카드 {ci + 1}'
                if c['t'] in ('fig', 'tbl'):
                    ref = c.get('ref')
                    if ref not in figs:
                        errs.append(f'{where}: 그림·표 {ref} 없음')
                        continue
                    if ref in used:
                        errs.append(f'{where}: {ref} 를 {used[ref]} 에서도 씀')
                    used[ref] = where
                    x = figs[ref]
                    c['fig'] = {k: x[k] for k in ('key', 'kind', 'no', 'title', 'page', 'img', 'w', 'h', 'source', 'part')}
                    if x.get('date'):
                        c['fig']['date'] = x['date']
                    c['fig'].update({k: x[k] for k in ('hd', 'hd_w', 'hd_h', 'scan', 'raw', 'raw_w', 'raw_h') if k in x})
                    if c.get('tech') and not x.get('hd'):
                        errs.append(f'{where}: 해설(tech)에 쓸 정리본 이미지(-hd)가 없음 — 벡터 그림이면 원본 렌더로 대체 필요')
                    for sp in (c.get('tech') or {}).get('spots', []):
                        if not (0 <= sp.get('x', -1) <= 100 and 0 <= sp.get('y', -1) <= 100):
                            errs.append(f'{where}: 해설 번호 {sp.get("n")} 위치가 0~100% 밖')
                    if x.get('rows'):
                        c['fig']['rows'] = x['rows']
                    c.setdefault('p', x['page'])
                if c['t'] == 'seq':     # 단계 넘기기: 그림 여러 장을 차례로 (같은 그림을 다른 카드에서 또 써도 된다)
                    if not c.get('steps'):
                        errs.append(f'{where}: 단계 넘기기에 steps 가 없음')
                    for si, st in enumerate(c.get('steps', [])):
                        x = figs.get(st.get('ref'))
                        if not x:
                            errs.append(f'{where}: 단계 {si + 1} 그림 {st.get("ref")} 없음')
                            continue
                        used.setdefault(st['ref'], where)
                        st['fig'] = {k: x[k] for k in ('key', 'kind', 'no', 'title', 'page', 'img', 'w', 'h', 'part', 'date') if k in x}
                        st['fig'].update({k: x[k] for k in ('hd', 'hd_w', 'hd_h', 'scan') if k in x})
                        for sp in st.get('spots', []):
                            if not (0 <= sp.get('x', -1) <= 100 and 0 <= sp.get('y', -1) <= 100):
                                errs.append(f'{where}: 단계 {si + 1} 번호 {sp.get("n")} 위치가 0~100% 밖')
                if c['t'] == 'ext':     # 공개 이미지 해설 (study/media)
                    m = media.get(c.get('media'))
                    if not m:
                        errs.append(f'{where}: 공개 이미지 {c.get("media")} 가 study/media/manifest.json 에 없음')
                    else:
                        c['m'] = {**m, 'img': f'data/study/media/{m["file"]}'}
                        used_media.add(c['media'])
                    for sp in (c.get('tech') or {}).get('spots', []):
                        if not (0 <= sp.get('x', -1) <= 100 and 0 <= sp.get('y', -1) <= 100):
                            errs.append(f'{where}: 해설 번호 {sp.get("n")} 위치가 0~100% 밖')
                if c['t'] == 'calc':    # 가정 조절 계산 카드: 입력·출력 모양만 검사
                    ks = [x.get('k') for x in c.get('inputs', [])]
                    if not ks or not c.get('out'):
                        errs.append(f'{where}: 계산 카드에 inputs·out 이 없음')
                    for o in c.get('out', []):
                        if not o.get('f'):
                            errs.append(f'{where}: 계산 결과 {o.get("label")} 에 식(f)이 없음')
                if c['t'] == 'dia':
                    svg = SRC / 'diagrams' / f'{c.get("dia")}.svg'
                    if not svg.exists():
                        errs.append(f'{where}: 설명 그림 {svg.name} 없음')
                    else:
                        c['svg'] = svg.read_text(encoding='utf-8')
                if c.get('chart'):
                    errs += [f'{where}: 차트 {m}' for m in check_chart(c['chart'])]
                if c.get('semi'):
                    link_cells(c, where)
                an = []
                for fx in [c.get('fig')] + [st.get('fig') for st in c.get('steps', [])]:
                    rk = figs.get((fx or {}).get('key'), {}).get('pdf') if fx else None
                    if isinstance(rk, str) and an_of(rk):
                        an.append(an_of(rk))
                if not an and c.get('src'):
                    an = [a for rx, a in house_re if a and rx.search(str(c['src']))]
                if not an and only:
                    an = [only]
                if an:
                    c['an'] = sorted(set(an))
                for k in c.get('tags', []) + c.get('addTags', []):
                    if k not in ents:
                        errs.append(f'{where}: 색인에 없는 키 {k}')
                        continue
                    ents[k]['refs'].append({'doc': d['id'], 'ti': ti, 'ci': ci, 'node': t['node'],
                                            'topic': t['title'], 'p': c.get('p'),
                                            'h': c.get('h') or (c.get('fig') or {}).get('title', ''),
                                            'add': k in c.get('addTags', [])})
            node_topics[t['node']].append({'doc': d['id'], 'ti': ti, 'title': t['title'], 'pages': t.get('pages'),
                                           'n': len(t['cards']),
                                           'an': dict(collections.Counter(a for c in t['cards'] for a in c.get('an', []))),
                                           'nfig': sum(1 for c in t['cards'] if c['t'] in ('fig', 'tbl'))})
        # 빠진 그림: 작성 끝난 범위 안인데 카드가 없음
        lo, hi = d.get('done', [0, -1])
        miss = [k for k, x in figs.items() if lo <= x['page'] <= hi and k not in used]
        if miss:
            warns.append(f'{d["id"]}: p.{lo}~{hi} 안에 카드 없는 그림·표 {len(miss)}개 — {", ".join(miss)}')
        done_figs = sum(1 for x in figs.values() if lo <= x['page'] <= hi)
        docs_meta[d['id']] = {k: d.get(k) for k in ('id', 'sector', 'title', 'source', 'done', 'overview')}
        docs_meta[d['id']]['reports'] = sorted(({'key': k, **v} for k, v in doc_reports.items()), key=lambda r: (r['date'] if len(r['date']) > 7 else r['date'] + '-99', r['house']))   # 월만 있는 날짜는 그달 끝으로
        docs_meta[d['id']].update({'nfig_total': len(figs), 'nfig_done': len(used), 'nfig_in_done': done_figs,
                                   'ncards': ncards,
                                   'topics': [{'ti': i, 'node': t['node'], 'title': t['title'], 'pages': t.get('pages')}
                                              for i, t in enumerate(d['topics'])]})
        doc_out[d['id']] = d

    for w in warns:
        print('경고:', w)
    for e in errs:
        print('오류:', e)
    if errs:
        return 1

    # 트리에 주제·개수 붙이기
    def attach(ns, prefix=''):
        out = []
        for n in ns:
            path = f'{prefix}/{n["id"]}' if prefix else n['id']
            kids = attach(n.get('children', []), path)
            topics = node_topics.get(path, [])
            an = collections.Counter()
            for x in topics:
                an.update(x.get('an', {}))
            for k in kids:
                an.update(k.get('an', {}))
            out.append({'id': n['id'], 'path': path, 'name': n['name'], 'desc': n.get('desc', ''),
                        'topics': topics, 'children': kids, 'an': dict(an.most_common()),
                        'count': len(topics) + sum(k['count'] for k in kids)})
        return out

    index = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'tree': attach(tree['sectors']),
        'docs': docs_meta,
        'kinds': KINDS,
        'entities': ents,
    }
    nref = sum(1 for e in ents.values() if e['refs'])
    print(f'문서 {len(doc_out)} · 카드 {sum(m["ncards"] for m in docs_meta.values())} · '
          f'색인 {len(ents)}개 중 {nref}개 사용')
    for m in docs_meta.values():
        print(f'  {m["id"]}: 그림·표 {m["nfig_done"]}/{m["nfig_total"]} 카드화 (작성 범위 p.{m["done"][0]}~{m["done"][1]} 안 {m["nfig_in_done"]}개)')
    unused = [k for k, e in ents.items() if not e['refs']]
    if unused:
        print('  카드에서 안 쓰인 색인:', ', '.join(unused))
    if a.check:
        return 0

    (OUT / 'docs').mkdir(parents=True, exist_ok=True)
    (OUT / 'media').mkdir(parents=True, exist_ok=True)
    for k in used_media:
        f = media[k]['file']
        (OUT / 'media' / f).write_bytes((SRC / 'media' / f).read_bytes())
    index['media'] = media
    (OUT / 'index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    for k, d in doc_out.items():
        (OUT / 'docs' / f'{k}.json').write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    print('→', OUT.relative_to(ROOT))
    try:   # 흐름(섹터 × 날짜) 데이터: study/flow/<섹터>.json 이 있는 섹터만 → data/study/flow/ (build_study_flow.py)
        import build_study_flow
        build_study_flow.main()
    except Exception as e:
        print(f'흐름 데이터 만들기 실패: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
