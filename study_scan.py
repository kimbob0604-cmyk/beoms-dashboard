#!/usr/bin/env python3
"""사진으로 찍은 책 PDF → Study 재료 (study_extract.py 의 스캔본 판)

글자 층이 없는 책 사진 PDF용. 순서:
  1) 쪽 이미지 뽑기      study_src/{doc}/pages/pNNN.jpeg   (--pdf 를 주면 새로 뽑음)
  2) OCR                  swiftc -O study_ocr.swift -o /tmp/study_ocr && /tmp/study_ocr pages ocr
                          → study_src/{doc}/ocr/pNNN.json (줄마다 글자·위치, 0~1 비율)
  3) 이 스크립트
     python3 study_scan.py --doc semi-oneday            쪽 글 + 그림·표 자르기
     python3 study_scan.py --doc semi-oneday --sheet    검수용 접촉 시트(study_src/{doc}/sheet-*.jpg)

산출물 (study_extract.py 와 같은 형식이라 build_study.py 가 그대로 읽는다):
  study_src/{doc}/pages.json     쪽별 본문 (책 쪽번호)
  study_src/{doc}/figures.json   그림·표 목록 (key, kind, no, title, page, img, hd …)
  public/data/study/img/{doc}/{key}.png, {key}-hd.png

그림 찾기: 캡션 줄 「| 그림 1-7. …」 을 OCR 에서 찾고, 그 **위쪽**을 자른다(이 책은 그림·표 모두 캡션이 아래).
  위 경계 = 캡션 위로 가장 가까운 본문 줄(왼쪽 여백에서 시작하는 문단 줄)의 아래, 또는 같은 쪽 앞 캡션의 아래.
  좌우 = 본문 여백 안에서 잉크가 있는 범위. 같은 높이에 캡션이 둘이면 가운데에서 나눈다.
정리: 쪽 전체 종이색을 2차 곡면으로 맞춰 나눔(조명 얼룩 제거) → 흰색 들어올림 → ±1.5° 기울기 보정 → 선명화.
손 보정: study_src/{doc}/crops.json  {"fig-1-10": {"pdf": 19, "box": [x0, y0, x1, y1]}, …}  (0~1 비율)
          캡션이 없는 컷(예: 요약 공정 단면)도 여기에 적으면 같은 방식으로 만든다 ("title", "kind" 함께).
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'study_src'
OUT = ROOT / 'public' / 'data' / 'study' / 'img'

# 문서별 설정: PDF 쪽 → 책 쪽 차이(구간별), 머리말·꼬리말 제거 규칙
DOCS = {
    'semi-oneday': {
        'offsets': [(1, 5, None), (6, 48, 11), (49, 137, 13), (138, 266, 16), (267, 320, 19)],
        'drop': [r'^PART\s*0\d\s', r'진짜\s*하루만에\s*이해하는\s*반도체\s*산업', r'^\d{1,3}$'],
        'renum': {(19, '1-1'): '1-11'},     # OCR 이 「그림 1-11」을 「그림 11」로 읽음
        # 캡션 OCR 오독 바로잡기 (원문 이미지와 대조함): 앞 글자 → 바꿀 글자
        'fix': [('(~ 전압', '(−) 전압'), ('() 전압', '(−) 전압'), ('( 전압', '(−) 전압'), ('PVP형', 'PNP형'),
                ('planar FET', 'Planar FET'), ('1+2=301라는', '1+2=3이라는'), ('논 리', '논리'), ('처리 하면서도', '처리하면서도'),
                ('CPUL GPU', 'CPU나 GPU'), ('채워지지 않으면 O,', '채워지지 않으면 0,'), ('1P', 'IP'), ('패키지 해', '패키지해'),
                ('깎아내고.', '깎아내고,'), ('(OASML)', '(©ASML)'), ('감광충', '감광층'), ('박막올', '박막을'),
                ('납하는', '납땜하는'), ('다이부착', '다이 부착'), ('자유전자', '자유 전자')],
        # 캡션 없는 그림 묶음: 이 쪽들에서 본문 줄 사이의 그림 덩어리를 차례로 cut-01, cut-02 … 로 자른다
        'cuts': [{'pdf': (249, 260), 'prefix': 'cut', 'part': '핵심만 쏙쏙', 'title': 'N-MOSFET 8대 공정 복습'}],
    },
}

CAP = re.compile(r'^[\s|Il1\[\(]{0,4}(그림|표)\s*(\d)\s*[-–—.]?\s*(\d{1,2})(?=[\s.,|])[.,]?\s*(.*)$')


def book_page(cfg, pdf):
    for a, b, off in cfg['offsets']:
        if a <= pdf <= b:
            return None if off is None else pdf + off
    return None


def load_ocr(doc, pdf):
    return json.loads((SRC / doc / 'ocr' / f'p{pdf:03d}.json').read_text(encoding='utf-8'))


def page_text(cfg, lines):
    keep = []
    for l in sorted(lines, key=lambda l: (round(l['y'], 3), l['x'])):
        t = l['t'].strip()
        if (l['y'] > 0.9 or l['y'] < 0.05) and any(re.search(p, t) for p in cfg['drop']):
            continue
        keep.append(t)
    return '\n'.join(keep)


def margins(lines):
    """본문 왼쪽·오른쪽 여백 (긴 줄들의 중앙값)"""
    long_ = [l for l in lines if l['w'] > 0.55]
    if len(long_) < 2:
        return 0.12, 0.90
    xs = sorted(l['x'] for l in long_)
    rs = sorted(l['x'] + l['w'] for l in long_)
    # 문단 첫 줄은 들여쓰기 되어 있으니 왼쪽은 아래쪽 1/5 값(실제 글 시작선)
    return xs[len(xs) // 5], rs[len(rs) // 2]


def body_lines(lines, ml):
    """문단 본문 줄: 왼쪽 여백 근처에서 시작하고, 길거나 바로 위·아래에 같은 여백의 긴 줄이 붙어 있는 줄"""
    cand = [l for l in lines if -0.01 < l['x'] - ml < 0.06 or (l['w'] > 0.6)]   # 들여쓴 첫 줄 포함
    out = []
    for l in cand:
        if l['w'] > 0.6:
            out.append(l)
            continue
        if l['w'] < 0.02:
            continue
        # 문장으로 끝나는 여백 줄(쪽 첫 줄 「…때문입니다.」, 문단 꼬리 「습니다.」)
        if -0.01 < l['x'] - ml < 0.06 and re.search(r'(다|요)[.。]?$', l['t'].strip()):
            out.append(l)
            continue
        # 문단 마지막 줄: 바로 위(줄 간격 안쪽)에 긴 본문 줄이 있다
        if any(o is not l and o['w'] > 0.6 and 0 < l['y'] - o['y'] < 0.05 for o in cand):
            out.append(l)
    return out


FIX = []


def captions(lines):
    caps = []
    ls = sorted(lines, key=lambda l: l['y'])
    for i, l in enumerate(ls):
        m = CAP.match(l['t'].strip())
        if not m:
            continue
        title = m.group(4).strip()   # 본문 속 「그림 1-3에서」는 숫자 뒤가 공백·마침표가 아니라 여기 안 걸린다
        # 두 줄 캡션: 바로 아래 가운데 정렬 줄
        prev = l
        for o in ls[i + 1:i + 4]:
            if 0 < o['y'] - prev['y'] < 0.03 and abs((o['x'] + o['w'] / 2) - (l['x'] + l['w'] / 2)) < 0.15 \
                    and not CAP.match(o['t'].strip()):
                title += ' ' + o['t'].strip()
                prev = o
        title = re.sub(r'[\s|Il1]+$', '', title).strip(' .')
        for a_, b_ in FIX:
            title = title.replace(a_, b_)
        kind = 'fig' if m.group(1) == '그림' else 'tbl'
        caps.append({'kind': kind, 'no': f'{m.group(2)}-{int(m.group(3))}', 'title': title, 'line': l})
    return caps


# ---------- 이미지 정리 ----------

def paper_model(img):
    """쪽 전체에서 종이색을 2차 곡면으로 맞춘 배경 (조명 얼룩 제거용)"""
    small = img.resize((img.width // 8, img.height // 8), Image.BILINEAR)
    a = np.asarray(small).astype(float)
    h, w, _ = a.shape
    lum = a.mean(2)
    sat = a.max(2) - a.min(2)
    thr = np.percentile(lum, 60)
    mask = (lum >= thr - 10) & (sat < 40)
    # 가장자리(책 테두리·그림자) 제외
    mask[:, :w // 20] = False
    mask[:, -w // 20:] = False
    yy, xx = np.mgrid[0:h, 0:w]
    X = np.stack([np.ones_like(xx), xx / w, yy / h, (xx / w) ** 2, (yy / h) ** 2, (xx / w) * (yy / h)], -1)
    A = X[mask]
    bg = np.zeros_like(a)
    for c in range(3):
        coef, *_ = np.linalg.lstsq(A, a[..., c][mask], rcond=None)
        bg[..., c] = X @ coef
    return Image.fromarray(np.clip(bg, 1, 255).astype('uint8')).resize(img.size, Image.BILINEAR)


def clean(crop, bgcrop):
    a = np.asarray(crop).astype(float)
    b = np.asarray(bgcrop).astype(float)
    a = np.clip(a / b * 250, 0, 255)
    g = a.mean(2, keepdims=True)
    sat = a.max(2, keepdims=True) - a.min(2, keepdims=True)
    m = np.clip((g - 226) / 12, 0, 1) * (sat < 30)   # 뒷장 비침(밝기 233~250)은 지우고 옅은 회색 칠(~220)은 남긴다
    a = a * (1 - m) + 255 * m
    return Image.fromarray(a.astype('uint8'))


def deskew(img):
    g = np.asarray(img.convert('L').resize((max(1, img.width // 3), max(1, img.height // 3))))
    ink = (g < 200).astype(float)
    best, ba = -1, 0.0
    for ang in np.arange(-1.5, 1.51, 0.25):
        r = np.asarray(Image.fromarray((ink * 255).astype('uint8')).rotate(ang, resample=Image.BILINEAR))
        s = r.sum(1).astype(float)
        v = s.var()
        if v > best:
            best, ba = v, ang
    if abs(ba) < 0.2:
        return img
    return img.rotate(ba, resample=Image.BICUBIC, fillcolor=(255, 255, 255), expand=False)


def ink_bbox(img, pad=10):
    a = np.asarray(img).astype(int)
    ink = (a.min(2) < 225) | ((a.max(2) - a.min(2)) > 35)
    rows = np.where(ink.sum(1) > 2)[0]
    cols = np.where(ink.sum(0) > 2)[0]
    if not len(rows) or not len(cols):
        return (0, 0, img.width, img.height)
    return (max(0, cols[0] - pad), max(0, rows[0] - pad),
            min(img.width, cols[-1] + pad + 1), min(img.height, rows[-1] + pad + 1))


def render(doc, pdf, box, key, cache):
    if pdf not in cache:
        img = Image.open(SRC / doc / 'pages' / f'p{pdf:03d}.jpeg').convert('RGB')
        cache.clear()
        cache[pdf] = (img, paper_model(img))
    img, bg = cache[pdf]
    W, H = img.size
    px = (int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H))
    raw = img.crop(px)                       # 정리 전 사진 그대로 (해설 카드의 '원본 (책 지면)' 탭)
    raw.thumbnail((900, 900))
    c = clean(img.crop(px), bg.crop(px))
    c = deskew(c)
    c = c.crop(ink_bbox(c))
    out = OUT / doc
    out.mkdir(parents=True, exist_ok=True)
    hd = c.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
    if hd.width > 1800:
        hd = hd.resize((1800, round(hd.height * 1800 / hd.width)), Image.LANCZOS)
    hd.save(out / f'{key}-hd.png', optimize=True)
    sm = c
    if sm.width > 900:
        sm = sm.resize((900, round(sm.height * 900 / sm.width)), Image.LANCZOS)
    sm = sm.filter(ImageFilter.UnsharpMask(radius=1, percent=50, threshold=2))
    sm.save(out / f'{key}.png', optimize=True)
    raw.save(out / f'{key}-raw.jpg', quality=82)
    return {'raw': f'data/study/img/{doc}/{key}-raw.jpg', 'raw_w': raw.width, 'raw_h': raw.height, 'scan': True, 'img': f'data/study/img/{doc}/{key}.png', 'w': sm.width, 'h': sm.height,
            'hd': f'data/study/img/{doc}/{key}-hd.png', 'hd_w': hd.width, 'hd_h': hd.height}


def regions(lines):
    """캡션마다 자를 영역 (0~1 비율 x0,y0,x1,y1)"""
    ml, mr = margins(lines)
    body = body_lines(lines, ml)
    caps = captions(lines)
    caps.sort(key=lambda c: c['line']['y'])
    out = []
    for i, c in enumerate(caps):
        L = c['line']
        bottom = L['y'] - 0.004
        top = 0.035
        for b in body:
            if b['y'] + b['h'] < bottom - 0.01:
                top = max(top, b['y'] + b['h'] + 0.006)
        for p in caps[:i]:
            pl = p['line']
            if abs(pl['y'] - L['y']) < 0.02:
                continue
            if pl['y'] < L['y']:
                top = max(top, pl['y'] + pl['h'] + 0.006)
        x0, x1 = ml - 0.02, mr + 0.02     # 더 넓히면 책 가장자리 그림자가 들어온다
        # 같은 높이 캡션(나란한 그림)
        side = [p for p in caps if p is not c and abs(p['line']['y'] - L['y']) < 0.02]
        cx = L['x'] + L['w'] / 2
        for p in side:
            px = p['line']['x'] + p['line']['w'] / 2
            mid = (cx + px) / 2
            if px > cx:
                x1 = min(x1, mid)
            else:
                x0 = max(x0, mid)
        out.append((c, [max(0, x0), top, min(1, x1), bottom]))
    return out


def blocks(doc, pdf, lines):
    """캡션 없는 쪽: 본문 줄을 지운 뒤 잉크가 이어진 세로 덩어리 (0~1 비율 상자 목록)"""
    img = Image.open(SRC / doc / 'pages' / f'p{pdf:03d}.jpeg').convert('RGB')
    bg = paper_model(img)
    W, H = img.size
    a = np.asarray(clean(img, bg)).astype(int)
    ink = (a.min(2) < 200) | ((a.max(2) - a.min(2)) > 50)
    ml, mr = margins(lines)
    x0, x1 = int((ml - 0.02) * W), int((mr + 0.02) * H / H * W)
    ink[:, :x0] = False
    ink[:, x1:] = False
    ink[:int(0.04 * H)] = False
    ink[int(0.9 * H):] = False          # 꼬리말
    for b in body_lines(lines, ml) + [l for l in lines if re.match(r'^\d\.|^[①-⑧]', l['t'].strip()) or l['h'] > 0.02]:
        ink[max(0, int((b['y'] - 0.004) * H)):int((b['y'] + b['h'] + 0.004) * H), :] = False
    rows = ink.sum(1) > 3
    out, start, gap = [], None, 0
    for y in range(H):
        if rows[y]:
            if start is None:
                start = y
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 0.03 * H:
                end = y - gap
                if end - start > 0.04 * H:
                    out.append([max(0, ml - 0.02), round(start / H - 0.006, 4), min(1, mr + 0.02), round(end / H + 0.006, 4)])
                start, gap = None, 0
    if start is not None and H - gap - start > 0.04 * H:
        out.append([max(0, ml - 0.02), round(start / H - 0.006, 4), min(1, mr + 0.02), round((H - gap) / H + 0.006, 4)])
    # 범례 줄만 있는 얇은 덩어리는 바로 위 그림에 붙인다
    merged = []
    for b in out:
        if merged and b[3] - b[1] < 0.1 and b[1] - merged[-1][3] < 0.04:
            merged[-1][3] = b[3]
        else:
            merged.append(b)
    return merged


def expected(doc):
    """쪽별 인벤토리에 적힌 그림·표 번호 (빠진 것 확인용)"""
    inv = SRC / doc / 'inventory'
    seen = set()
    for f in sorted(inv.glob('*.md')) if inv.exists() else []:
        for k, n in re.findall(r'\[(그림|표) (\d-\d+)\]', f.read_text(encoding='utf-8')):
            seen.add(('fig' if k == '그림' else 'tbl') + '-' + n)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc', required=True)
    ap.add_argument('--only', help='이 key 만 다시 (쉼표)')
    ap.add_argument('--sheet', action='store_true', help='검수용 접촉 시트만 만든다')
    a = ap.parse_args()
    doc = a.doc
    cfg = DOCS[doc]
    FIX[:] = cfg.get('fix', [])
    d = SRC / doc
    if a.sheet:
        return sheet(doc)

    pdfs = sorted(int(p.stem[1:]) for p in (d / 'ocr').glob('p*.json'))
    pages, items = [], {}
    for pdf in pdfs:
        o = load_ocr(doc, pdf)
        bp = book_page(cfg, pdf)
        pages.append({'pdf': pdf, 'page': bp if bp is not None else -1, 'text': page_text(cfg, o['lines'])})
        if bp is None:
            continue
        for c, box in regions(o['lines']):
            c['no'] = cfg.get('renum', {}).get((pdf, c['no']), c['no'])
            key = f'{c["kind"]}-{c["no"]}'
            if key in items:      # 같은 번호가 또 나오면(요약 재수록 등) 뒤엣것은 -b
                key += '-b'
            items[key] = {'key': key, 'kind': c['kind'], 'no': c['no'], 'title': c['title'], 'part': '',
                          'pdf': pdf, 'page': bp, 'box': [round(v, 4) for v in box], 'source': '', 'has_source': False}

    for cut in cfg.get('cuts', []):
        n = 0
        for pdf in range(cut['pdf'][0], cut['pdf'][1] + 1):
            for box in blocks(doc, pdf, load_ocr(doc, pdf)['lines']):
                n += 1
                key = f'{cut["prefix"]}-{n:02d}'
                items[key] = {'key': key, 'kind': 'fig', 'no': '', 'title': f'{cut["title"]} {n}', 'part': cut['part'],
                              'pdf': pdf, 'page': book_page(cfg, pdf), 'box': box, 'source': '', 'has_source': False}

    manual = json.loads((d / 'crops.json').read_text(encoding='utf-8')) if (d / 'crops.json').exists() else {}
    for key, m in manual.items():
        if key.startswith('_'):
            continue
        it = items.get(key) or {'key': key, 'kind': m.get('kind', 'fig'), 'no': m.get('no', ''),
                                'title': m.get('title', ''), 'part': '', 'source': '', 'has_source': False}
        it.update({k: v for k, v in m.items() if k in ('title', 'no', 'kind')})
        it['pdf'] = m['pdf']
        it['page'] = book_page(cfg, m['pdf'])
        it['box'] = m['box']
        it['manual'] = True
        items[key] = it

    only = set(a.only.split(',')) if a.only else None
    old = {}
    if only and (d / 'figures.json').exists():
        old = {x['key']: x for x in json.loads((d / 'figures.json').read_text(encoding='utf-8'))}
    cache = {}
    for key in sorted(items, key=lambda k: (items[k]['pdf'], items[k]['box'][1])):
        it = items[key]
        if only and key not in only and key in old:
            it.update({k: old[key][k] for k in ('img', 'w', 'h', 'hd', 'hd_w', 'hd_h', 'raw', 'raw_w', 'raw_h', 'scan') if k in old[key]})
            continue
        it.update(render(doc, it['pdf'], it['box'], key, cache))

    def order(k):
        it = items[k]
        return (it['pdf'], it['box'][1], it['box'][0])
    lst = [items[k] for k in sorted(items, key=order)]
    (d / 'pages.json').write_text(json.dumps(pages, ensure_ascii=False, indent=0), encoding='utf-8')
    (d / 'figures.json').write_text(json.dumps(lst, ensure_ascii=False, indent=1), encoding='utf-8')

    exp = expected(doc)
    got = {k for k in items}
    print(f'쪽 {len(pages)} · 그림 {sum(1 for x in lst if x["kind"] == "fig")} · 표 {sum(1 for x in lst if x["kind"] == "tbl")}'
          f' (손 보정 {sum(1 for x in lst if x.get("manual"))})')
    if exp:
        miss = sorted(exp - got, key=lambda k: [int(x) for x in re.findall(r'\d+', k)])
        extra = sorted(k for k in got - exp if not items[k].get('manual') and not items[k].get('part'))
        print('인벤토리에 있는데 못 찾음:', ', '.join(miss) or '없음')
        print('인벤토리에 없는데 찾음:', ', '.join(extra) or '없음')


def sheet(doc):
    """검수용 접촉 시트: 그림마다 축소본 + key·쪽, 한 장에 24개"""
    figs = json.loads((SRC / doc / 'figures.json').read_text(encoding='utf-8'))
    try:
        font = ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc', 22)
    except OSError:
        font = ImageFont.load_default()
    cw, ch, cols, rows = 420, 340, 6, 4
    per = cols * rows
    for s in range(0, len(figs), per):
        sh = Image.new('RGB', (cw * cols, ch * rows), (235, 235, 235))
        dr = ImageDraw.Draw(sh)
        for i, f in enumerate(figs[s:s + per]):
            x, y = (i % cols) * cw, (i // cols) * ch
            im = Image.open(ROOT / 'public' / f['img']).convert('RGB')
            im.thumbnail((cw - 16, ch - 46))
            sh.paste(im, (x + 8, y + 38))
            dr.rectangle([x + 8, y + 38, x + 8 + im.width, y + 38 + im.height], outline=(200, 60, 60))
            dr.text((x + 8, y + 6), f'{f["key"]} p.{f["page"]} (PDF {f["pdf"]}){" ✋" if f.get("manual") else ""}',
                    fill=(0, 0, 0), font=font)
        p = SRC / doc / f'sheet-{s // per + 1:02d}.jpg'
        sh.save(p, quality=82)
        print(p)


if __name__ == '__main__':
    raise SystemExit(main())
