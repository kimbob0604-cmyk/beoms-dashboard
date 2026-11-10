"""
소비재 탭 종목 설정 초안 만들기 → consumer_assets.json  (바이오의 bio_draft.py 자리)

종목마다 밸류체인 단계와 '수출 흐름'(어느 품목 묶음이 어느 지역에서 나가는가)을 적는다. 흐름의 근거는 세 가지:
  channel  텔레그램 수출입 채널이 그 종목·지역·품목을 짝지어 다룬 기록 (KBJ 매핑 작업 2026-10, 글 건수만 참고 — 본문·숫자는 쓰지 않는다)
  hq       DART 기업개황의 본사 주소가 있는 시군구 (공장이 아닐 수 있다 — 검수 전 초안)
  national 전국 품목 묶음 (회사 흐름이 아니라 업황 — 여러 회사가 섞인다)
이 스크립트는 초안만 만든다. 검수해서 고친 뒤 "reviewed": true 로 바꾸는 것은 consumer_assets.json 에서 직접 한다.
이미 있는 종목은 덮어쓰지 않는다(--redo 로 전부 다시).

  python3 consumer_draft.py            # 표에 있는 종목 가운데 설정에 없는 것만 더한다
  python3 consumer_draft.py --redo     # 전부 다시 만든다 (손으로 고친 것이 사라진다)
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

import config  # noqa: F401
from collect_history import corp_codes

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'consumer_assets.json'
NAMES = ROOT / 'public' / 'data' / 'names.json'
DART = 'https://opendart.fss.or.kr/api'

# 밸류체인 단계 (왼쪽 → 오른쪽이 가치사슬의 흐름)
CHAINS = {
    '화장품': ['원료·소재', '용기·부자재', 'ODM·OEM', '브랜드', '유통·플랫폼'],
    '식음료': ['원료·소재', '라면', '제과·빙과', '종합식품', '수산·김', '음료·주류', '담배', '건강기능식품', '외식'],
    '미용 의료·의료기기': ['톡신·필러·스킨부스터', '미용 의료기기', '치과 임플란트', '창상·렌즈'],
}
# (이름, 분야, 단계, 품목 묶음(consumer_hs.json 의 id), 채널 근거 지역 {묶음: [시도코드:시군구…]}, 메모)
STOCKS = [
    ('아모레퍼시픽', '화장품', '브랜드', ['skin', 'color', 'cleanse'], {}, ''),
    ('LG생활건강', '화장품', '브랜드', ['skin', 'cleanse', 'hair'], {}, '생활용품·음료 매출이 크다 — 수출이 설명하는 비중이 낮다'),
    ('에이피알', '화장품', '브랜드', ['skin', 'mask', 'device'], {'skin': ['11:송파구'], 'mask': ['11:송파구'], 'device': ['11:송파구']}, '뷰티 디바이스 포함'),
    ('달바글로벌', '화장품', '브랜드', ['skin'], {'skin': ['11:마포구']}, ''),
    ('브이티', '화장품', '브랜드', ['skin', 'mask'], {}, ''),
    ('아이패밀리에스씨', '화장품', '브랜드', ['color'], {}, ''),
    ('클리오', '화장품', '브랜드', ['color', 'skin'], {}, ''),
    ('마녀공장', '화장품', '브랜드', ['skin', 'cleanse'], {}, ''),
    ('토니모리', '화장품', '브랜드', ['skin', 'color'], {}, ''),
    ('에이블씨엔씨', '화장품', '브랜드', ['skin', 'color'], {}, ''),
    ('삐아', '화장품', '브랜드', ['color'], {}, ''),
    ('애경산업', '화장품', '브랜드', ['color', 'skin', 'hair'], {}, '생활용품 매출이 크다'),
    ('네오팜', '화장품', '브랜드', ['skin'], {}, ''),
    ('코스맥스', '화장품', 'ODM·OEM', ['skin', 'color'], {}, '고객사가 수출 — 간접 수출. 해외 법인 생산은 한국 수출에 안 잡힌다'),
    ('한국콜마', '화장품', 'ODM·OEM', ['skin', 'color'], {}, '고객사가 수출 — 간접 수출'),
    ('코스메카코리아', '화장품', 'ODM·OEM', ['skin', 'color'], {}, '고객사가 수출 — 간접 수출. 미국 법인(잉글우드랩) 연결'),
    ('씨앤씨인터내셔널', '화장품', 'ODM·OEM', ['color'], {'color': ['41:화성시']}, '색조 ODM'),
    ('한국화장품제조', '화장품', 'ODM·OEM', ['skin'], {'skin': ['43:음성군']}, ''),
    ('잉글우드랩', '화장품', 'ODM·OEM', ['skin', 'color'], {}, '미국 법인 생산이 중심 — 한국 수출과의 관계가 약하다'),
    ('제닉', '화장품', 'ODM·OEM', ['mask'], {}, '마스크팩·패치 ODM'),
    ('실리콘투', '화장품', '유통·플랫폼', ['skin', 'color'], {}, '자기 이름으로 여러 브랜드를 수출'),
    ('청담글로벌', '화장품', '유통·플랫폼', ['skin'], {}, ''),
    ('펌텍코리아', '화장품', '용기·부자재', ['pack'], {}, '용기는 주로 국내 브랜드·ODM 에 납품 — 화장품 수출의 후행 지표로 본다'),
    ('에스엠씨지', '화장품', '용기·부자재', ['pack'], {}, '유리 용기'),
    ('선진뷰티사이언스', '화장품', '원료·소재', ['skin'], {}, '자외선 차단 소재 — 품목이 따로 분류돼 화장품 수출과 직접 맞지 않는다'),
    ('엔에프씨', '화장품', '원료·소재', ['skin'], {}, ''),
    ('현대바이오랜드', '화장품', '원료·소재', ['skin'], {}, ''),
    ('제이투케이바이오', '화장품', '원료·소재', ['skin'], {}, ''),
    ('삼양식품', '식음료', '라면', ['ramen', 'sauce'], {'ramen': ['48:밀양시', '51:원주시', '52:익산시', '11:성북구'], 'sauce': ['48:밀양시', '51:원주시', '52:익산시', '11:성북구']}, ''),
    ('농심', '식음료', '라면', ['ramen', 'snack'], {}, '미국·중국 현지 공장 매출은 한국 수출에 안 잡힌다'),
    ('오뚜기', '식음료', '라면', ['ramen', 'sauce'], {'ramen': ['41:평택시']}, '내수 비중이 크다'),
    ('오리온', '식음료', '제과·빙과', ['snack'], {}, '중국·베트남·러시아 현지 법인 매출이 대부분 — 한국 수출로는 설명되지 않는다'),
    ('롯데웰푸드', '식음료', '제과·빙과', ['snack', 'ice'], {'snack': ['11:영등포구'], 'ice': ['11:영등포구']}, '인도 등 해외 법인 별도'),
    ('빙그레', '식음료', '제과·빙과', ['ice', 'drink'], {'ice': ['41:남양주시', '47:경산시']}, ''),
    ('크라운제과', '식음료', '제과·빙과', ['snack'], {}, ''),
    ('해태제과식품', '식음료', '제과·빙과', ['snack', 'ice'], {}, ''),
    ('CJ제일제당', '식음료', '종합식품', ['kimchi', 'sauce', 'gim'], {}, '미국 등 해외 생산과 바이오·사료 사업이 크다'),
    ('대상', '식음료', '종합식품', ['kimchi', 'sauce'], {}, '소재(전분당·라이신) 사업 포함'),
    ('풀무원', '식음료', '종합식품', ['kimchi'], {}, '해외 현지 생산 비중이 크다'),
    ('샘표식품', '식음료', '종합식품', ['sauce'], {}, ''),
    ('동원산업', '식음료', '수산·김', ['gim'], {}, '지주·수산·포장재가 섞여 있다'),
    ('CJ씨푸드', '식음료', '수산·김', ['gim'], {}, ''),
    ('사조씨푸드', '식음료', '수산·김', ['gim'], {}, ''),
    ('사조대림', '식음료', '수산·김', ['gim', 'sauce'], {}, ''),
    ('우양', '식음료', '원료·소재', ['snack'], {}, '핫도그·HMR 은 품목 사전에 없다 — 과자·베이커리 묶음은 참고용'),
    ('에스앤디', '식음료', '원료·소재', ['sauce'], {'sauce': ['48:밀양시', '51:원주시', '11:성북구']}, '삼양식품에 소스 원료를 공급 — 삼양식품 공장 지역의 소스 수출을 대신 본다(간접)'),
    ('하이트진로', '식음료', '음료·주류', ['liquor'], {'liquor': ['48:창원시']}, ''),
    ('롯데칠성', '식음료', '음료·주류', ['liquor', 'drink'], {'liquor': ['51:강릉시']}, ''),
    ('매일유업', '식음료', '음료·주류', ['drink'], {}, ''),
    ('KT&G', '식음료', '담배', ['tobacco'], {'tobacco': ['30:대덕구', '47:영주시', '29:북구', '12:북구']}, '해외 현지 생산·홍삼·부동산 별도'),
    ('노바렉스', '식음료', '건강기능식품', ['health'], {'health': ['43:청주시']}, ''),
    ('서흥', '식음료', '건강기능식품', ['health'], {'health': ['43:청주시']}, '캡슐 사업 포함'),
    ('교촌에프앤비', '식음료', '외식', [], {}, '수출 통계와 맞는 품목이 없다 — 밸류체인 표시만'),
    # 미용 의료·의료기기 — 지역은 수출입 채널 기록(KBJ 매핑, 2026-10)
    ('휴젤', '미용 의료·의료기기', '톡신·필러·스킨부스터', ['toxin'], {'toxin': ['51:춘천시']}, '필러·화장품 매출 별도'),
    ('메디톡스', '미용 의료·의료기기', '톡신·필러·스킨부스터', ['toxin'], {'toxin': ['43:청주시']}, ''),
    ('대웅제약', '미용 의료·의료기기', '톡신·필러·스킨부스터', ['toxin'], {'toxin': ['41:화성시']}, '전문의약품 매출이 대부분 — 톡신(나보타)은 일부'),
    ('파마리서치', '미용 의료·의료기기', '톡신·필러·스킨부스터', ['inject', 'mask'], {'inject': ['51:강릉시'], 'mask': ['51:강릉시']}, '스킨부스터(리쥬란)·화장품. 내수 의료기기 매출이 크다'),
    ('휴메딕스', '미용 의료·의료기기', '톡신·필러·스킨부스터', ['skin'], {}, '필러는 기초·메이크업 묶음의 기타(3304.99.9000)에 섞여 신고된다 — 전국 묶음은 참고용'),
    ('바이오플러스', '미용 의료·의료기기', '톡신·필러·스킨부스터', ['skin'], {}, '필러는 기초·메이크업 묶음의 기타에 섞여 신고된다 — 전국 묶음은 참고용'),
    ('클래시스', '미용 의료·의료기기', '미용 의료기기', ['derma'], {'derma': ['11:강남구']}, ''),
    ('원텍', '미용 의료·의료기기', '미용 의료기기', ['derma'], {'derma': ['30:유성구']}, ''),
    ('아스테라시스', '미용 의료·의료기기', '미용 의료기기', ['derma'], {}, ''),
    ('레이저옵텍', '미용 의료·의료기기', '미용 의료기기', ['derma', 'device'], {}, ''),
    ('하이로닉', '미용 의료·의료기기', '미용 의료기기', ['derma', 'device'], {}, ''),
    ('동국제약', '미용 의료·의료기기', '미용 의료기기', ['device', 'skin'], {}, '의약품이 중심 — 화장품(센텔리안24)·미용기기는 일부'),
    ('덴티움', '미용 의료·의료기기', '치과 임플란트', ['implant'], {'implant': ['41:수원시']}, '중국·베트남 현지 생산 별도'),
    ('디오', '미용 의료·의료기기', '치과 임플란트', ['implant'], {'implant': ['26:해운대구']}, ''),
    ('덴티스', '미용 의료·의료기기', '치과 임플란트', ['implant'], {'implant': ['27:달서구']}, ''),
    ('티앤엘', '미용 의료·의료기기', '창상·렌즈', ['wound'], {'wound': ['41:안성시']}, '하이드로콜로이드 패치'),
    ('인터로조', '미용 의료·의료기기', '창상·렌즈', ['lens'], {}, ''),
]
SIDO = {'서울': '11', '부산': '26', '대구': '27', '인천': '28', '광주': '29', '대전': '30', '울산': '31', '세종': '36', '경기': '41',
        '충북': '43', '충청북': '43', '충남': '44', '충청남': '44', '전남': '46', '전라남': '46', '경북': '47', '경상북': '47',
        '경남': '48', '경상남': '48', '제주': '50', '강원': '51', '전북': '52', '전라북': '52'}


def region_of(addr: str):
    """주소 → '시도코드:시군구'. '경기도 성남시 분당구 …' → '41:성남시', '서울특별시 용산구 …' → '11:용산구'. 모르면 None"""
    m = re.match(r'\s*(\S+?)(?:특별자치시|특별자치도|특별시|광역시|도)?\s+(\S+?[시군구])(?:\s|$)', addr or '')
    if not m:
        m2 = re.match(r'\s*(세종)', addr or '')
        return '36:세종특별자치시' if m2 else None
    sido = next((code for k, code in SIDO.items() if m.group(1).startswith(k)), None)
    if sido == '36':
        return '36:세종특별자치시'
    return f'{sido}:{m.group(2)}' if sido else None


def hq_regions(codes: list) -> dict:
    """{종목코드: (시도코드:시군구, 주소)} — DART 기업개황. 키가 없거나 실패하면 빈 값"""
    key = os.environ.get('DART_API_KEY', '')
    if not key:
        print('DART_API_KEY 가 없어 본사 주소를 붙이지 못합니다')
        return {}
    s = requests.Session()
    cc = corp_codes(s, key)
    out = {}
    for c in codes:
        if c not in cc:
            continue
        try:
            d = s.get(f'{DART}/company.json', params={'crtfc_key': key, 'corp_code': cc[c]}, timeout=15).json()
        except (requests.RequestException, ValueError):
            continue
        r = region_of(d.get('adres', ''))
        if r:
            out[c] = (r, d.get('adres', ''))
    return out


def entry(code, name, sector, stage, groups, channel, memo, hq) -> dict:
    flows = []
    for g in groups:
        if channel.get(g):
            flows.append({'id': f'c-{g}', 'kind': 'sigungu', 'group': g, 'regions': channel[g], 'basis': 'channel', 'nature': 'company'})
        elif hq:
            flows.append({'id': f'h-{g}', 'kind': 'sigungu', 'group': g, 'regions': [hq[0]], 'basis': 'hq', 'nature': 'draft'})
        flows.append({'id': f'n-{g}', 'kind': 'national', 'group': g, 'basis': 'national', 'nature': 'mixed'})
    return {'code': code, 'name': name, 'sector': sector, 'stage': stage, 'groups': groups, 'memo': memo,
            'hq': hq[0] if hq else None, 'hq_addr': hq[1] if hq else None, 'flows': flows, 'reviewed': False}


def main() -> int:
    redo = '--redo' in sys.argv
    names = {r[1]: r[0] for r in json.loads(NAMES.read_text(encoding='utf-8'))}
    old = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() and not redo else {'stocks': []}
    have = {s['code'] for s in old['stocks']}
    missing = [n for n, *_ in STOCKS if n not in names]
    if missing:
        print('종목 목록에 없는 이름(건너뜀):', missing)
    todo = [(names[n], n, *rest) for n, *rest in STOCKS if n in names and names[n] not in have]
    hq = hq_regions([t[0] for t in todo]) if todo else {}
    stocks = old['stocks'] + [entry(c, n, sec, st, g, ch, memo, hq.get(c)) for c, n, sec, st, g, ch, memo in todo]
    out = {'note': '소비재 탭 종목 설정. consumer_draft.py 가 만든 초안 — 흐름의 basis: channel=수출입 채널 기록 근거, hq=본사 소재지(검수 전), national=전국 업황. '
                   'regions 는 "시도코드:시군구". 검수하면 reviewed 를 true 로.',
           'chains': CHAINS, 'stocks': stocks}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'consumer_assets.json: {len(stocks)}종목 (새로 {len(todo)}, 본사 주소 {len(hq)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
