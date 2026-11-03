"""
수집 대상 종목 목록

KRX 일별 데이터(price_daily)의 가장 최근 거래일 보통주를 시총순으로 쓴다.
아직 가격 수집 전이면 기존 stock-dashboard DB의 stocks 테이블로 대체한다.
"""

import os
import sqlite3
from pathlib import Path
from typing import Dict, List

import db

LEGACY_DB = Path(os.environ.get('LEGACY_STOCK_DB',
                                Path.home() / 'stock-dashboard' / 'db' / 'dashboard.db'))


def is_common(code: str) -> bool:
    """보통주 = 6자리 + 끝자리 0 (우선주는 5, 7, 9, K 등)"""
    return len(code) == 6 and code[5] == '0'


def load_universe(min_mcap_eok: float = 0) -> List[Dict]:
    """[{'code', 'name', 'market_cap'(억원)}] 시총 내림차순. 우선주 제외."""
    conn = db.connect()
    rows = conn.execute(
        """SELECT code, name, mcap AS market_cap FROM price_daily
           WHERE date = (SELECT MAX(date) FROM price_daily)
           ORDER BY mcap DESC""").fetchall()
    conn.close()
    if rows:
        return [dict(r) for r in rows if is_common(r['code']) and r['market_cap'] >= min_mcap_eok]
    return _load_legacy(min_mcap_eok)


def _load_legacy(min_mcap_eok: float) -> List[Dict]:
    conn = sqlite3.connect(f'file:{LEGACY_DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT code, name, market_cap FROM stocks
           WHERE market != 'US' AND COALESCE(is_etf, 0) = 0
           ORDER BY market_cap DESC""").fetchall()
    conn.close()
    out = []
    for r in rows:
        mcap = (r['market_cap'] or 0) / 1e8
        if is_common(r['code']) and mcap >= min_mcap_eok:
            out.append({'code': r['code'], 'name': r['name'], 'market_cap': mcap})
    return out
