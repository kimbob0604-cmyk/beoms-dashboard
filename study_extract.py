"""
Beom's Study: 리포트·책 PDF → 그림·표 잘라내기 + 쪽별 본문

  python3 study_extract.py <pdf> --doc hmsec-onc-vol1 [--offset 2] [--dpi 200]

- 그림: `<그림N> 제목` 캡션부터 그 아래 첫 `자료:` 줄까지를 잘라 PNG 로 렌더한다.
  증권사 리포트의 차트는 대부분 벡터 도형이라 '이미지 추출'로는 안 나온다.
  같은 높이에 캡션이 둘 이상이면(좌우 2단) 다음 캡션 왼쪽 끝까지를 한 칸으로 본다.
- 표: `<표N>` 도 같은 방식으로 영역을 잡고, PyMuPDF find_tables() 로 행·열을 뽑는다(실패하면 이미지만).
- 쪽번호: PDF 쪽 - offset = 원문에 찍힌 쪽번호 (현대차증권 고형암편은 표지·목차 2쪽이라 offset 2).

결과
  study_src/{doc}/pages.json    쪽별 본문(카드 작성용, 공개 안 함)
  study_src/{doc}/figures.json  그림·표 목록(번호·제목·쪽·영역·표 데이터)
  public/data/study/img/{doc}/fig-007.png, tbl-003.png
마지막에 번호 빠짐·중복을 검사해 출력한다.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pymupdf

try:
    from PIL import Image, ImageChops, ImageFilter
except ImportError:      # 정리본(-hd) 만들 때만 필요
    Image = None

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'study_src'
IMG = ROOT / 'public' / 'data' / 'study' / 'img'

CAP = re.compile(r'^\s*<\s*(그림|표)\s*(\d+)\s*>\s*(.*)')
SOURCE = re.compile(r'^\s*자료\s*[:：]')
KIND = {'그림': 'fig', '표': 'tbl'}


def lines_of(page):
    """줄 단위 (x0, y0, x1, y1, text). 블록이 캡션과 본문을 한데 묶는 경우가 있어 줄로 쪼갠다."""
    out = []
    for b in page.get_text('dict')['blocks']:
        for ln in b.get('lines', []):
            t = ''.join(s['text'] for s in ln['spans']).strip()
            if t:
                x0, y0, x1, y1 = ln['bbox']
                out.append((x0, y0, x1, y1, t))
    out.sort(key=lambda r: (round(r[1]), r[0]))
    return out


def find_regions(page):
    lines = lines_of(page)
    W, H = page.rect.width, page.rect.height
    caps = [(l, CAP.match(l[4])) for l in lines]
    caps = [(l, m) for l, m in caps if m]
    regions = []
    for l, m in caps:
        x0, y0, x1, y1, _ = l
        # 같은 줄(±6pt)에서 오른쪽에 있는 다음 캡션 → 이 칸의 오른쪽 끝
        right = [o[0] for o, _ in caps if o is not l and abs(o[1] - y0) < 6 and o[0] > x0 + 20]
        rx = min(right) - 6 if right else W - 30
        lx = x0 - 6
        # 왼쪽 칸에 있는 다른 캡션이 같은 줄이면, 그 칸의 끝이 내 시작
        # 아래쪽 끝: 칸 안의 첫 '자료:' 줄, 없으면 칸 안 다음 캡션 위, 그래도 없으면 쪽 아래 여백
        src = [o for o in lines if o[1] > y1 - 1 and SOURCE.match(o[4]) and lx - 4 <= o[0] < rx]
        nxt = [o for o, _ in caps if o[1] > y1 + 2 and lx - 4 <= o[0] < rx]
        bottom = None
        if src:
            s = min(src, key=lambda o: o[1])
            if not nxt or s[1] < min(o[1] for o in nxt):
                bottom = s[3] + 3
        if bottom is None:
            bottom = (min(o[1] for o in nxt) - 4) if nxt else H - 50
        # 캡션 줄이 칸보다 넓을 수 있다(그림 자체가 캡션보다 넓은 경우) → 칸 안 도형 범위로 넓힌다
        rect = pymupdf.Rect(lx, y0 - 4, rx, bottom)
        draw = [d['rect'] for d in page.get_drawings() if d['rect'].intersects(rect) and d['rect'].width < W * 0.95]
        imgs = [page.get_image_bbox(i) for i in page.get_images(full=True)]
        for r in draw + [r for r in imgs if r.is_valid and r.intersects(rect)]:
            if r.y0 >= rect.y0 - 2 and r.y1 <= bottom + 2:
                rect.x0 = max(min(rect.x0, r.x0 - 2), 20)
                rect.x1 = min(max(rect.x1, r.x1 + 2), W - 20) if not right else rect.x1
        title = m.group(3).strip()
        regions.append({
            'kind': KIND[m.group(1)], 'no': int(m.group(2)), 'title': title,
            'rect': [round(v, 1) for v in rect], 'has_source': bool(src),
            'source': (min(src, key=lambda o: o[1])[4].strip() if src else ''),
        })
    return regions


def table_rows(page, rect):
    """표 영역의 행·열. find_tables 가 준 칸 경계로 글자를 다시 읽는다(extract() 는 쉼표·소수점 위치가 틀어진다).
    바깥쪽 세로선이 없는 표는 맨 왼쪽·오른쪽 열을 놓치므로 영역 안에 남은 글자가 있으면 열을 하나 더 붙인다.
    한 영역에 표가 여럿(중간에 끊긴 표)이면 위에서부터 이어 붙인다."""
    region = pymupdf.Rect(rect)
    try:
        tabs = page.find_tables(clip=region).tables
        # clip 을 줘도 영역에 걸친 다른 표를 통째로 주는 경우가 있다 → 절반 이상 영역 안에 있는 표만
        tabs = sorted((t for t in tabs if (pymupdf.Rect(t.bbox) & region).get_area() > 0.5 * pymupdf.Rect(t.bbox).get_area()),
                      key=lambda t: t.bbox[1])
    except Exception:
        return None
    if not tabs:
        return None
    read = lambda r: ' '.join(page.get_text('text', clip=pymupdf.Rect(r)).split())
    words = page.get_text('words', clip=region)
    out = []
    for t in tabs:
        tx0, ty0, tx1, ty1 = t.bbox
        left = any(w[2] <= tx0 + 1 and w[1] >= ty0 - 1 and w[3] <= ty1 + 1 for w in words)
        right = any(w[0] >= tx1 - 1 and w[1] >= ty0 - 1 and w[3] <= ty1 + 1 for w in words)
        for row in t.rows:
            y0, y1 = row.bbox[1], row.bbox[3]
            cells = [read(c) if c else '' for c in row.cells]
            if left:
                cells.insert(0, read((region.x0, y0, tx0, y1)))
            if right:
                cells.append(read((tx1, y0, region.x1, y1)))
            out.append(cells)
    n = max(len(r) for r in out)
    return [r + [''] * (n - len(r)) for r in out if any(r)]


def hd_image(doc, page, rect, out):
    """그림 영역 안에 박힌 원본 이미지가 하나면 그것을 꺼내 정리본을 만든다:
    흰 여백 자르기 → 2배 확대(Lanczos) → 약한 선명화. 화면 렌더(캡션·출처 줄 포함)보다 깨끗하고 크다.
    벡터 그림이거나 이미지가 여럿이면 만들지 않는다(None)."""
    if Image is None:
        return None
    R = pymupdf.Rect(rect)
    inside = [(i[0], page.get_image_bbox(i)) for i in page.get_images(full=True)]
    inside = [(x, b) for x, b in inside if b.is_valid and (b & R).get_area() > 0.8 * b.get_area()]
    if len(inside) != 1:
        return None
    pix = pymupdf.Pixmap(doc, inside[0][0])
    if pix.n - pix.alpha >= 4:          # CMYK → RGB
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    im = Image.frombytes('RGBA' if pix.alpha else 'RGB', (pix.width, pix.height), pix.samples).convert('RGB')
    bg = Image.new('RGB', im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).convert('L').point(lambda v: 255 if v > 18 else 0).getbbox()
    if box:
        pad = 6
        im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height)))
    if im.width < 1400:
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    im.save(out, optimize=True)
    return im.size


def page_text(page):
    """머리글(INDUSTRY REPORT/COMPANY REPORT)·쪽번호·바닥글 빼고 줄을 이어 붙인 본문"""
    H = page.rect.height
    out = []
    for x0, y0, x1, y1, t in lines_of(page):
        if y0 < 45 or y1 > H - 40:
            continue
        if t in ('INDUSTRY REPORT', 'COMPANY REPORT'):
            continue
        out.append(t)
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('--doc', required=True)
    ap.add_argument('--offset', type=int, default=0, help='PDF 쪽 - offset = 원문 쪽번호')
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--part', action='append', default=[],
                    help='번호가 다시 1부터 시작하는 부분: PDF시작쪽:이름 (예: 120:voronoi → voronoi-fig-003)')
    a = ap.parse_args()
    parts = sorted((int(x.split(':')[0]), x.split(':')[1]) for x in a.part)
    part_of = lambda pno: next((n for st, n in reversed(parts) if pno >= st), '')

    doc = pymupdf.open(a.pdf)
    src_dir, img_dir = SRC / a.doc, IMG / a.doc
    src_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    pages, items = [], []
    for i, page in enumerate(doc):
        pno = i + 1
        pages.append({'pdf': pno, 'page': pno - a.offset, 'text': page_text(page)})
        for r in find_regions(page):
            pre = part_of(pno)
            key = f"{pre + '-' if pre else ''}{r['kind']}-{r['no']:03d}"
            r['part'] = pre
            pix = page.get_pixmap(dpi=a.dpi, clip=pymupdf.Rect(r['rect']))
            pix.save(img_dir / f'{key}.png')
            item = {'key': key, **r, 'pdf': pno, 'page': pno - a.offset,
                    'img': f'data/study/img/{a.doc}/{key}.png', 'w': pix.width, 'h': pix.height}
            if r['kind'] == 'tbl':
                item['rows'] = table_rows(page, r['rect'])
            else:
                hd = hd_image(doc, page, r['rect'], img_dir / f'{key}-hd.png')
                if hd:
                    item.update({'hd': f'data/study/img/{a.doc}/{key}-hd.png', 'hd_w': hd[0], 'hd_h': hd[1]})
            items.append(item)

    (src_dir / 'pages.json').write_text(json.dumps(pages, ensure_ascii=False, indent=0), encoding='utf-8')
    (src_dir / 'figures.json').write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')

    # 점검: 같은 번호가 여러 번(같은 번호를 쓰는 기업분석 부분이 뒤에 붙은 경우 등), 빠진 번호, 자료 줄 없음
    for pre in [''] + [n for _, n in parts]:
        for kind in ('fig', 'tbl'):
            nos = [it['no'] for it in items if it['kind'] == kind and it['part'] == pre]
            dup = sorted({n for n in nos if nos.count(n) > 1})
            miss = sorted(set(range(1, max(nos) + 1)) - set(nos)) if nos else []
            print(f'{pre or "본문"} {kind}: {len(nos)}개, 최대 {max(nos) if nos else 0}, 중복 {dup or "-"}, 빠짐 {miss or "-"}')
    nosrc = [it['key'] + f"(p{it['pdf']})" for it in items if not it['has_source']]
    print('자료 줄 없음:', ', '.join(nosrc) or '-')
    print('정리본(-hd) 만든 그림:', sum(1 for it in items if it.get('hd')), '개')
    notab = [it['key'] for it in items if it['kind'] == 'tbl' and not it.get('rows')]
    print('표 데이터 못 뽑음:', ', '.join(notab) or '-')
    return 0


if __name__ == '__main__':
    sys.exit(main())
