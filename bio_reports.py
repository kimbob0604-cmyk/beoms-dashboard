"""
바이오 탭: 증권사 리포트 모음과 요약.

- 국장: 대시보드가 모으는 네이버 종목분석 리포트(research 테이블: 증권사·투자의견·목표가·요약·PDF). PDF 원문을
  내려받아 텍스트로 바꾼 뒤, 목표가 산정·가치평가 근거가 담긴 문장만 원문 그대로 뽑는다(요약을 지어내지 않음).
  PDF 텍스트는 macOS PDFKit(osascript)로 읽고 .cache/reports/ 에 남겨 다시 받지 않는다.
- 미장: 리포트 원문은 무료로 받을 수 없어 yfinance 의 애널리스트 목표가(평균·최저·최고)와 최근 의견·목표가 변경만 모은다.

  python3 bio_reports.py 196170
"""

import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

import db

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / '.cache' / 'reports'
JS = """ObjC.import('PDFKit');
function run(argv) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  if (!doc || doc.isNil()) return '';
  return ObjC.unwrap(doc.string);
}"""

# 목표가 산정·가치평가 근거 문장을 고르는 말
VAL_KEYS = re.compile(r'목표주가|목표 주가|적정\s?주가|적정\s?시가총액|산정|rNPV|NPV|DCF|SOTP|WACC|할인율|성공\s?확률|PoS|LoA|피크|peak|Peak|'
                      r'로열티|royalty|마일스톤|milestone|영업가치|신약가치|파이프라인 가치|기술가치|순현금|순차입|Target|목표 PER|PER\s?\d|'
                      r'점유율|시장 규모|침투율|약가', re.I)
NUM = re.compile(r'\d')
SKIP = re.compile(r'제시일자|괴리율|향후 6개월간|Target Price \d|Compliance|투자의견 및 적정|본 자료는|당사는|고지|Disclaimer|무단|복제|신뢰할 만한|법적 책임|최근 2년간|투자등급|'
                  r'금융투자분석사|이해관계|기업분석부|Analyst|@', re.I)


def pdf_text(url: str, rid) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    txt = CACHE / f'{rid}.txt'
    if txt.exists():
        return txt.read_text(encoding='utf-8')
    pdf = CACHE / f'{rid}.pdf'
    r = requests.get(url, timeout=60, headers={'User-Agent': 'Mozilla/5.0 (compatible; BeomDashboard)'})
    r.raise_for_status()
    pdf.write_bytes(r.content)
    js = CACHE / 'pdftext.js'
    if not js.exists():
        js.write_text(JS, encoding='utf-8')
    out = subprocess.run(['osascript', '-l', 'JavaScript', str(js), str(pdf)], capture_output=True, text=True, timeout=120).stdout
    pdf.unlink(missing_ok=True)
    txt.write_text(out, encoding='utf-8')
    return out


def sentences_kr(text: str):
    """PDF 줄바꿈을 이어 붙인 뒤 문장(…다. / . )으로 나눈다. 표 줄은 짧아서 걸러진다."""
    t = re.sub(r'-\n', '', text)
    t = re.sub(r'(?<![.다\)])\n(?=\S)', ' ', t)
    t = re.sub(r'[ \t]+', ' ', t)
    for line in t.split('\n'):
        for s in re.split(r'(?<=다\.)\s+|(?<=[a-z0-9%)]\.)\s+(?=[A-Z가-힣])', line):
            s = s.strip(' ·•-')
            if 25 <= len(s) <= 260:
                yield s


def valuation_lines(text: str, limit: int = 8) -> list:
    out, seen = [], set()
    for s in sentences_kr(text):
        if not VAL_KEYS.search(s) or not NUM.search(s) or SKIP.search(s):
            continue
        k = re.sub(r'\s+', '', s)[:50]
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def kr_reports(code: str, days: int = 180, max_pdf: int = 8) -> dict:
    conn = db.connect()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute('SELECT id, broker, date, opinion, goal, price, title, heads, body, pdf FROM research WHERE code=? AND date>=? ORDER BY date DESC',
                        (code, since)).fetchall()
    items = []
    for i, (rid, broker, d, op, goal, price, title, heads, body, pdf) in enumerate(rows):
        lines, err = [], None
        if pdf and i < max_pdf:
            try:
                lines = valuation_lines(pdf_text(pdf, rid))
            except Exception as e:   # PDF 받기·읽기 실패는 목록만 남긴다
                err = str(e)[:80]
        try:
            hl = json.loads(heads) if heads else []
        except ValueError:
            hl = []
        items.append({'id': rid, 'broker': broker, 'date': d, 'opinion': op, 'goal': goal, 'price_at': price, 'title': title,
                      'heads': hl[:3], 'valuation': lines, 'pdf': pdf, 'error': err})
    latest = {}
    for it in items:   # 증권사별 가장 최근 목표가
        if it['goal'] and it['broker'] not in latest:
            latest[it['broker']] = it
    goals = [x['goal'] for x in latest.values()]
    summary = {'n_reports': len(items), 'n_brokers': len(latest), 'source': '네이버 종목분석 (증권사 리포트 원문 PDF)'}
    if goals:
        summary.update({'goal_avg': sum(goals) / len(goals), 'goal_min': min(goals), 'goal_max': max(goals)})
    return {'kind': 'kr', 'summary': summary, 'items': items, 'latest': sorted(latest.values(), key=lambda x: x['date'], reverse=True)}


def us_reports(ticker: str, days: int = 180) -> dict:
    import yfinance as yf
    t = yf.Ticker(ticker)
    summary = {'source': 'yfinance 애널리스트 목표가 (리포트 원문 아님)'}
    try:
        pt = t.analyst_price_targets or {}
        summary.update({'goal_avg': pt.get('mean'), 'goal_min': pt.get('low'), 'goal_max': pt.get('high'), 'goal_median': pt.get('median')})
    except Exception:
        pass
    items = []
    try:
        ud = t.upgrades_downgrades
        since = date.today() - timedelta(days=days)
        for idx, r in ud.iterrows():
            if idx.date() < since:
                break
            items.append({'date': idx.strftime('%Y-%m-%d'), 'broker': r.get('Firm'), 'opinion': r.get('ToGrade'), 'from': r.get('FromGrade'),
                          'action': r.get('Action'), 'goal': float(r['currentPriceTarget']) if r.get('currentPriceTarget') else None,
                          'goal_prev': float(r['priorPriceTarget']) if r.get('priorPriceTarget') else None, 'pt_action': r.get('priceTargetAction')})
    except Exception:
        pass
    latest = {}
    for it in items:
        if it['goal'] and it['broker'] not in latest:
            latest[it['broker']] = it
    summary.update({'n_reports': len(items), 'n_brokers': len(latest)})
    return {'kind': 'us', 'summary': summary, 'items': items, 'latest': sorted(latest.values(), key=lambda x: x['date'], reverse=True)}


if __name__ == '__main__':
    code = sys.argv[1] if len(sys.argv) > 1 else '196170'
    r = kr_reports(code) if code.isdigit() else us_reports(code)
    print(json.dumps(r['summary'], ensure_ascii=False))
    for it in r['items'][:6]:
        print('-', it['date'], it['broker'], it.get('opinion'), it.get('goal'), it.get('title'))
        for v in it.get('valuation', []):
            print('     ·', v)
