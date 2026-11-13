"""
DART 정기보고서 XBRL(fnlttXbrl.xml 압축) → 비용의 성격별 분류 · 손익 핵심 항목 사실(fact) 목록 (네트워크·DB 없음)

- 비용의 성격별 분류: 표시 링크(pre)에서 정의가 '비용의 성격별 분류'인 역할(D8343xx)의 항목을, '[항목]'(LineItems) 다음부터
  합계 'ifrs-full_ExpenseByNature' 까지 순서대로 읽는다(그 뒤의 종업원급여 내역 같은 딸린 표는 빼서 두 번 세지 않는다).
  계산 링크가 없는 회사가 많아 표시 순서를 쓰고, 합계와 줄의 합이 맞는지는 build 쪽에서 본다.
- 손익: 매출·매출원가·매출총이익·판관비·영업이익·당기순이익 (다른 축이 붙지 않은 값만 — 부문·지역별은 빼고)
- 연결(ConsolidatedMember)/별도(SeparateMember) 구분을 basis 'C'/'S' 로, 축이 없으면 'X'.
- 금액은 억원. 기간은 (시작, 끝) — 분기보고서는 대개 연초부터 누적이라 분기 값은 build 에서 뺀다.
- 부문: 매출·영업이익에 부문/지역/제품 축이 붙은 사실 → segs (보기 seg|geo|prod). 회사마다 축 쓰는 법이 달라 seg_class 가 정리한다.
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

# ---- 부문·제품·지역별 매출/영업이익 (주석 XBRL) ----
SEG_ITEMS = {'ifrs-full_Revenue': 'rev', 'ifrs-full_RevenueFromContractsWithCustomers': 'rev', 'dart_OperatingIncomeLoss': 'op',
             'ifrs-full_ProfitLossFromOperatingActivities': 'op'}
AX_SEG, AX_GEO, AX_PROD, AX_CONS = ('ifrs-full:SegmentsAxis', 'ifrs-full:GeographicalAreasAxis', 'ifrs-full:ProductsAndServicesAxis',
                                    'ifrs-full:SegmentConsolidationItemsAxis')
VIEW = {AX_SEG: 'seg', AX_GEO: 'geo', AX_PROD: 'prod'}
M_OPSEG = 'ifrs-full:OperatingSegmentsMember'                     # 영업부문 (조정 전 부문 값이라는 표시)
M_ADJ = {'ifrs-full:MaterialReconcilingItemsMember', 'ifrs-full:EliminationOfIntersegmentAmountsMember', 'ifrs-full:UnallocatedAmountsMember'}
M_TOTAL = {'ifrs-full:SegmentsMember', 'ifrs-full:GeographicalAreasMember', 'ifrs-full:ProductsAndServicesMember',
           'ifrs-full:ReportableSegmentsMember', 'ifrs-full:EntitysTotalForSegmentConsolidationItemsMember'}   # 축 전체 합 — 줄로 안 쓴다
RENAME = {'ifrs-full:CountryOfDomicileMember': '국내', 'ifrs-full:ForeignCountriesMember': '해외', 'ifrs-full:AllOtherSegmentsMember': '기타 부문'}


def seg_class(extra):
    """연결·별도 말고 붙은 축 [(축, 구성요소)…] → (보기 seg|geo|prod, 구성요소) 또는 None.
    - 부문 축 하나(또는 '영업부문' + 축 하나): 그 구성요소. '영업부문'이 같이 붙으면 지역·제품 축이어도 부문 보기(지역이 곧 부문인 회사)
    - 조정 축에 회사 고유 구성요소가 직접 달린 꼴(제조부문·도소매부문): 부문 보기
    - 조정·제거·미배분: 부문 보기의 '조정'"""
    cons = [m for a, m in extra if a == AX_CONS]
    rest = [(a, m) for a, m in extra if a != AX_CONS]
    if len(cons) > 1 or len(rest) > 1:
        return None
    c = cons[0] if cons else None
    if not rest:
        if c is None or c == M_OPSEG or c in M_TOTAL:
            return None
        return ('seg', '__adj__' if c in M_ADJ else c)
    axis, m = rest[0]
    if axis not in VIEW or m in M_TOTAL or m in M_ADJ or (c is not None and c != M_OPSEG):
        return None
    # '영업부문' + 지역/제품 축: 지역이 곧 부문인 회사(삼양식품)일 수도, 부문 축이 따로 있는데 지역에도 표시를 붙인 회사(삼성전자)일 수도 있다
    # → 일단 'geo*'/'prod*' 로 두고 settle_views 가 그 보고서에 진짜 부문이 있는지 보고 정한다
    return (VIEW[axis] + '*' if c == M_OPSEG and axis != AX_SEG else VIEW[axis], m)


def settle_views(segs: dict) -> dict:
    """{(보기, 항목, 이름, 분류, basis, 시작, 끝): 값} 의 'geo*'·'prod*' 를 정한다: 그 basis 에 부문 보기(seg)가 없으면 그것이 부문 보기
    (지역이 곧 부문인 회사), 있으면 지역·제품 보기. 분류 앞에 'x|' 를 붙여 표시 없는 값(외부 고객 매출)과 다른 벌로 둔다 —
    두 표는 줄 구성이 달라(국내/한국, 미국/미주) 섞으면 같은 매출을 두 번 센다. 어느 벌을 쓸지는 build 가 전체 매출과 맞춰 보고 고른다"""
    has_seg = {k[4] for k in segs if k[0] == 'seg' and k[2] != '조정'}
    out = {}
    for (view, item, name, grp, b, st, en), v in segs.items():
        if view.endswith('*'):
            view, grp = (view[:-1] if b in has_seg else 'seg'), 'x|' + grp
        out[(view, item, name, grp, b, st, en)] = v
    return out


def member_children(def_root) -> Dict[str, set]:
    """정의 링크 → ({구성요소: 그 아래 모든 구성요소}, {구성요소: 그 구성요소가 나오는 주석 표 코드 중 가장 앞의 것}) ('prefix:Name' 꼴).
    표 코드(D871100 영업부문, D831150 수익 …)는 회사·시점이 달라도 같아서, 같은 축 아래 분류가 여러 벌일 때 벌을 가르는 데 쓴다"""
    kids, parent = {}, {}
    q = lambda href: href.split('#')[1].replace('_', ':', 1)
    for lk in def_root.iter(LINK + 'definitionLink'):
        locs = {x.get(XL + 'label'): q(x.get(XL + 'href')) for x in lk.findall(LINK + 'loc')}
        rm = re.search(r'role-(\w+)$', lk.get(XL + 'role') or '')
        code = re.sub(r'[a-z]$', '', rm.group(1)) if rm else ''
        for m in locs.values():
            if m.endswith('Member') and (m not in parent or code < parent[m]):
                parent[m] = code
        for a in lk.findall(LINK + 'definitionArc'):
            if (a.get(XL + 'arcrole') or '').endswith('domain-member'):
                f, t = locs.get(a.get(XL + 'from')), locs.get(a.get(XL + 'to'))
                if f and t and f.endswith('Member') and t.endswith('Member'):
                    kids.setdefault(f, set()).add(t)
    out = {}

    def below(m, seen):
        for c in kids.get(m, ()):
            if c not in seen:
                seen.add(c)
                below(c, seen)
        return seen
    for m in kids:
        out[m] = below(m, set())
    return out, parent


def leaves_only(raw: dict, kids: Dict[str, set]) -> dict:
    """{(보기, 항목, 구성요소, basis, 시작, 끝): 값} 에서, 같은 칸에 자기 아래 구성요소의 값이 있는 상위 구성요소를 뺀다 (해외 = 미국 + 중국 …)"""
    by = {}
    for (view, item, mem, b, st, en) in raw:
        by.setdefault((view, item, b, st, en), set()).add(mem)
    return {k: v for k, v in raw.items() if not (kids.get(k[2], set()) & by[(k[0], k[1], k[3], k[4], k[5])])}


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
    kids, parent = member_children(ET.fromstring(z.read(get('_def.xml')))) if get('_def.xml') else ({}, {})

    ctx, sctx = {}, {}
    for c in inst.iter(XI + 'context'):
        p = c.find(XI + 'period')
        st = p.findtext(XI + 'startDate')
        if not st:
            continue
        pairs = [(m.get('dimension'), m.text) for m in c.iter(XD + 'explicitMember')]
        dims = {m for _, m in pairs}
        basis = 'C' if 'ifrs-full:ConsolidatedMember' in dims else 'S' if 'ifrs-full:SeparateMember' in dims else 'X'
        if dims <= OK_DIMS:
            ctx[c.get('id')] = (basis, st, p.findtext(XI + 'endDate'))
            continue
        sc = seg_class([(a, m) for a, m in pairs if m not in OK_DIMS])
        if sc:
            sctx[c.get('id')] = (basis, st, p.findtext(XI + 'endDate'), *sc)
    facts, segs = {}, {}
    for el in inst:
        if not isinstance(el.tag, str) or '}' not in el.tag:
            continue
        ns, local = el.tag[1:].split('}')
        prefix = 'ifrs-full' if '/ifrs-full' in ns else 'dart' if ns.rstrip('/').endswith('/dart') else None
        if prefix is None:
            m = re.search(r'(entity\d+)', ns)
            prefix = m.group(1) if m else ns.rsplit('/', 1)[-1]
        item = f'{prefix}_{local}'
        cid = el.get('contextRef')
        if not (el.text or '').strip():
            continue
        if item in SEG_ITEMS and cid in sctx:
            try:
                b, st, en, view, mem = sctx[cid]
                segs[(view, SEG_ITEMS[item], mem, b, st, en)] = float(el.text) / 1e8
            except ValueError:
                pass
            continue
        if item not in want or cid not in ctx:
            continue
        try:
            v = float(el.text) / 1e8
        except ValueError:
            continue
        b, st, en = ctx[cid]
        facts[(item, b, st, en)] = v
    name = lambda mem: '조정' if mem == '__adj__' else RENAME.get(mem) or re.sub(
        r'\s*\[구성요소\]\s*$', '', labels.get(mem.replace(':', '_'), mem.split(':')[-1])).strip()
    # 분류 = 그 구성요소가 속한 주석 표 코드 (같은 축 아래 분류가 두 벌인 회사: 상품·제품·가맹점 / 재화의 판매·용역의 제공)
    grp = lambda mem: '' if mem == '__adj__' else parent.get(mem, '')
    segs = {(view, item, name(mem), grp(mem), b, st, en): v for (view, item, mem, b, st, en), v in leaves_only(segs, kids).items()}
    return {'facts': [(*k, v) for k, v in facts.items()], 'labels': {k: labels.get(k, k) for k in want},
            'nature': nature, 'segs': [(*k, v) for k, v in settle_views(segs).items()]}      # segs: (보기, rev|op, 이름, 분류, basis, 시작, 끝, 억원)
