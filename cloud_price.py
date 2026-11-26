# -*- coding: utf-8 -*-
"""
成都废料报价 · 云端定时版（供 GitHub Actions 运行）
=========================================================
每次运行：抓取中国废品网「成都」每日废料报价 -> 压缩成一条 JSON -> 写入 ntfy.sh。
手机打开那个固定网址（页面外壳只发一次）时，JS 去 ntfy 取最新一条显示。

本文件自包含，不依赖本机的任何其他文件。只依赖 requests。
"""

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse

import requests
import urllib3

urllib3.disable_warnings()  # 源站证书不合规，我们只读取公开报价，关掉噪音告警

# ---------------- 配置 ----------------
NTFY_API = 'https://ntfy.sh'
NTFY_TOPIC = 'scrap_price_sichuan_2026'   # 必须和页面外壳里的 topic 一致，别改
DATA_URL = f'{NTFY_API}/{NTFY_TOPIC}/json?poll=1&since=20h'
CN_TZ = dt.timezone(dt.timedelta(hours=8))

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'}
TIMEOUT = 40

SECTION_ORDER = ['废铜', '废铝', '废钢', '废不锈钢', '废铁', '废铅', '废锌', '废纸']
ACCENT = {'废铜': '#b45309', '废铝': '#0f766e', '废钢': '#0e7490', '废不锈钢': '#6d28d9',
          '废铁': '#78716c', '废铅': '#1d4ed8', '废锌': '#7c3aed', '废纸': '#059669'}


def log(*a):
    print(dt.datetime.now(CN_TZ).strftime('%m-%d %H:%M:%S'), *a, flush=True)


# ============================ 抓取解析（来自 scrap_sc_price.py） ============================

def fetch(url, referer=None, encoding=None):
    h = dict(HEADERS)
    if referer:
        h['Referer'] = referer
    try:
        r = requests.get(url, headers=h, timeout=TIMEOUT, verify=False)
        if r.status_code != 200:
            log('  fetch 非200:', r.status_code, url[:60])
            return None
        r.encoding = encoding or r.apparent_encoding or 'utf-8'
        return r.text
    except Exception as e:
        log('  fetch 失败:', type(e).__name__, url[:60])
        return None


def html_to_text(html):
    if not html:
        return ''
    b = re.sub(r'<script.*?</script>', ' ', html, flags=re.S | re.I)
    b = re.sub(r'<style.*?</style>', ' ', b, flags=re.S | re.I)
    b = re.sub(r'<[^>]+>', '', b)
    b = b.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&gt;', '>').replace('&lt;', '<')
    return re.sub(r'[ \t\r\n\u3000]+', '', b)


SC_REGIONS = ['四川', '成都', '绵阳', '德阳', '乐山', '泸州', '宜宾', '南充', '自贡',
              '内江', '遂宁', '眉山', '广元', '达州', '攀枝花', '雅安', '资阳', '西昌']
SC_REGIONS_SORTED = sorted(SC_REGIONS, key=len, reverse=True)


def match_sc_region(text):
    for reg in SC_REGIONS_SORTED:
        if text.startswith(reg):
            return reg
    return None


ITEM_RE = re.compile(
    r'^(?P<name>.*?)'
    r'(?P<low>\d+(?:\.\d+)?)'
    r'(?:\s*-\s*(?P<high>\d+(?:\.\d+)?))?'
    r'(?:(?P<dir>涨|跌)(?P<chg>\d+(?:\.\d+)?))?'
    r'(?:元/(?P<unit>公斤|千克|吨|基吨))?'
    r'$'
)


def parse_items(payload):
    items = []
    for raw in re.split(r'[，,；;]', payload):
        seg = raw.strip().strip('。').strip()
        if not seg:
            continue
        m = ITEM_RE.match(seg)
        if not m:
            continue
        low = float(m.group('low'))
        high = float(m.group('high')) if m.group('high') else low
        # 源站偶尔把价格区间写反（如「铝合金17700-17000」），低价高于高价时兜底交换
        if high < low:
            low, high = high, low
        items.append({
            'name': m.group('name').strip(' ：:'),
            'low': low, 'high': high,
            'dir': m.group('dir') or '',
            'chg': float(m.group('chg')) if m.group('chg') else None,
            'unit_raw': m.group('unit') or '',
        })
    return items


# ============================ 中国废品网 成都频道（主源，元/吨） ============================
# 成都本地每日报价专页，地区码 a=6002。列表页每日更新，需从中提取各品类最新文章 id。
ZGFP_LIST = ('https://www.zgfp.com/search/searchprice.aspx?page=1&ChannelId=8'
             '&cid=0&k=&w=&e=2&d=&a=6002')
ZGFP_VIEW = 'https://www.zgfp.com/price/View/{ch}/{aid}.htm'
ZGFP_CATS = [('废铜', 61, '铜'), ('废铝', 40, '铝'),
             ('废钢', 12, '钢'), ('废不锈钢', 39, '不锈钢')]
ZGFP_EXTRA = [('废铁', 14), ('废铅', 19), ('废锌', 17), ('废纸', 22)]
ZGFP_DATE_RE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')


def parse_zgfp_table(detail):
    """解析详情页 table 的 品种/最低价/最高价，返回统一条目 dict"""
    items = []
    for tr in re.findall(r'<TR[^>]*>(.*?)</TR>', detail, flags=re.S | re.I):
        cells = re.findall(r'<TD[^>]*>(.*?)</TD>', tr, flags=re.S | re.I)
        if len(cells) < 3:
            continue
        name = re.sub(r'<[^>]+>', '', cells[0]).strip()
        lo = re.sub(r'<[^>]+>', '', cells[1]).strip()
        hi = re.sub(r'<[^>]+>', '', cells[2]).strip()
        try:
            low, high = float(lo), float(hi)
        except ValueError:
            continue
        if not name or name in ('品种', '指数名称'):
            continue
        if high < low:
            low, high = high, low
        items.append({'name': name, 'low': low, 'high': high,
                      'dir': '', 'chg': None, 'unit_raw': '吨'})
    return items


def zgfp_chengdu(want_date=None):
    """返回 (rows, qdate, fallback, extra)。rows 带 section 字段，extra 是补充品类 dict。"""
    html = fetch(ZGFP_LIST, encoding='gbk')
    if not html:
        return [], None, True, {}
    pairs = re.findall(r'href="([^"]*price/View/(\d+)/(\d+)\.htm)"[^>]*>([^<]{4,60})', html)
    target = want_date or dt.datetime.now(CN_TZ).date()
    groups = {}
    for href, ch, aid, title in pairs:
        m = ZGFP_DATE_RE.search(title)
        if not m:
            continue
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d > target:
            continue
        groups.setdefault(d, []).append((ch, aid, title.strip()))
    if not groups:
        return [], None, True, {}
    qdate = max(groups)
    fallback = qdate < target
    by_ch = {}
    for ch, aid, title in groups[qdate]:
        by_ch.setdefault(ch, (aid, title))
    cat_map = {str(cid): (sec, metal) for sec, cid, metal in ZGFP_CATS}
    extra_map = {str(cid): sec for sec, cid in ZGFP_EXTRA}
    rows, extra = [], {}
    for ch, (aid, _title) in by_ch.items():
        detail = fetch(ZGFP_VIEW.format(ch=ch, aid=aid), encoding='gbk')
        if not detail:
            continue
        items = parse_zgfp_table(detail)
        if not items:
            continue
        if ch in cat_map:
            sec, metal = cat_map[ch]
            for it in items:
                rows.append(dict(section=sec, metal=metal, region='成都', **it))
        elif ch in extra_map:
            extra[extra_map[ch]] = items
    return rows, qdate, fallback, extra


FJ139_SEARCH = 'https://www.fj139.com/news/search.php?kw='
FJ139_ITEM = 'https://www.fj139.com/news/show.php?itemid={}'
FJ139_KW = '废金属行情调价汇总'
FJ139_SECTIONS = [
    ('废铜最新行情', '废铜', '铜'),
    ('废铝最新行情', '废铝', '铝'),
    ('废电瓶最新行情', '废电瓶', '铅'),
    ('废不锈钢最新行情', '废不锈钢', '不锈钢'),
]
NAME_ALLOW = {
    '废不锈钢': re.compile(
        r'^(?:成都)?(?:不锈|30[0-9]|31[0-9]|32[01]|20[0-2]|2520|2205|444|43[0-9]'
        r'|409|410|904L|17-4)'),
}
DATE_IN_TITLE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')


def name_allowed(section, name):
    pat = NAME_ALLOW.get(section)
    return True if pat is None else bool(pat.match(name))


def fj139_list_articles():
    html = fetch(FJ139_SEARCH + urllib.parse.quote(FJ139_KW), referer='https://www.fj139.com/')
    if not html:
        return []
    pairs = re.findall(r'href="[^"]*show\.php\?itemid=(\d+)"[^>]*>\s*([^<]{4,80})', html)
    seen, out = set(), []
    for iid, title in pairs:
        if iid in seen:
            continue
        seen.add(iid)
        m = DATE_IN_TITLE.search(title)
        if not m:
            continue
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        out.append((d, iid, title.strip()))
    out.sort(key=lambda x: (x[0], int(x[1])), reverse=True)
    return out


def fj139_pick_article(want_date=None):
    arts = fj139_list_articles()
    if not arts:
        return None
    target = want_date or dt.datetime.now(CN_TZ).date()
    cand = [a for a in arts if a[0] <= target]
    if not cand:
        return None
    d, iid, title = cand[0]
    return d, iid, title, (d == target)


def split_sections(text):
    marks = []
    for name, label, metal in FJ139_SECTIONS:
        p = text.find(name)
        if p >= 0:
            marks.append((p, name, label, metal))
    marks.sort(key=lambda x: x[0])
    segs = []
    for i, (p, name, label, metal) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        segs.append((label, metal, text[p + len(name):end]))
    return segs


def parse_fj139_sichuan(text):
    rows = []
    for label, metal, body in split_sections(text):
        for blk in re.findall(r'【[^】]{0,12}】(.*?)(?=【|$)', body, flags=re.S):
            blk = blk.strip()
            m = re.match(r'^(\d{1,2})月(\d{1,2})日(.*)$', blk, flags=re.S)
            if not m:
                continue
            rest = m.group(3).strip()
            region = match_sc_region(rest)
            if not region:
                continue
            for it in parse_items(rest[len(region):]):
                if not it['name'] or not name_allowed(label, it['name']):
                    continue
                rows.append(dict(section=label, metal=metal, region=region, **it))
    return rows


SD_LIST = 'http://sdjinshu.com/NewsInfoCategory?categoryId=26652,26652'
SD_BODY_JS = ('https://nwzimg.wezhan.cn/pubsf/10029/10029936/cdn-static-pages/newsinfo/pc/'
              '{itemid}_zh-cn.nocookie.html.Body.js')
SD_TITLE_RE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日各地废旧金属报价')


def sdjinshu_list():
    html = fetch(SD_LIST, referer='http://sdjinshu.com/')
    if not html:
        return []
    seen, out = set(), []
    for iid, title in re.findall(r'newsinfo/(\d+)\.html"[^>]*>([^<]{4,60})', html):
        if iid in seen:
            continue
        seen.add(iid)
        m = SD_TITLE_RE.search(title)
        if not m:
            continue
        out.append((dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                    iid, title.strip()))
    out.sort(key=lambda x: (x[0], int(x[1])), reverse=True)
    return out


def sdjinshu_chengdu(want_date=None):
    arts = sdjinshu_list()
    target = want_date or dt.datetime.now(CN_TZ).date()
    cand = [a for a in arts if a[0] <= target]
    if not cand:
        return None
    d, iid, title = cand[0]
    body = fetch(SD_BODY_JS.format(itemid=iid), referer='http://sdjinshu.com/')
    if not body:
        return None
    t = (body.replace('\\u003c', '<').replace('\\u003e', '>')
             .replace('\\"', '"').replace('\\r', '').replace('\\n', '\n'))
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'[ \t\u3000]+', ' ', t)
    out = {'date': d.isoformat(), 'cu_kg': {}, 'steel_per_t': {}}
    m = re.search(r'成都[：:]([^\n]{5,200})', t)
    if m:
        pat = r'([\u4e00-\u9fa5A-Za-z]{1,8}?)(\d+(?:\.\d+)?)(?=[\u4e00-\u9fa5A-Za-z]|\s|$)'
        for name, val in re.findall(pat, m.group(1)):
            out['cu_kg'][name] = float(val)
    for name, val in re.findall(r'(成都重废|成都钢板料|成都剪切料)(\d{3,5})', t):
        out['steel_per_t'][name] = float(val)
    return out


def sd_chengdu_rows(sd):
    """把山东金属网成都 dict 转成统一 rows。返回 (rows, qdate)。
    cu_kg 里含「铝」的归废铝，其余归废铜（元/公斤）；steel_per_t 归废钢（元/吨）。"""
    rows = []
    if not sd:
        return rows, None
    for name, val in (sd.get('cu_kg') or {}).items():
        sec = '废铝' if '铝' in name else '废铜'
        rows.append({'name': name, 'low': val, 'high': val, 'dir': '', 'chg': None,
                     'unit_raw': '公斤', 'section': sec, 'metal': sec[1:], 'region': '成都'})
    for name, val in (sd.get('steel_per_t') or {}).items():
        nm = name.replace('成都', '')
        rows.append({'name': nm, 'low': val, 'high': val, 'dir': '', 'chg': None,
                     'unit_raw': '吨', 'section': '废钢', 'metal': '钢', 'region': '成都'})
    qdate = None
    if sd.get('date'):
        try:
            qdate = dt.date.fromisoformat(sd['date'])
        except ValueError:
            qdate = None
    return rows, qdate


# ============================ 废金属资讯网 四川废铜废铝（主源，元/吨） ============================
# feijs.com 每日发布各省废铜废铝报价，数值真实新鲜（与沪铜/沪铝期货吻合）。
# 其列表页不可访问，文章 ID 连续递增，故用「指数探测最大 ID + 向前扫描标题」定位最新一篇四川文章。
FEIJS_VIEW = 'http://www.feijs.com/news/news_detail.asp?class=ftfl&id={id}'
FEIJS_SEED_ID = 901849  # 2026-11-26 四川文章，作为探测锚点（ID 只增不减，永久有效）
FEIJS_TITLE_RE = re.compile(r'font20s[^>]*>([^<]{4,80})', re.S)
FEIJS_DATE_RE = re.compile(r'(\d{4})/(\d{1,2})/(\d{1,2})')
FEIJS_BODY_RE = re.compile(r'<FONT[^>]*size=4[^>]*>(.*?)</DIV>', re.S | re.I)


def feijs_article(iid):
    """抓取指定 ID 的文章，返回 (title, qdate, body)；无效返回 None。"""
    html = fetch(FEIJS_VIEW.format(id=iid), encoding='gbk')
    if not html:
        return None
    tm = FEIJS_TITLE_RE.search(html)
    if not tm:
        return None
    title = tm.group(1).strip()
    qdate = None
    dm = FEIJS_DATE_RE.search(html)
    if dm:
        try:
            qdate = dt.date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            pass
    body = ''
    bm = FEIJS_BODY_RE.search(html)
    if bm:
        body = re.sub(r'<BR\s*/?>', '\n', bm.group(1), flags=re.I)
        body = re.sub(r'<[^>]+>', '', body).replace('&nbsp;', ' ').strip()
    return title, qdate, body


def feijs_max_id(seed=FEIJS_SEED_ID):
    """指数探测当前最大有效文章 ID。"""
    if not feijs_article(seed):
        for i in range(seed, max(1, seed - 200), -1):  # 锚点失效时向前找最近有效 ID
            if feijs_article(i):
                seed = i
                break
        else:
            return None
    hi, step, stall = seed, 16, 0
    while step >= 1 and stall < 3:
        if feijs_article(hi + step):
            hi += step
            step = min(step * 2, 8192)
            stall = 0
        else:
            step //= 2
            stall += 1
    return hi


def feijs_sichuan(want_date=None):
    """返回 (rows, qdate, fallback)。四川废铜废铝当日行情，单位元/吨。"""
    hi = feijs_max_id()
    if hi is None:
        return [], None, True
    target = want_date or dt.datetime.now(CN_TZ).date()
    found = None
    for iid in range(hi, max(1, hi - 120) - 1, -1):
        art = feijs_article(iid)
        if not art:
            continue
        title, qdate, body = art
        if '四川' in title and '废铜' in title:
            found = (qdate, body)
            break
    if not found:
        return [], None, True
    qdate, body = found
    rows = []
    for line in body.split('\n'):
        for it in parse_items(line.strip()):
            if not it['name']:
                continue
            sec = '废铝' if '铝' in it['name'] else '废铜'
            rows.append(dict(section=sec, metal=sec[1:], region='四川', **it))
    return rows, qdate, (qdate is not None and qdate < target)


SINA_URL = ('https://hq.sinajs.cn/list=nf_CU0,nf_AL0,nf_ZN0,nf_PB0,nf_NI0,nf_SN0,'
            'nf_AU0,nf_AG0,nf_RB0,nf_SS0,nf_HC0,nf_I0')
FUT_NAMES = {
    'CU': ('沪铜', '吨'), 'AL': ('沪铝', '吨'), 'ZN': ('沪锌', '吨'), 'PB': ('沪铅', '吨'),
    'NI': ('沪镍', '吨'), 'SN': ('沪锡', '吨'), 'AU': ('黄金', '克'), 'AG': ('白银', '千克'),
    'RB': ('螺纹钢', '吨'), 'SS': ('不锈钢', '吨'), 'HC': ('热卷', '吨'), 'I': ('铁矿石', '吨'),
}


def fetch_futures():
    txt = fetch(SINA_URL, referer='https://finance.sina.com.cn', encoding='gbk')
    if not txt:
        return []
    rows = []
    for line in txt.split(';'):
        m = re.search(r'hq_str_nf_([A-Z]{1,2})0="([^"]*)"', line)
        if not m:
            continue
        code = m.group(1)
        parts = m.group(2).split(',')
        if len(parts) < 18:
            continue
        try:
            last = float(parts[8])
            prev = float(parts[10]) if parts[10] else 0.0
        except ValueError:
            continue
        nm, unit = FUT_NAMES.get(code, (parts[16] if len(parts) > 16 else code, '吨'))
        chg = round(last - prev, 2) if prev else None
        pct = round(chg / prev * 100, 2) if prev else None
        rows.append({'name': nm, 'last': last, 'chg': chg, 'pct': pct, 'unit': unit})
    return rows


def to_kg(values, unit_raw, section):
    if unit_raw in ('公斤', '千克'):
        return values
    if unit_raw == '基吨':
        return [None for _ in values]
    return [round(v / 1000, 3) if v is not None else None for v in values]


# ============================ 组装 + 推送 ntfy ============================

def build_payload(rows, qdate, fallback, futures, low_src=None):
    """把成都条目压成前端要用的纯 JSON（体积压到 ntfy 单条上限内）。
    low_src：由 zgfp（过期偏低）来源填充的板块名集合，前端据此打「数值偏低」标签。"""
    low_src = low_src or set()
    grouped = {}
    for r in rows:
        kg = to_kg([r['low'], r['high']], r['unit_raw'], r['section'])
        o = {'name': r['name'], 'low': kg[0], 'high': kg[1]}
        # 元/吨前端可由元/公斤×1000 推出，不重复传；成都源也没有涨跌字段
        if r.get('dir') or r.get('chg') is not None:
            chg_kg = r['chg'] / 1000 if r['unit_raw'] not in ('公斤', '千克') else r['chg']
            o['dir'] = r['dir']
            o['chg'] = chg_kg
        grouped.setdefault(r['section'], []).append(o)
    secs = []
    for sec in SECTION_ORDER:
        items = grouped.get(sec) or []
        if not items:
            continue
        secs.append({'name': sec, 'accent': ACCENT.get(sec, '#1f3b57'),
                     'rows': items, 'low': sec in low_src})
    return {
        'quote_date': qdate.strftime('%Y-%m-%d') if qdate else '',
        'is_fallback': bool(fallback),
        'fetched_at': dt.datetime.now(CN_TZ).strftime('%m-%d %H:%M'),
        'sections': secs,
        'chengdu': {'date': '', 'cu': [], 'steel': []},
        'futures': futures,
    }


def last_good_payload():
    """从 ntfy 读回上一条含完整 sections 的数据，供云端抓不到废料时续期。
    找不到返回 None。"""
    # 必须带 poll=1：ntfy 的 /json 端点只有 poll=1 才立即返回历史消息，否则会挂住等新消息
    read_url = f'{NTFY_API}/{NTFY_TOPIC}/json?poll=1&since=20h'
    for attempt in range(3):
        try:
            r = requests.get(read_url, headers={'User-Agent': UA}, timeout=25)
            if r.status_code != 200:
                log('  读回 ntfy 非200:', r.status_code)
                time.sleep(3)
                continue
            lines = [x for x in r.text.split('\n') if x.strip()]
            for line in reversed(lines):
                try:
                    o = json.loads(line)
                    p = json.loads(o.get('message', '{}'))
                    if p.get('sections'):
                        log('  找到上一条完整数据，报价日:', p.get('quote_date', ''))
                        return p
                except Exception:
                    continue
            return None  # 有响应但没有完整数据
        except Exception as e:
            log('  读回 ntfy 失败，重试', attempt + 1, type(e).__name__, str(e)[:50])
            time.sleep(3)
    return None


def publish(body):
    last = ''
    for attempt in range(3):
        try:
            r = requests.post(f'{NTFY_API}/{NTFY_TOPIC}', data=body,
                              headers={'User-Agent': 'Mozilla/5.0',
                                       'Content-Type': 'application/json'},
                              timeout=40)
            if r.status_code == 200:
                rid = (r.json() or {}).get('id', '')
                return rid
            last = f'HTTP {r.status_code}: {r.text[:100]}'
        except Exception as e:
            last = f'{type(e).__name__}: {str(e)[:80]}'
        log('  写入重试', attempt + 1, last)
        time.sleep(3)
    raise RuntimeError(f'数据没写进去（{last}）')


# 一天只在两个时段真正写入 ntfy，其余定时运行直接跳过，避免 ntfy 匿名配额超限（HTTP 429）导致停更。
# 时段按北京时间，窗口放宽以容纳 GitHub Actions 定时漂移，并对应现有 cron 的 00:00Z / 10:00Z：
#   07:00–10:30 —— 早间，取最近一期行情（当天未发布时页面会提示「当日报价尚未发布」）
#   17:00–20:00 —— 傍晚，源站当日行情通常 13:00 前后发布，此时已是当天真实价
# 写入窗口只覆盖 5 个 cron 中的 08:00 与 18:00 两次；
# 手动触发若想强制写入，把环境变量 FORCE_PUBLISH 设为 1 即可绕过窗口与去重。
PUBLISH_WINDOWS = ((7 * 60, 10 * 60 + 30), (17 * 60, 20 * 60))


def in_publish_window(now=None):
    now = now or dt.datetime.now(CN_TZ)
    mins = now.hour * 60 + now.minute
    return any(a <= mins <= b for a, b in PUBLISH_WINDOWS)


def published_this_window_today():
    """读回 ntfy，若今天同一发布时段已写过一次则跳过，防止定时任务重复触发多写。"""
    read_url = f'{NTFY_API}/{NTFY_TOPIC}/json?poll=1&since=36h'
    try:
        r = requests.get(read_url, headers={'User-Agent': UA}, timeout=25)
        if r.status_code != 200:
            return False
        today = dt.datetime.now(CN_TZ).date()
        for line in reversed([x for x in r.text.split('\n') if x.strip()]):
            try:
                o = json.loads(line)
                ts = o.get('time')
                if not ts:
                    continue
                t = dt.datetime.fromtimestamp(int(ts), CN_TZ)
                if t.date() != today:
                    break
                mins = t.hour * 60 + t.minute
                if any(a <= mins <= b for a, b in PUBLISH_WINDOWS):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def main():
    if os.environ.get('FORCE_PUBLISH') != '1':
        if not in_publish_window():
            log('=== 跳过：不在发布时段（每天仅北京 08:00 / 18:00 写入）===')
            return
        if published_this_window_today():
            log('=== 跳过：当前时段今天已写入过，避免重复消耗 ntfy 配额 ===')
            return
    log('=== 开始抓取（云端）===')
    # 数据源策略：
    #   废金属资讯网(feijs) —— 四川废铜/废铝，数值真实新鲜（与沪铜/沪铝期货吻合），主源
    #   zgfp —— 品类齐全但报价过期偏低，仅用于补 钢/不锈钢/铁/铅/锌/纸，并在页面标注「偏低」
    #   旧主源「山东金属网」已失效（404），不再使用。
    zg_rows, zg_qdate, zg_fallback, extra = zgfp_chengdu()
    fj_rows, fj_qdate, fj_fallback = feijs_sichuan()

    low_src = set()
    rows = []
    if fj_rows:
        rows.extend(fj_rows)                       # 真实四川废铜/废铝行情
        qdate, fallback = (fj_qdate or zg_qdate), fj_fallback
        for r in zg_rows:                          # 钢等非铜铝品类仍取 zgfp，标偏低
            if r['section'] in ('废铜', '废铝'):
                continue
            rows.append(r)
            low_src.add(r['section'])
    else:
        rows = list(zg_rows)                       # feijs 没抓到，退回 zgfp（全部偏低）
        qdate, fallback = zg_qdate, zg_fallback
        low_src.update(r['section'] for r in rows)
    # 补充品类（废铁/铅/锌/纸）来自 zgfp，标注偏低
    for sec, items in extra.items():
        for it in items:
            rows.append(dict(section=sec, metal=sec, region='成都', **it))
            low_src.add(sec)
    log('  成都条目数:', len(rows), '(feijs行情:', len(fj_rows),
        '/ zgfp补充:', len(rows) - len(fj_rows), ') 报价日:', qdate, '偏低板块:', sorted(low_src))

    futures = fetch_futures()
    log('  期货条数:', len(futures))

    if not rows:
        # 云端偶尔被源站限流，抓不到废料时绝不能写空数据覆盖页面。
        # 策略：读回 ntfy 上一条完整数据，续上保留期（顺带刷新期货和时间）。
        log('!! 没抓到废料数据，尝试复用上一条完整数据续期')
        prev = last_good_payload()
        if prev is None:
            log('!! 也没有可复用的历史数据，放弃写入（保持页面原样）')
            sys.exit(1)
        if futures:
            prev['futures'] = futures
        prev['fetched_at'] = dt.datetime.now(CN_TZ).strftime('%m-%d %H:%M')
        payload = prev
    else:
        payload = build_payload(rows, qdate, fallback, futures, low_src)

    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    log('  数据大小:', len(body), '字节')
    if len(body) > 4000:
        log('!! 超过 ntfy 单条上限')
        sys.exit(1)

    rid = publish(body)
    # 写入成功后把 ntfy 上早于当天的旧消息清理掉（ntfy 支持按 id 删除），
    # 防止页面取数时历史消息混入。
    try:
        read_url = f'{NTFY_API}/{NTFY_TOPIC}/json?poll=1&since=48h'
        rr = requests.get(read_url, headers={'User-Agent': UA}, timeout=25)
        if rr.status_code == 200:
            today = dt.datetime.now(CN_TZ).date()
            for line in rr.text.split('\n'):
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                    ts = o.get('time')
                    if ts and dt.datetime.fromtimestamp(int(ts), CN_TZ).date() < today:
                        requests.delete(f'{NTFY_API}/{NTFY_TOPIC}/{o["id"]}',
                                        headers={'User-Agent': UA}, timeout=15)
                except Exception:
                    continue
    except Exception:
        pass
    log('写入成功，消息 id =', rid)
    log('数据地址 =', DATA_URL)
    log('=== 完成 ===')


if __name__ == '__main__':
    main()
