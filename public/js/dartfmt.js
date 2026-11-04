// DART 공시 한 건을 화면 줄·복사용 글로 바꾼다 (공시 탭·홈·종목 패널 공통)
const DartFmt = (() => {
  const SECTIONS = [
    ['contract', '단일판매 · 공급계약체결', ['contract']],
    ['earn', '잠정실적 발표', ['earn']],
    ['biz', '투자판단 관련 주요경영사항', ['biz']],
    ['cancel', '주식소각결정', ['cancel']],
    ['buyback', '자기주식 취득', ['buyback', 'trust']],
    ['bond', '사채 발행결정 (CB · BW · EB)', ['cb', 'bw', 'eb']],
    ['rights', '유상 · 무상증자', ['rights', 'bonus']],
    ['holder', '최대주주 변경', ['holder']],
    ['invest', '타법인 주식 취득', ['invest']],
    ['dividend', '현금 · 현물배당', ['dividend']],
    ['contract_x', '공급계약 해지', ['contract_x']],
    ['ir', '실적발표 · 기업설명회 일정', ['ir', 'preview']],
  ];
  const KIND_LABEL = {
    contract: '공급계약', contract_x: '계약해지', earn: '잠정실적', biz: '주요경영사항', cancel: '주식소각',
    buyback: '자사주 취득', trust: '자사주 신탁', cb: '전환사채', bw: '신주인수권부사채', eb: '교환사채',
    rights: '유상증자', bonus: '무상증자', holder: '최대주주 변경', invest: '타법인 취득', dividend: '배당',
    ir: 'IR', preview: '실적 공시 예고',
  };
  const DOW = '일월화수목금토';

  const comma = v => Math.round(v).toLocaleString('ko-KR');
  // 억 단위 → 9조 2,037억 / 565억
  function eok(v) {
    if (v == null) return '–';
    const neg = v < 0, a = Math.abs(v);
    const jo = Math.floor(a / 10000), r = Math.round(a - jo * 10000);
    const s = jo ? `${comma(jo)}조${r ? ` ${comma(r)}억` : ''}` : `${comma(a)}억`;
    return neg ? `-${s}` : s;
  }
  const won = v => (v == null ? '–' : eok(v / 1e8));
  const dot = d => (d ? d.replace(/-/g, '.') : '–');
  const md = d => { const t = new Date(`${d}T00:00:00`); return `${t.getMonth() + 1}월 ${t.getDate()}일(${DOW[t.getDay()]})`; };
  const pct = (v, nd = 0) => `${v > 0 ? '+' : ''}${(v * 100).toFixed(nd)}%`;
  const clean = s => (s || '').replace(/\(주\)|주식회사|㈜/g, '').trim();
  const join = parts => parts.filter(p => p && !/: (–|null|undefined)$/.test(p)).join(' / ');

  // 잠정실적 한 항목: 영업이익 1,918(+5%) / 영업손실 263(예상 손실 257 대비 2% 확대)
  function earnPart(label, lossLabel, row, c, dd, missing) {
    const v = row?.v;
    if (v == null) return null;
    const name = v < 0 ? lossLabel : label;
    const n = Math.abs(v) < 1 ? Math.abs(v).toFixed(1) : comma(Math.abs(v));
    if (c == null) return `${name} ${n}${missing ? '(컨센서스 미기재)' : ''}`;
    if (v < 0 && c < 0) {
      const r = Math.round(Math.abs(dd) * 100);
      return `${name} ${comma(-v)}(예상 손실 ${comma(-c)} 대비 ${r}% ${v < c ? '확대' : '축소'})`;
    }
    if (v < 0 && c > 0) return `${name} ${comma(-v)}(컨센서스 ${label} ${comma(c)} 대비 적자)`;
    if (v > 0 && c < 0) return `${label} ${comma(v)}(예상 손실 ${comma(-c)} 대비 흑자)`;
    const r = Math.round(dd * 100);
    return `${name} ${comma(v)}(${Math.abs(r) <= 2 ? '약 부합' : `${r > 0 ? '+' : ''}${r}%`})`;
  }

  function earnLine(x) {
    const r = x.d.rows || {}, s = x.s?.mismatch ? null : x.s;
    const npRow = s?.np_basis === '지배' ? r.cnp : (r.np || r.cnp);
    const parts = [
      earnPart('매출', '매출', r.sales, s?.cns.sales, s?.d.sales, !!s && s.cns.op != null),
      earnPart('영업이익', '영업손실', r.op, s?.cns.op, s?.d.op),
      earnPart('순이익', '순손실', npRow, s?.cns.np, s?.d.np),
    ].filter(Boolean);
    return parts.join(' / ') + (x.s?.mismatch ? ' / 별도 실적이라 연결 컨센서스와 비교 안 함' : !s || s.cns.op == null ? ' / 컨센서스 미기재' : '');
  }

  // 종류별 본문 한 줄 (복사용 글과 화면이 같은 문장)
  function body(x) {
    const d = x.d || {};
    switch (x.k) {
      case 'contract':
        return join([`계약상대 : ${clean(d.party) || '–'}`, `계약내용 : ${d.name || '–'}`, d.region && `공급지역 : ${d.region}`,
          `계약금액 : ${won(d.amt)}`, d.start && `계약기간 : ${dot(d.start)}~${dot(d.end)}`, d.pct != null && `매출대비 : ${d.pct}%`]);
      case 'contract_x':
        return join([`계약상대 : ${clean(d.party) || '–'}`, `계약내용 : ${d.name || '–'}`, `해지금액 : ${won(d.amt)}`,
          d.pct != null && `매출대비 : ${d.pct}%`, d.reason && `사유 : ${d.reason}`]);
      case 'earn':
        return earnLine(x);
      case 'biz':
        return `${d.title || x.t}${d.body ? `\n${d.body.slice(0, 220)}${d.body.length > 220 ? '…' : ''}` : ''}`;
      case 'cancel':
        return join([`소각주식 : 보통주 ${d.shares ? comma(d.shares) : '–'}주`, `소각예정금액 : ${won(d.amt)}`,
          x.mc && d.amt && `시총대비 : ${(d.amt / 1e8 / x.mc * 100).toFixed(2)}%`, d.how && `취득방법 : ${d.how}`,
          d.date && `소각예정일 : ${dot(d.date)}`]);
      case 'buyback':
        return join([`취득예정 : 보통주 ${d.shares ? comma(d.shares) : '–'}주 · ${won(d.amt)}`,
          x.mc && d.amt && `시총대비 : ${(d.amt / 1e8 / x.mc * 100).toFixed(2)}%`,
          d.start && `기간 : ${dot(d.start)}~${dot(d.end)}`, d.how && `방법 : ${d.how}`]);
      case 'trust':
        return join([`신탁계약 : ${won(d.amt)}`, x.mc && d.amt && `시총대비 : ${(d.amt / 1e8 / x.mc * 100).toFixed(2)}%`,
          d.start && `기간 : ${dot(d.start)}~${dot(d.end)}`, d.broker && `계약기관 : ${d.broker}`]);
      case 'cb': case 'bw': case 'eb': {
        const lab = x.k === 'cb' ? '전환가액' : x.k === 'bw' ? '행사가액' : '교환가액';
        return join([`발행금액 : ${won(d.amt)}`, d.how && `발행방법 : ${d.how}`, d.price && `${lab} : ${comma(d.price)}원`,
          d.floor && `최저 조정가액 : ${comma(d.floor)}원`, d.cpn != null && `표면·만기이율 : ${d.cpn}%·${d.ytm ?? '–'}%`,
          d.pay && `납입일 : ${dot(d.pay)}`, d.from && `청구기간 : ${dot(d.from)}~${dot(d.to)}`,
          d.ratio != null && `주식총수 대비 : ${d.ratio}%`,
          d.investors?.length && `투자자 : ${d.investors.slice(0, 4).join(', ')}${d.investors.length > 4 ? ` 외 ${d.investors.length - 4}` : ''}`]);
      }
      case 'rights':
        return join([`신주 : ${d.common ? `보통주 ${comma(d.common)}주` : ''}${d.other ? `${d.common ? ' · ' : ''}기타주 ${comma(d.other)}주` : ''}` || '–',
          d.amt && `조달금액 : ${won(d.amt)}`, d.how && `방식 : ${d.how}`]);
      case 'bonus':
        return join([`신주 : 보통주 ${d.common ? comma(d.common) : '–'}주`, d.per && `1주당 ${d.per}주`, d.date && `배정기준일 : ${dot(d.date)}`]);
      case 'holder':
        return join([`변경 전 : ${d.before || '–'} ${d.before_pct ?? ''}%`, `변경 후 : ${d.after || '–'} ${d.after_pct ?? ''}%`,
          d.reason && `변경사유 : ${d.reason}`, d.why && `인수목적 : ${d.why}`]);
      case 'invest':
        return join([`대상 : ${d.target || '–'}`, `취득금액 : ${won(d.amt)}`, d.eq_pct != null && `자기자본대비 : ${d.eq_pct}%`,
          d.own_pct != null && `취득 후 지분 : ${d.own_pct}%`, d.why && `목적 : ${d.why}`]);
      case 'dividend':
        return join([d.type && `${d.type}`, `주당 ${d.dps ? comma(d.dps) : '–'}원`, d.yld != null && `시가배당률 ${d.yld}%`,
          d.date && `기준일 : ${dot(d.date)}`]);
      case 'ir':
        return join([`${dot(d.date)}${d.time ? ` ${d.time}` : ''}`, d.how, d.what]);
      case 'preview':
        return `${dot(d.date)} 실적 공시 예정${d.end ? ` (${d.end.slice(0, 7).replace('-', '.')} 결산)` : ''}`;
      default:
        return x.t;
    }
  }

  function tags(x) {
    const t = [];
    if (x.s?.tag) t.push(x.s.tag);
    if (x.ss) t.push(`${x.ss} 공시`);
    if (x.fx) t.push('정정');
    return t;
  }

  // 회사 (시총) - 태그
  const head = x => `${x.n} (${x.mc != null ? eok(x.mc) : '시총 –'})${tags(x).length ? ` - ${tags(x).join(' · ')}` : ''}`;

  // 섹션별로 묶은 글 (사용자 양식)
  function digest(day, items, schedule) {
    const out = [`[${md(day)} 주요 공시]`];
    for (const [, title, kinds] of SECTIONS) {
      const xs = items.filter(x => kinds.includes(x.k));
      if (!xs.length) continue;
      out.push('', `[${title}]`);
      for (const x of xs) out.push('', head(x), body(x));
    }
    const next = (schedule || []).filter(e => e.earn && e.date > day);
    if (next.length) {
      const d = next[0].date;
      out.push('', `[${md(d)} 실적발표 예정 종목]`, next.filter(e => e.date === d).map(e => e.n).join(', '));
    }
    return out.join('\n');
  }

  const dartUrl = no => `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${no}`;

  return { SECTIONS, KIND_LABEL, body, head, tags, digest, eok, won, md, dartUrl, pct };
})();
