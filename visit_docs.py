"""
증권사 자료(콥데이·NDR 기업별 노트 PDF) → 종목별 노트 → 탐방 탭

텔레그램 탐방 글(collect_visits.py) 말고, 받은 PDF 를 글로 풀어 회사별로 나눠 탐방 탭에 같이 싣는다.
build_visits.py 가 visit_docs/*.json 을 읽어 텔레그램 글과 같은 종목 카드에 넣는다(출처 = 자료 이름).

- 저장: visit_docs/<자료 id>.json (gitignore — 증권사 자료 원문이라 공개 저장소에 올리지 않는다), 원본 PDF 는 visit_docs/src/.
  공개 사이트에는 제목·요약만 가고(build_visits.public_view), 원문은 이 컴퓨터와 암호 건 전체판에만 있다.
- 글 뽑기: PyMuPDF. 이 PDF(워드 변환)는 한글·영문 글꼴이 바뀌는 자리에 가짜 공백이 생겨('SK 하이닉스', '’27 년')
  TEXT_INHIBIT_SPACES 로 뽑는다. 줄바꿈은 줄 끝이 오른쪽 여백까지 찬 줄만 다음 줄과 잇는다(머리 기호로 시작하는 줄은 새 줄).
  표는 칸별로 읽어 '칸 | 칸 | 칸' 줄로 바꾼다.
- 회사 나누기: 목차의 회사 이름 줄 바로 다음 줄이 'iM증권 …(애널리스트)'인 자리가 회사의 시작이다.
- 요약: 사람이(Claude 가) 원문을 읽고 두세 문장으로 쓴다. 가이던스·수주·증설·일정·리스크를 숫자와 함께.

  python3 visit_docs.py import 파일.pdf --id imcd261120 --date 2026-11-20 --source "iM증권 Corporate Day"
  python3 visit_docs.py list                         # 자료와 회사, 종목 코드, 요약 유무
  python3 visit_docs.py show imcd261120 3            # 3번째 회사 원문
  python3 visit_docs.py sum imcd261120 3 "요약"       # 요약 저장
  python3 visit_docs.py code imcd261120 3 011070     # 종목 코드 고치기 (자동 매칭이 틀렸을 때)
  python3 visit_docs.py fix imcd261120 12 "39월" "3~9월" "원본에서 물결표 빠짐"   # 원본 오탈자 바로잡기 (내역이 남는다)
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'visit_docs'
MIN_SUM, MAX_SUM = 20, 400

# 줄 머리 기호: 이것으로 시작하는 줄은 앞줄에 잇지 않는다
_HEAD = re.compile(r'^\s*(?:[\-–—•·*▶►■□●○◆◇※①-⑳]|Q\d*\s*[.:)]|A\s*[.:)]|Q\s|\d{1,2}[.)]\s|\(\d{1,2}\)|<[^>]{1,20}>|\[[^\]]{1,30}\])')
_ANALYST = re.compile(r'^iM\s*증권\s*(.+?)\s*\(?(\d{4}-\d{4})\)?\s*$')


# ---------- 순수 함수 (tests/test_visit_docs.py) ----------

def join_lines(lines: List[Dict], right: float, hard: float = 40, soft: float = 62) -> List[str]:
    """
    lines: [{'t': 글, 'x1': 줄 오른쪽 끝, 'tbl': 표 줄, 'hd': 큰 글씨 제목}] (페이지를 넘어 이어진 순서).
    한글 워드 줄바꿈은 낱말 단위라 이어지는 줄도 오른쪽이 한 낱말만큼 빈다. 그래서
      - 오른쪽 여백(right)까지 hard 안쪽으로 찬 줄 → 다음 줄과 잇는다
      - soft 안쪽이면 문장이 끝나지 않았을 때(마침표·물음표로 끝나지 않을 때)만 잇는다
      - 다음 줄이 머리 기호(-, Q., 1., <…>, […])로 시작하거나, 표·제목 줄이거나, 앞줄이 물음표로 끝나면 잇지 않는다
      - 굵은 글씨('b0' 줄 첫머리가 굵음, 'ball' 줄 전체가 굵음): 굵게 시작하는 줄은 새 문단(소제목·문단 첫 문장).
        다만 앞줄 전체가 굵으면 두 줄로 넘어간 굵은 문장이라 위 규칙대로 잇는다
    """
    out, prev = [], None
    for ln in lines:
        t = ln['t'].strip()
        if not t:
            prev = None
            continue
        join = False
        bold_ok = not (ln.get('b0') and not (prev or {}).get('ball'))    # 굵게 시작하는 줄 = 새 문단 (앞줄도 굵으면 이어지는 굵은 문장)
        if out and prev is not None and not ln.get('tbl') and not ln.get('hd') and not _HEAD.match(t) and bold_ok:
            if not (prev.get('tbl') or prev.get('hd')):
                gap, last = right - prev['x1'], out[-1].rstrip()
                ends = last.endswith(('.', '?', '다', ':'))
                join = not last.endswith('?') and (gap <= hard or (gap <= soft and not ends))
        if join:
            out[-1] = out[-1].rstrip() + ' ' + t
        else:
            out.append(t)
        prev = ln
    return out


def parse_analyst(line: str) -> Optional[Dict]:
    """'iM증권 고의영 반도체/전기전자 (2122-9179)' → {'who': '고의영', 'sector': '반도체/전기전자'} (순서가 바뀌어도)"""
    m = _ANALYST.match(line.strip())
    if not m:
        return None
    toks = m.group(1).replace('(', ' ').split()
    sector = ' '.join(t for t in toks if '/' in t)
    who = ' '.join(t for t in toks if '/' not in t)
    # '정원석(2122-9203)' 처럼 붙어 있던 경우
    return {'who': who.strip(), 'sector': sector.strip()}


def toc_names(first_page: str) -> List[str]:
    """목차 줄 '01  삼성전자 ......' → ['삼성전자', …]"""
    out = []
    for ln in first_page.splitlines():
        m = re.match(r'^\s*(\d{1,2})\s+(.+?)\s*\.{3,}', ln)
        if m:
            out.append(m.group(2).strip())
    return out


def split_companies(lines: List[str], names: List[str]) -> List[Dict]:
    """이어 붙인 줄 → 회사별 [{name, who, sector, lines}]. 회사 이름 줄 다음 줄이 애널리스트 줄인 자리에서 끊는다."""
    keys = {re.sub(r'\s', '', n): n for n in names}
    out, cur = [], None
    i = 0
    while i < len(lines):
        ln = lines[i]
        nm = keys.get(re.sub(r'\s', '', ln))
        an = parse_analyst(lines[i + 1]) if nm and i + 1 < len(lines) else None
        if nm and an:
            cur = {'name': nm, **an, 'lines': []}
            out.append(cur)
            i += 2
            continue
        if cur is not None:
            cur['lines'].append(ln)
        i += 1
    return out


def apply_fixes(text: str, fixes: List[Dict]) -> str:
    """원본 PDF 자체의 오탈자 바로잡기 [{'from','to','why'}]. 자료 파일에 내역을 남겨 다시 뽑아도(import) 같은 결과가 나온다."""
    for f in fixes:
        text = text.replace(f['from'], f['to'])
    return text


def norm_name(s: str) -> str:
    return re.sub(r'[\s()㈜]', '', s).upper()


def match_code(name: str, names: Dict[str, str], alias: Dict[str, str] = None) -> Optional[str]:
    """회사 이름 → 종목 코드. 이름표(names: 이름 → 코드)에서 공백·괄호·대소문자 무시하고 찾고, 없으면 별칭표."""
    idx = {norm_name(n): c for n, c in names.items()}
    return idx.get(norm_name(name)) or (alias or {}).get(name)


# 증권사 자료의 표기와 거래소 종목명이 다른 회사 (자료 표기 → 코드)
ALIAS = {
    'SM엔터테인먼트': '041510',     # 에스엠
    'YG엔터테인먼트': '122870',     # 와이지엔터테인먼트
    'LIG D&A': '079550',          # LIG넥스원 (2026 사명 변경 전후 표기)
    '삼성E&A': '028050',
}


def notes(docs: List[Dict], key_lines) -> List[Dict]:
    """탐방 탭에 넣을 글: 회사마다 하나. build_visits.build 가 종목 카드에 텔레그램 글과 함께 넣는다.
    'pub': True 라 공개판에는 제목·요약만 가고(public_view), 'src' 로 자료 글임을 표시한다."""
    out = []
    for doc in docs:
        for c in doc['cos']:
            who = ' '.join(x for x in (c.get('who'), c.get('sector')) if x)
            out.append({
                'id': f"doc:{doc['id']}:{c['no']}", 'd': doc['date'], 'tm': '', 'code': c.get('code'), 'name': c['name'],
                't': f"{doc['source']} · {c['name']}" + (f" ({who})" if who else ''),
                'rooms': [doc['source']], 'rp': [doc['source']], 'k': 'note', 'dm': False, 'pub': True,
                'fwd': None, 'link': None, 'src': 'doc', 'file': doc.get('file'),
                'lines': [ln for ln in key_lines(c['name'] + '\n' + c['text']) if not ln.rstrip().endswith('?')],   # 질문 줄은 빼고 답만
                'x': c['text'], 'sum': c.get('sum'), 'also': [],
            })
    return out


# ---------- PDF ----------

def _fitz():
    try:
        import pymupdf as f
    except ImportError:
        import fitz as f
    return f


def pdf_lines(path: Path) -> Dict:
    """PDF → {'toc': 첫 쪽 글, 'lines': [{'t','x1','page','tbl'}], 'right': 오른쪽 여백 x}"""
    f = _fitz()
    flags = f.TEXT_PRESERVE_LIGATURES | f.TEXT_PRESERVE_WHITESPACE | f.TEXT_MEDIABOX_CLIP | f.TEXT_INHIBIT_SPACES
    doc = f.open(str(path))
    toc = doc[0].get_text('text', flags=flags)
    out, rights, sizes = [], [], []
    for pno in range(1, len(doc)):
        page = doc[pno]
        try:
            tabs = [t for t in page.find_tables().tables if t.row_count >= 2]
        except Exception:
            tabs = []
        boxes = [f.Rect(t.bbox) for t in tabs]
        items = []
        d = page.get_text('dict', flags=flags)
        h = page.rect.height
        for b in d['blocks']:
            for ln in b.get('lines', []):
                t = ''.join(s['text'] for s in ln['spans']).rstrip()
                r = f.Rect(ln['bbox'])
                if not t.strip():
                    continue
                if t.strip().isdigit() and (r.y0 > h - 70 or r.y1 < 70):   # 쪽 번호 (아래·위 여백)
                    continue
                if any(bx.contains(f.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)) for bx in boxes):
                    continue
                sps = [sp for sp in ln['spans'] if sp['text'].strip()]
                sz = max(sp['size'] for sp in sps)
                bold = [bool(sp['flags'] & 16) or 'Bold' in sp['font'] for sp in sps]
                items.append((r.y0, {'t': t, 'x1': r.x1, 'page': pno + 1, 'sz': round(sz, 1),
                                     'b0': bold[0], 'ball': all(bold)}))
                rights.append(r.x1)
                sizes.append(round(sz, 1))
        for t, bx in zip(tabs, boxes):
            for row_t in table_rows(page, t, flags):
                items.append((bx.y0 + 0.01 * len(items), {'t': row_t, 'x1': 0, 'page': pno + 1, 'tbl': True}))
        items.sort(key=lambda x: x[0])
        out.extend(it for _, it in items)
    rights.sort()
    right = rights[int(len(rights) * 0.97)] if rights else 520
    body = max(set(sizes), key=sizes.count) if sizes else 0
    for it in out:                                   # 본문보다 1.5pt 넘게 큰 글씨 = 회사 이름 같은 제목 줄
        if it.get('sz', 0) > body + 1.5:
            it['hd'] = True
    return {'toc': toc, 'lines': out, 'right': right, 'pages': len(doc)}


def table_rows(page, tab, flags) -> List[str]:
    """
    표 → ['[표] 머리 | 머리', '칸 | 칸', …]. 칸 글은 줄바꿈을 붙여 한 줄로.
    워드 표의 세로 병합 칸(제품 이름 등)은 PyMuPDF 가 '앞 줄 안에 들어 있는 줄'로 따로 내놓는다.
    그런 줄은 앞 줄에 합치고, 칸은 왼쪽부터 놓는다.
    """
    logical = []                      # [{'y0','y1','cells': [(x0, y0, 글)]}]
    for row in tab.rows:
        y0, y1 = row.bbox[1], row.bbox[3]
        cells = []
        for c in row.cells:
            if c is None:
                continue
            t = page.get_text('text', clip=c, flags=flags)
            t = ' '.join(x.strip() for x in t.splitlines() if x.strip())
            if t:
                cells.append((round(c[0]), c[1], t))
        cur = logical[-1] if logical else None
        if cur and y0 >= cur['y0'] - 1 and y1 <= cur['y1'] + 1:
            cur['cells'].extend(cells)
        elif cells:
            logical.append({'y0': y0, 'y1': y1, 'cells': cells})
        else:
            logical.append({'y0': y0, 'y1': y1, 'cells': []})
    rows = []
    for r in logical:
        cols = {}                         # 같은 열(왼쪽 x)에 칸이 여럿이면 위에서부터 이어 쓴다
        for x0, y0, t in sorted(r['cells']):
            cols.setdefault(x0, []).append(t)
        if cols:
            rows.append(' | '.join(' '.join(v) for _, v in sorted(cols.items())))
    if rows:
        rows[0] = '[표] ' + rows[0]
    return rows


# ---------- 저장 ----------

def load_all() -> List[Dict]:
    if not DIR.exists():
        return []
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(DIR.glob('*.json'))]


def save(doc: Dict) -> Path:
    DIR.mkdir(exist_ok=True)
    p = DIR / f"{doc['id']}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return p


def get(doc_id: str) -> Dict:
    p = DIR / f'{doc_id}.json'
    if not p.exists():
        raise SystemExit(f'자료 없음: {doc_id} (python3 visit_docs.py list)')
    return json.loads(p.read_text(encoding='utf-8'))


def names_now() -> Dict[str, str]:
    import db
    from build_visits import load_names
    return load_names(db.connect())


def do_import(pdf: Path, doc_id: str, day: str, source: str, keep: Dict = None) -> Dict:
    raw = pdf_lines(pdf)
    lines = join_lines(raw['lines'], raw['right'])
    names = toc_names(raw['toc'])
    cos = split_companies(lines, names)
    found = {re.sub(r'\s', '', c['name']) for c in cos}
    missing = [n for n in names if re.sub(r'\s', '', n) not in found]
    nm = names_now()
    keep = keep or {}
    items = []
    for i, c in enumerate(cos, 1):
        old = keep.get(c['name'], {})
        fixes = old.get('fixes', [])
        items.append({
            'no': i, 'name': c['name'], 'code': old.get('code') or match_code(c['name'], nm, ALIAS),
            'who': c['who'], 'sector': c['sector'], 'text': apply_fixes('\n'.join(c['lines']), fixes),
            'sum': old.get('sum'), 'fixes': fixes,
        })
    doc = {'id': doc_id, 'date': day, 'source': source, 'file': pdf.name, 'pages': raw['pages'],
           'toc': names, 'missing': missing, 'cos': items}
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    a = sub.add_parser('import')
    a.add_argument('pdf')
    a.add_argument('--id', required=True)
    a.add_argument('--date', required=True, help='행사 날짜 YYYY-MM-DD (탐방 탭의 날짜·당시 시총 기준)')
    a.add_argument('--source', required=True, help='탐방 탭의 방 이름 자리에 보일 출처')
    a.add_argument('--out', help='시험용: 저장 대신 이 경로에 JSON')
    sub.add_parser('list')
    s = sub.add_parser('show')
    s.add_argument('id')
    s.add_argument('no', type=int)
    s = sub.add_parser('sum')
    s.add_argument('id')
    s.add_argument('no', type=int)
    s.add_argument('text')
    s = sub.add_parser('code')
    s.add_argument('id')
    s.add_argument('no', type=int)
    s.add_argument('code')
    s = sub.add_parser('fix')
    s.add_argument('id')
    s.add_argument('no', type=int)
    s.add_argument('old')
    s.add_argument('new')
    s.add_argument('why', nargs='?', default='')
    a = ap.parse_args()

    if a.cmd == 'import':
        pdf = Path(a.pdf).expanduser()
        prev = DIR / f'{a.id}.json'
        keep = {c['name']: c for c in json.loads(prev.read_text(encoding='utf-8'))['cos']} if prev.exists() else {}
        doc = do_import(pdf, a.id, a.date, a.source, keep)
        if a.out:
            Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
        else:
            (DIR / 'src').mkdir(parents=True, exist_ok=True)
            if pdf.resolve() != (DIR / 'src' / pdf.name).resolve():
                shutil.copyfile(pdf, DIR / 'src' / pdf.name)
            save(doc)
        nocode = [c['name'] for c in doc['cos'] if not c['code']]
        print(f"{doc['id']}: 목차 {len(doc['toc'])}곳 → 회사 {len(doc['cos'])}곳"
              + (f", 못 나눈 곳 {doc['missing']}" if doc['missing'] else '')
              + (f", 종목 코드 못 찾음 {nocode}" if nocode else ''))
        return 1 if doc['missing'] else 0
    if a.cmd == 'show':
        c = get(a.id)['cos'][a.no - 1]
        print(f"{c['no']}. {c['name']} ({c['code']}) · {c['who']} {c['sector']}\n\n{c['text']}\n\n요약: {c['sum']}")
        for f in c.get('fixes', []):
            print(f"바로잡음: {f['from']} → {f['to']} ({f['why']})")
        return 0
    if a.cmd in ('sum', 'code', 'fix'):
        doc = get(a.id)
        c = doc['cos'][a.no - 1]
        if a.cmd == 'fix':
            n = c['text'].count(a.old)
            if n != 1:
                raise SystemExit(f"'{a.old}' 가 원문에 {n}번 있습니다 — 딱 한 번 나오는 글로 지정하세요")
            c.setdefault('fixes', []).append({'from': a.old, 'to': a.new, 'why': a.why})
            c['text'] = c['text'].replace(a.old, a.new)
        elif a.cmd == 'sum':
            t = ' '.join(a.text.split())
            if not MIN_SUM <= len(t) <= MAX_SUM:
                raise SystemExit(f'요약은 {MIN_SUM}~{MAX_SUM}자 (지금 {len(t)}자)')
            c['sum'] = t
        else:
            if not re.fullmatch(r'\d{6}', a.code):
                raise SystemExit('코드는 6자리')
            c['code'] = a.code
        save(doc)
        print(f"{c['name']}: 저장")
        return 0
    for doc in load_all():
        print(f"{doc['id']}  {doc['date']}  {doc['source']}  ({doc['file']}, {len(doc['cos'])}곳)")
        for c in doc['cos']:
            print(f"  {c['no']:>2}. {c['name']:<14} {c['code'] or '------'}  {c['who']:<4} {len(c['text']):>5}자  {'요약 있음' if c['sum'] else '요약 없음'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
