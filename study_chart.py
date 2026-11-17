"""
Beom's Study: 리포트 차트 이미지에서 막대 값 읽기 (재구성 차트용 데이터)

증권사 PDF 의 차트는 대부분 이미지로 박혀 있어 숫자가 글자로 남아 있지 않다.
고해상도로 렌더한 뒤 픽셀에서 ① 막대(같은 색 덩어리)의 위·아래 끝 ② 왼쪽 축 눈금 글자의 세로 위치를 찾고,
눈금 값(사람이 그림을 보고 넣어 줌)으로 직선 맞춤 → 막대 높이를 값으로 바꾼다.

  python3 study_chart.py --doc hmsec-onc-vol1 --key fig-007 --ticks 80000,60000,40000,20000,0
  python3 study_chart.py ... --stack        # 쌓은 막대: 막대마다 색 구간별 높이
  python3 study_chart.py ... --save out.png # 찾은 막대·눈금을 표시한 확인용 이미지

눈금 글자 줄 수와 --ticks 개수가 다르면 멈춘다(잘못 맞추는 것보다 낫다). 결과는 반올림 전 값과
'눈금 한 칸 = 몇 픽셀'을 같이 찍는다. 막대 끝의 안티앨리어싱 때문에 오차는 보통 눈금 한 칸의 1% 안팎.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
DPI = 400


def render(doc, key):
    figs = {x['key']: x for x in json.loads((ROOT / 'study_src' / doc / 'figures.json').read_text())}
    f = figs[key]
    pdf = ROOT / 'study_src' / 'pdf' / f'{doc}.pdf'
    page = pymupdf.open(pdf)[f['pdf'] - 1]
    pix = page.get_pixmap(dpi=DPI, clip=pymupdf.Rect(f['rect']))
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples), f


def sat(c):
    return max(c) - min(c)


def quant(c, q=24):
    return tuple(v // q * q for v in c)


def bar_colors(im, top_n=8):
    """채도가 있는(회색·검정·흰색이 아닌) 색 중 많이 쓰인 것. 회색 막대도 있으니 --gray 로 추가 가능"""
    cnt = Counter()
    W, H = im.size
    px = im.load()
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            c = px[x, y]
            if sat(c) > 60:
                cnt[quant(c)] += 1
    return [c for c, n in cnt.most_common(top_n) if n > 200]


def near(c, ref, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def find_bars(im, color, tol=40, min_w=6, min_h=4):
    """색 color 의 세로 막대들: [(x0, x1, top, bottom)] 왼쪽부터"""
    W, H = im.size
    px = im.load()
    cols = []
    for x in range(W):
        ys = [y for y in range(H) if near(px[x, y], color, tol)]
        cols.append((min(ys), max(ys)) if len(ys) >= min_h else None)
    bars, run = [], []
    for x, c in enumerate(cols + [None]):
        if c:
            run.append((x, c))
        elif run:
            if len(run) >= min_w:
                mid = run[len(run) // 2][1]
                core = [r for _, r in run[len(run) // 5: len(run) - len(run) // 5]] or [mid]
                top = sorted(t for t, _ in core)[len(core) // 2]
                bot = sorted(b for _, b in core)[len(core) // 2]
                bars.append((run[0][0], run[-1][0], top, bot))
            run = []
    return bars


def tick_rows(im, x_max):
    """왼쪽 축 글자(어두운 픽셀)가 있는 줄 묶음의 세로 가운데"""
    W, H = im.size
    px = im.load()
    dark = lambda x, y: sum(px[x, y]) < 330 and sat(px[x, y]) < 40
    # 축선·테두리처럼 세로로 길게 이어진 열은 뺀다 (글자 줄이 하나로 붙어 버린다)
    xs = [x for x in range(0, x_max) if sum(dark(x, y) for y in range(H)) < H * 0.25]
    rows = [any(dark(x, y) for x in xs) for y in range(H)]
    out, start = [], None
    for y, r in enumerate(rows + [False]):
        if r and start is None:
            start = y
        elif not r and start is not None:
            if y - start >= 8:
                out.append((start + y - 1) / 2)
            start = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--ticks', required=True, help='왼쪽 축 눈금 값, 위에서 아래로 (예: 80000,60000,40000,20000,0)')
    ap.add_argument('--color', action='append', default=[], help='막대 색 r,g,b (생략하면 자동)')
    ap.add_argument('--tol', type=int, default=40)
    ap.add_argument('--axis-x', type=float, default=None, help='눈금 글자를 찾을 왼쪽 폭 비율(기본: 첫 막대 왼쪽)')
    ap.add_argument('--skip-top', type=float, default=0.12, help='위쪽 제목 영역 비율은 눈금에서 뺀다')
    ap.add_argument('--skip-bottom', type=float, default=0.10)
    ap.add_argument('--stack', action='store_true')
    ap.add_argument('--save')
    a = ap.parse_args()

    im, f = render(a.doc, a.key)
    W, H = im.size
    colors = [tuple(map(int, c.split(','))) for c in a.color] or bar_colors(im)[:1]   # 기본: 가장 많이 쓰인 막대 색 하나
    print(f'{a.key} {f["title"]}  ({W}x{H}px @ {DPI}dpi)')
    print('막대 색 후보:', colors)

    allbars = {c: [b for b in find_bars(im, c, a.tol) if b[3] - b[2] > 3] for c in colors}
    allbars = {c: bs for c, bs in allbars.items() if bs}
    first_x = min(b[0] for bs in allbars.values() for b in bs)
    x_max = int(W * a.axis_x) if a.axis_x else first_x - 4
    rows = [r for r in tick_rows(im, x_max) if H * a.skip_top < r < H * (1 - a.skip_bottom)]
    ticks = [float(t) for t in a.ticks.split(',')]
    print(f'눈금 글자 줄 {len(rows)}개: {[round(r) for r in rows]}')
    if len(rows) > len(ticks):
        # 단위 글자 '(백만달러)' 같은 줄이 섞이면, 간격이 가장 고른 연속 구간을 눈금으로 본다
        def spread(w):
            g = [b - a for a, b in zip(w, w[1:])]
            return max(g) - min(g)
        rows = min((rows[i:i + len(ticks)] for i in range(len(rows) - len(ticks) + 1)), key=spread)
        print(f'  → 간격이 가장 고른 {len(ticks)}줄 사용: {[round(r) for r in rows]}')
    if len(rows) != len(ticks):
        print(f'눈금 줄 수({len(rows)}) ≠ --ticks 개수({len(ticks)}). --skip-top/--skip-bottom/--axis-x 를 조정하세요.')
        return 2
    # 직선 맞춤 value = a*y + b
    n = len(rows)
    my, mv = sum(rows) / n, sum(ticks) / n
    slope = sum((y - my) * (v - mv) for y, v in zip(rows, ticks)) / sum((y - my) ** 2 for y in rows)
    icpt = mv - slope * my
    resid = max(abs(slope * y + icpt - v) for y, v in zip(rows, ticks))
    step_px = abs((rows[-1] - rows[0]) / (n - 1))
    print(f'맞춤: 값 = {slope:.3f}·y + {icpt:.1f}  (눈금 한 칸 {step_px:.0f}px, 최대 잔차 {resid:.3g})')
    val = lambda y: slope * y + icpt

    if a.stack:
        # 쌓은 막대: 막대 x 위치는 기준 색(맨 아래 구간) 막대에서 잡고, 가운데 세로줄을 바닥부터 위로 훑어
        # 흰 바탕이 나올 때까지 색이 바뀌는 지점마다 끊는다. 회색·검정 구간도 잡힌다. 색 → 계열은 범례를 보고 사람이 붙인다.
        base = max(allbars.values(), key=len)
        px = im.load()
        for i, (x0, x1, _, bot) in enumerate(base):
            xm = (x0 + x1) // 2
            segs, cur, start = [], None, bot
            y = bot
            while y > 0:
                c = px[xm, y]
                if min(c) > 235:            # 흰 바탕 = 막대 끝
                    break
                q = quant(c, 32)
                if cur is None:
                    cur = q
                elif q != cur and all(quant(px[xm, y - k], 32) == q for k in range(1, 4)):   # 3px 이상 이어져야 새 구간
                    segs.append((cur, y + 1, start))
                    cur, start = q, y
                y -= 1
            segs.append((cur, y + 1, start))
            parts = [(c, round(val(top) - val(b + 1), 1)) for c, top, b in segs if b - top > 2]
            print(f'  막대 {i + 1} (아래→위): ' + ' | '.join(f'{c}: {v:,}' for c, v in parts) + f'  합 {sum(v for _, v in parts):,.1f}')
    else:
        for c, bs in allbars.items():
            print(f'색 {c}: 막대 {len(bs)}개')
            for i, (x0, x1, top, bot) in enumerate(bs):
                # 높이 = 위 끝 - 아래 끝 (바닥선 두께만큼의 치우침이 빠진다)
                print(f'  {i + 1:2d}. x {x0}-{x1}  값 {val(top) - val(bot + 1):,.1f}  (위 끝 눈금값 {val(top):,.1f})')

    if a.save:
        dr = ImageDraw.Draw(im)
        for bs in allbars.values():
            for x0, x1, top, bot in bs:
                dr.rectangle([x0, top, x1, bot], outline=(255, 0, 0), width=2)
        for r in rows:
            dr.line([0, r, x_max, r], fill=(0, 200, 0), width=2)
        im.save(a.save)
    return 0


if __name__ == '__main__':
    sys.exit(main())
