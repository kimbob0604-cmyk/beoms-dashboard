#!/usr/bin/env python3
"""여러 리포트에서 고른 그림을 한 '종합 문서'의 그림 목록으로 잘라 모은다 (섹터 종합 스터디용)

  python3 study_crop.py --doc energy-2027              # study_src/<doc>/crops.json → 그림 잘라 figures.json
  python3 study_crop.py --doc energy-2027 --sheet      # 검수용 접촉 시트

crops.json 형식:
  {"<key>": {"pdf": "rg-14636", "page": 12, "box": [x0, y0, x1, y1], "title": "…", "part": "DB증권",
             "kind": "fig"|"tbl", "no": "도표 7"}, …}
  - box 는 쪽 크기 대비 0~1 비율(왼쪽 위 기준). 생략하면 쪽 전체.
  - part 는 화면 그림 제목 앞 [ ] 에 붙는 출처 하우스, no 는 원문 번호(없으면 "").
- 같은 내용의 그림이 여러 리포트에 있으면 하나만 고른다(고르는 일은 카드 작성 단계에서).
- 렌더: 쪽 영역을 220dpi 로 그리고 흰 여백을 잘라 -hd.png, 폭 900px 판을 .png 로. 원본 PDF 는 study_src/pdf(커밋 안 함).
"""
import argparse
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'study_src'
OUT = ROOT / 'public' / 'data' / 'study' / 'img'


def trim(im, pad=12):
    bg = Image.new('RGB', im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).convert('L').point(lambda v: 255 if v > 18 else 0).getbbox()
    if not box:
        return im
    return im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height)))


def render(doc, key, c, cache):
    pdf = c['pdf']
    if pdf not in cache:
        cache[pdf] = pymupdf.open(SRC / 'pdf' / f'{pdf}.pdf')
    page = cache[pdf][c['page'] - 1]
    W, H = page.rect.width, page.rect.height
    x0, y0, x1, y1 = c.get('box') or [0, 0, 1, 1]
    clip = pymupdf.Rect(x0 * W, y0 * H, x1 * W, y1 * H)
    pix = page.get_pixmap(dpi=220, clip=clip)
    im = trim(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
    out = OUT / doc
    out.mkdir(parents=True, exist_ok=True)
    hd = im if im.width <= 1800 else im.resize((1800, round(im.height * 1800 / im.width)), Image.LANCZOS)
    hd.save(out / f'{key}-hd.png', optimize=True)
    sm = im.resize((900, round(im.height * 900 / im.width)), Image.LANCZOS) if im.width > 900 else im
    sm.filter(ImageFilter.UnsharpMask(radius=1, percent=40, threshold=2)).save(out / f'{key}.png', optimize=True)
    return {'img': f'data/study/img/{doc}/{key}.png', 'w': sm.width, 'h': sm.height,
            'hd': f'data/study/img/{doc}/{key}-hd.png', 'hd_w': hd.width, 'hd_h': hd.height}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc', required=True)
    ap.add_argument('--sheet', action='store_true')
    ap.add_argument('--only')
    a = ap.parse_args()
    d = SRC / a.doc
    crops = json.loads((d / 'crops.json').read_text(encoding='utf-8'))
    if a.sheet:
        return sheet(a.doc)
    only = set(a.only.split(',')) if a.only else None
    old = {x['key']: x for x in json.loads((d / 'figures.json').read_text(encoding='utf-8'))} if (d / 'figures.json').exists() else {}
    cache, items = {}, []
    for key, c in crops.items():
        if key.startswith('_'):
            continue
        it = {'key': key, 'kind': c.get('kind', 'fig'), 'no': c.get('no', ''), 'title': c['title'], 'part': c.get('part', ''),
              'page': c['page'], 'pdf': c['pdf'], 'source': c.get('source', ''), 'has_source': bool(c.get('source'))}
        if only and key not in only and key in old:
            it.update({k: old[key][k] for k in ('img', 'w', 'h', 'hd', 'hd_w', 'hd_h') if k in old[key]})
        else:
            it.update(render(a.doc, key, c, cache))
        items.append(it)
    (d / 'figures.json').write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{a.doc}: 그림 {len(items)}개')


def sheet(doc):
    figs = json.loads((SRC / doc / 'figures.json').read_text(encoding='utf-8'))
    try:
        font = ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc', 20)
    except OSError:
        font = ImageFont.load_default()
    cw, ch, cols, rows = 420, 330, 6, 4
    per = cols * rows
    for s in range(0, len(figs), per):
        sh = Image.new('RGB', (cw * cols, ch * rows), (235, 235, 235))
        dr = ImageDraw.Draw(sh)
        for i, f in enumerate(figs[s:s + per]):
            x, y = (i % cols) * cw, (i // cols) * ch
            im = Image.open(ROOT / 'public' / f['img']).convert('RGB')
            im.thumbnail((cw - 16, ch - 44))
            sh.paste(im, (x + 8, y + 36))
            dr.text((x + 8, y + 6), f'{f["key"]} {f["pdf"]} p.{f["page"]}', fill=(0, 0, 0), font=font)
        p = SRC / doc / f'sheet-{s // per + 1:02d}.jpg'
        sh.save(p, quality=82)
        print(p)


if __name__ == '__main__':
    raise SystemExit(main())
