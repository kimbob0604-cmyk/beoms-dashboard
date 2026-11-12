"""
DART 정기보고서 XBRL(fnlttXbrl.xml 압축) → 비용의 성격별 분류 · 손익 핵심 항목 사실(fact) 목록 (네트워크·DB 없음)

- 비용의 성격별 분류: 표시 링크(pre)에서 정의가 '비용의 성격별 분류'인 역할(D8343xx)의 항목을, '[항목]'(LineItems) 다음부터
  합계 'ifrs-full_ExpenseByNature' 까지 순서대로 읽는다(그 뒤의 종업원급여 내역 같은 딸린 표는 빼서 두 번 세지 않는다).
  계산 링크가 없는 회사가 많아 표시 순서를 쓰고, 합계와 줄의 합이 맞는지는 build 쪽에서 본다.
- 손익: 매출·매출원가·매출총이익·판관비·영업이익·당기순이익 (다른 축이 붙지 않은 값만 — 부문·지역별은 빼고)
- 연결(ConsolidatedMember)/별도(SeparateMember) 구분을 basis 'C'/'S' 로, 축이 없으면 'X'.
- 금액은 억원. 기간은 (시작, 끝) — 분기보고서는 대개 연초부터 누적이라 분기 값은 build 에서 뺀다.
"""

import io
import re
import zipfile
from typing import Dict, List
from xml.etree import ElementTree as ET

LINK = '{http://www.xbrl.org/2003/linkbase}'
XL = '{http://www.w3.org/1999/xlink}'
XI = '{http://www.xbrl.org/2003/instance}'
XD = '{http://xbrl.org/2006/xbrldi}'

IS_ITEMS = {
    'ifrs-full_Revenue': ('rev', '매출액'),
    'ifrs-full_CostOfSales': ('cogs', '매출원가'),
    'ifrs-full_GrossProfit': ('gp', '매출총이익'),
    'dart_TotalSellingGeneralAdministrativeExpenses': ('sga', '판매비와관리비'),
    'dart_OperatingIncomeLoss': ('op', '영업이익'),
    'ifrs-full_ProfitLoss': ('np', '당기순이익'),
}
TOTAL = 'ifrs-full_ExpenseByNature'
OK_DIMS = {'dart:ReportedAmountMember', 'ifrs-full:CarryingAmountMember', 'ifrs-full:ConsolidatedMember', 'ifrs-full:SeparateMember'}


def _labels(root) -> Dict[str, str]:
    out = {}
    for lk in root.iter(LINK + 'labelLink'):
        locs = {x.get(XL + 'label'): x.get(XL + 'href').split('#')[1] for x in lk.findall(LINK + 'loc')}
        labs = {}
        for x in lk.findall(LINK + 'label'):
            if (x.get(XL + 'role') or '').endswith('/label'):
                labs[x.get(XL + 'label')] = (x.text or '').strip()
        for a in lk.findall(LINK + 'labelArc'):
            f, t = a.get(XL + 'from'), a.get(XL + 'to')
            if t in labs and f in locs:
                out.setdefault(locs[f], labs[t])
    return out


def _roles(xsd: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r'roleURI="([^"]+)"[^>]*>\s*<link:definition>([^<]*)</link:definition>', xsd)}


def nature_items(pre_root, roles: Dict[str, str]) -> List[str]:
    """비용의 성격별 분류 줄 (표시 순서, 합계 포함). 연결·별도 역할이 따로 있으면 처음 나온 순서로 합친다"""
    out = []
    for pl in pre_root.iter(LINK + 'presentationLink'):
        if '비용의 성격별' not in roles.get(pl.get(XL + 'role'), ''):
            continue
        locs = {x.get(XL + 'label'): x.get(XL + 'href').split('#')[1] for x in pl.findall(LINK + 'loc')}
        # 화살표를 따라 순서대로 (order 속성), LineItems 밑의 자식들
        kids = {}
        for a in pl.findall(LINK + 'presentationArc'):
            kids.setdefault(locs.get(a.get(XL + 'from')), []).append((float(a.get('order') or 0), locs.get(a.get(XL + 'to'))))
        line_parent = next((p for p in kids if p and p.endswith('LineItems')), None)
        if not line_parent:
            continue
        seq = []

        def walk(node):
            for _, c in sorted(kids.get(node, [])):
                seq.append(c)
                if not c.endswith(('Abstract', 'Table', 'LineItems', 'Axis', 'Member', 'Domain')):
                    walk(c)      # 줄 밑에 더 나눈 줄(예: 급여·퇴직급여)이 붙은 경우 — 자식은 뒤에서 빠진다
        walk(line_parent)
        # 합계가 있으면 합계까지만, 그리고 합계 밑에 매달린 것은 그대로 줄로
        items = [x for x in seq if not x.endswith(('Abstract', 'Table', 'LineItems', 'Axis', 'Member', 'Domain', 'TextBlock'))]
        if TOTAL in items:
            items = items[:items.index(TOTAL) + 1]
        top = {c for _, c in kids.get(line_parent, [])}
        if TOTAL in kids:   # 합계 밑에 줄을 단 회사: 합계의 자식이 줄
            top |= {c for _, c in kids[TOTAL]}
        items = [x for x in items if x in top or x == TOTAL]
        for x in items:
            if x not in out:
                out.append(x)
    return out


def parse(zbytes: bytes) -> Dict:
    """압축 → {'facts': [(item, basis, start, end, 억원)], 'labels': {item: 한글}, 'nature': [줄 순서]}"""
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    names = z.namelist()
    get = lambda suf: next((n for n in names if n.endswith(suf)), None)
    inst = ET.fromstring(z.read(get('.xbrl')))
    pre = ET.fromstring(z.read(get('_pre.xml'))) if get('_pre.xml') else None
    lab = ET.fromstring(z.read(get('_lab-ko.xml'))) if get('_lab-ko.xml') else None
    xsd = z.read(get('.xsd')).decode('utf-8', 'replace') if get('.xsd') else ''
    labels = _labels(lab) if lab is not None else {}
    nature = nature_items(pre, _roles(xsd)) if pre is not None else []
    want = set(nature) | set(IS_ITEMS)

    ctx = {}
    for c in inst.iter(XI + 'context'):
        p = c.find(XI + 'period')
        st = p.findtext(XI + 'startDate')
        if not st:
            continue
        dims = {m.text for m in c.iter(XD + 'explicitMember')}
        if not dims <= OK_DIMS:
            continue
        basis = 'C' if 'ifrs-full:ConsolidatedMember' in dims else 'S' if 'ifrs-full:SeparateMember' in dims else 'X'
        ctx[c.get('id')] = (basis, st, p.findtext(XI + 'endDate'))
    facts = {}
    for el in inst:
        if not isinstance(el.tag, str) or '}' not in el.tag:
            continue
        ns, local = el.tag[1:].split('}')
        prefix = 'ifrs-full' if '/ifrs-full' in ns else 'dart' if ns.rstrip('/').endswith('/dart') else None
        if prefix is None:
            m = re.search(r'(entity\d+)', ns)
            prefix = m.group(1) if m else ns.rsplit('/', 1)[-1]
        item = f'{prefix}_{local}'
        if item not in want or el.get('contextRef') not in ctx or not (el.text or '').strip():
            continue
        try:
            v = float(el.text) / 1e8
        except ValueError:
            continue
        b, st, en = ctx[el.get('contextRef')]
        facts[(item, b, st, en)] = v
    return {'facts': [(*k, v) for k, v in facts.items()], 'labels': {k: labels.get(k, k) for k in want},
            'nature': nature}
