#!/usr/bin/env python3
"""Study 리포트 발간일 목록(study/reports.json)을 자동으로 채운다

- Study 문서가 쓰는 리포트(그림 figures.json 의 pdf 키 + 문서 source.reports + 리포트 한 건짜리 문서 id) 중
  목록에 없는 것을 찾아, PDF 표지(앞 3쪽)에서 발간일을 읽어 추가한다. build_study.py 가 빌드 때마다 부른다.
- 표지 글자 층이 없으면 study_src/<키>/ocr/pNNN.json(OCR 결과)을 읽는다. 그래도 못 읽으면 날짜를 비우고 check 에 적는다.
- 하우스·애널리스트·제목은 텔레그램 받은 목록(study_src/pdf/rg_index.json)이나 dl_index.json 의 원래 파일 이름에서 뽑는다.
- 자동으로 넣은 줄에는 "auto": true 가 붙는다 — 표지와 다르면 손으로 고치고 auto 를 지우면 된다.

  python3 study_reports.py            # 빠진 리포트 추가
  python3 study_reports.py --check    # 추가하지 않고 빠진 것·자동 추가분만 보여 준다
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'study'
EXTRACT = ROOT / 'study_src'
PDF = EXTRACT / 'pdf'
REG = SRC / 'reports.json'
MON = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
PATS = [   # (정규식, (년, 월, 일) 뽑기) — 표지에 흔한 꼴
    (r'(20\d\d)\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', lambda m: (m[1], m[2], m[3])),
    (r'(20\d\d)\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?!\d)', lambda m: (m[1], m[2], m[3])),
    (r'(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*,?\s*(20\d\d)', lambda m: (m[3], MON[m[2].lower()[:3]], m[1])),
    (r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s*(20\d\d)', lambda m: (m[3], MON[m[1].lower()[:3]], m[2])),
]
MONTH_ONLY = r'(20\d\d)\s*\.\s*(\d{1,2})(?![\d.])|(20\d\d)\s*년\s*(\d{1,2})\s*월(?!\s*\d)'   # '2026. 11' · '2026년 11월'
OCR_BIN = ROOT / '.cache' / 'study_ocr'      # macOS Vision OCR (study_ocr.swift 를 컴파일), 없으면 처음 쓸 때 만든다


def _dates(text: str) -> list:
    out = []
    for pat, f in PATS:
        for m in re.finditer(pat, text, re.I):
            try:
                y, mo, d = (int(v) for v in f(m))
            except (ValueError, KeyError):
                continue
            if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                out.append((m.start(), f'{y}-{mo:02d}-{d:02d}'))
    return [d for _, d in sorted(out)]


def _page_texts(key: str, n: int = 3) -> list:
    import pymupdf
    doc = pymupdf.open(PDF / f'{key}.pdf')
    texts = []
    for i in range(min(n, doc.page_count)):
        t = doc[i].get_text()
        ocr = EXTRACT / key / 'ocr' / f'p{i + 1:03d}.json'
        if len(t.strip()) < 30 and ocr.exists():
            t = '\n'.join(l['t'] for l in json.loads(ocr.read_text(encoding='utf-8')).get('lines', []))
        texts.append(t)
    return texts


def _cover_ocr(key: str, dpi: int = 200) -> str:
    """표지(1쪽)를 그림으로 그려 OCR 한 글자. 표지 날짜가 그림 안에 박혀 있는 리포트가 많다"""
    import subprocess
    import pymupdf
    if not OCR_BIN.exists():
        subprocess.run(['swiftc', '-O', str(ROOT / 'study_ocr.swift'), '-o', str(OCR_BIN)], capture_output=True)
        if not OCR_BIN.exists():
            return ''
    d = ROOT / '.cache' / 'cover_ocr' / f'{key}@{dpi}'
    d.mkdir(parents=True, exist_ok=True)
    js = d / 'p001.json'
    if not js.exists():
        pymupdf.open(PDF / f'{key}.pdf')[0].get_pixmap(dpi=dpi).save(d / 'p001.jpg')
        subprocess.run([str(OCR_BIN), str(d), str(d)], capture_output=True, timeout=120)
    if not js.exists():
        return ''
    lines = json.loads(js.read_text(encoding='utf-8')).get('lines', [])
    return '\n'.join(l['t'] for l in sorted(lines, key=lambda l: (round(l['y'], 2), l['x'])))


def _month_only(text: str) -> str:
    for m in re.finditer(MONTH_ONLY, text):
        y, mo = (m[1], m[2]) if m[1] else (m[3], m[4])
        if 2000 <= int(y) <= 2100 and 1 <= int(mo) <= 12:
            return f'{int(y)}-{int(mo):02d}'
    return ''


def cover_date(key: str) -> str:
    """표지 날짜. 순서: 1쪽 글자 → 1쪽 그림 OCR → 2·3쪽 글자. 날짜가 없고 '2026. 11' 같은 월만 있으면 YYYY-MM. 못 찾으면 ''"""
    texts = _page_texts(key)
    tries = [texts[0] if texts else '', _cover_ocr(key)] + texts[1:]
    for t in tries:
        ds = _dates(t)
        if ds:
            return ds[0]
    tries.append(_cover_ocr(key, 400))   # 작은 글씨(어두운 표지 위 발간일자 등)는 해상도를 올려 한 번 더
    if _dates(tries[-1]):
        return _dates(tries[-1])[0]
    for t in tries:
        mo = _month_only(t)
        if mo:
            return mo
    return ''


def _meta_from_name(name: str) -> dict:
    """'신한투자증권_이진명,_김명주_2차전지_…pdf' · '[iM증권 고의영, 박정하]_반도체_…' → 하우스·애널리스트·제목"""
    n = re.sub(r'\.pdf$', '', name)
    m = re.match(r'\[([^\]]+)\]_?(.*)', n)
    if m:
        house, _, analyst = m[1].partition(' ')
        title = m[2].replace('_', ' ')
    else:
        bits = n.split('_')
        house, rest = bits[0], bits[1:]
        names = []
        while rest and (not names or names[-1].endswith(',')):   # '이진명,' '김명주' 처럼 쉼표로 이어진 이름
            names.append(rest.pop(0))
        analyst, title = ''.join(names), ' '.join(rest)
    house = house.replace('투자증권', '').replace('증권', '').replace('한국', '한투')
    return {'house': house, 'analyst': analyst.replace(', ', '·').replace(',', '·').strip(), 'title': title.strip()}


def meta(key: str) -> dict:
    for idx_name, k in (('rg_index.json', key[3:] if key.startswith('rg-') else None), ('dl_index.json', key)):
        p = PDF / idx_name
        if k and p.exists():
            idx = json.loads(p.read_text(encoding='utf-8'))
            if k in idx:
                return _meta_from_name(idx[k]['name'])
    return {'house': '', 'analyst': '', 'title': key}


def _post_date(key: str) -> str:
    p = PDF / 'rg_index.json'
    if key.startswith('rg-') and p.exists():
        e = json.loads(p.read_text(encoding='utf-8')).get(key[3:])
        if e and e.get('date'):
            return e['date'][:10]
    return ''


def used_keys() -> set:
    keys = set()
    for f in (SRC / 'docs').glob('*.json'):
        d = json.loads(f.read_text(encoding='utf-8'))
        figs = EXTRACT / d['id'] / 'figures.json'
        found = set()
        if figs.exists():
            found = {x['pdf'] for x in json.loads(figs.read_text(encoding='utf-8')) if isinstance(x.get('pdf'), str)}
        found |= set(d.get('source', {}).get('reports', []))
        if not found and d.get('source', {}).get('kind') != 'book' and (PDF / f'{d["id"]}.pdf').exists():
            found.add(d['id'])   # 리포트 한 건짜리 문서
        keys |= found
    return keys


def sync(write: bool = True) -> list:
    """목록에 없는 리포트를 표지에서 읽어 추가하고, 추가한 (키, 항목) 목록을 돌려준다"""
    reg = json.loads(REG.read_text(encoding='utf-8')) if REG.exists() else {'_note': ''}
    added = []
    for key in sorted(used_keys() - set(reg)):
        if not (PDF / f'{key}.pdf').exists():
            continue
        e = {**meta(key), 'date': cover_date(key), 'auto': True}
        if not e['date']:
            post = _post_date(key)
            e['date'] = post
            e['check'] = '표지에서 날짜를 못 읽어 텔레그램 올린 날짜를 넣음 — 표지 확인' if post else '표지에서 날짜를 못 읽음 — 손으로 적기'
        reg[key] = e
        added.append((key, e))
    if added and write:
        note = {k: v for k, v in reg.items() if k.startswith('_')}
        rest = dict(sorted((k, v) for k, v in reg.items() if not k.startswith('_')))
        REG.write_text(json.dumps({**note, **rest}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return added


def main():
    check = '--check' in sys.argv
    added = sync(write=not check)
    for k, e in added:
        print(f"{'빠짐' if check else '추가'} {k}: {e['date'] or '날짜 못 읽음'} {e['house']} {e['analyst']} {e['title'][:40]}")
    reg = json.loads(REG.read_text(encoding='utf-8')) if REG.exists() else {}
    auto = [k for k, v in reg.items() if isinstance(v, dict) and v.get('auto')]
    if auto:
        print(f'자동으로 넣은 줄 {len(auto)}개 (표지와 맞는지 확인 후 auto 지우기): {", ".join(auto)}')
    if not added and not auto:
        print('빠진 리포트 없음')
    return 0


if __name__ == '__main__':
    sys.exit(main())
