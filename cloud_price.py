# -*- coding: utf-8 -*-
"""
鎴愰兘搴熸枡鎶ヤ环 路 浜戠瀹氭椂鐗堬紙渚?GitHub Actions 杩愯锛?
=========================================================
姣忔杩愯锛氭姄鍙栦腑鍥藉簾鍝佺綉銆屾垚閮姐€嶆瘡鏃ュ簾鏂欐姤浠?-> 鍘嬬缉鎴愪竴鏉?JSON -> 鍐欏叆 ntfy.sh銆?
鎵嬫満鎵撳紑閭ｄ釜鍥哄畾缃戝潃锛堥〉闈㈠澹冲彧鍙戜竴娆★級鏃讹紝JS 鍘?ntfy 鍙栨渶鏂颁竴鏉℃樉绀恒€?

鏈枃浠惰嚜鍖呭惈锛屼笉渚濊禆鏈満鐨勪换浣曞叾浠栨枃浠躲€傚彧渚濊禆 requests銆?
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

urllib3.disable_warnings()  # 婧愮珯璇佷功涓嶅悎瑙勶紝鎴戜滑鍙鍙栧叕寮€鎶ヤ环锛屽叧鎺夊櫔闊冲憡璀?

# ---------------- 閰嶇疆 ----------------
NTFY_API = 'https://ntfy.sh'
NTFY_TOPIC = 'scrap_price_sichuan_2026'   # 蹇呴』鍜岄〉闈㈠澹抽噷鐨?topic 涓€鑷达紝鍒敼
DATA_URL = f'{NTFY_API}/{NTFY_TOPIC}/json?poll=1&since=20h'
CN_TZ = dt.timezone(dt.timedelta(hours=8))

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'}
TIMEOUT = 40

SECTION_ORDER = ['搴熼摐', '搴熼摑', '搴熼挗', '搴熶笉閿堥挗', '搴熼搧', '搴熼搮', '搴熼攲', '搴熺焊']
ACCENT = {'搴熼摐': '#b45309', '搴熼摑': '#0f766e', '搴熼挗': '#0e7490', '搴熶笉閿堥挗': '#6d28d9',
          '搴熼搧': '#78716c', '搴熼搮': '#1d4ed8', '搴熼攲': '#7c3aed', '搴熺焊': '#059669'}


def log(*a):
    print(dt.datetime.now(CN_TZ).strftime('%m-%d %H:%M:%S'), *a, flush=True)


# ============================ 鎶撳彇瑙ｆ瀽锛堟潵鑷?scrap_sc_price.py锛?============================

def fetch(url, referer=None, encoding=None):
    h = dict(HEADERS)
    if referer:
        h['Referer'] = referer
    try:
        r = requests.get(url, headers=h, timeout=TIMEOUT, verify=False)
        if r.status_code != 200:
            log('  fetch 闈?00:', r.status_code, url[:60])
            return None
        r.encoding = encoding or r.apparent_encoding or 'utf-8'
        return r.text
    except Exception as e:
        log('  fetch 澶辫触:', type(e).__name__, url[:60])
        return None


def html_to_text(html):
    if not html:
        return ''
    b = re.sub(r'<script.*?</script>', ' ', html, flags=re.S | re.I)
    b = re.sub(r'<style.*?</style>', ' ', b, flags=re.S | re.I)
    b = re.sub(r'<[^>]+>', '', b)
    b = b.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&gt;', '>').replace('&lt;', '<')
    return re.sub(r'[ \t\r\n\u3000]+', '', b)


SC_REGIONS = ['鍥涘窛', '鎴愰兘', '缁甸槼', '寰烽槼', '涔愬北', '娉稿窞', '瀹滃', '鍗楀厖', '鑷础',
              '鍐呮睙', '閬傚畞', '鐪夊北', '骞垮厓', '杈惧窞', '鏀€鏋濊姳', '闆呭畨', '璧勯槼', '瑗挎槍']
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
    r'(?:(?P<dir>娑▅璺?(?P<chg>\d+(?:\.\d+)?))?'
    r'(?:鍏?(?P<unit>鍏枻|鍗冨厠|鍚▅鍩哄惃))?'
    r'$'
)


def parse_items(payload):
    items = []
    for raw in re.split(r'[锛?锛?]', payload):
        seg = raw.strip().strip('銆?).strip()
        if not seg:
            continue
        m = ITEM_RE.match(seg)
        if not m:
            continue
        low = float(m.group('low'))
        high = float(m.group('high')) if m.group('high') else low
        # 婧愮珯鍋跺皵鎶婁环鏍煎尯闂村啓鍙嶏紙濡傘€岄摑鍚堥噾17700-17000銆嶏級锛屼綆浠烽珮浜庨珮浠锋椂鍏滃簳浜ゆ崲
        if high < low:
            low, high = high, low
        items.append({
            'name': m.group('name').strip(' 锛?'),
            'low': low, 'high': high,
            'dir': m.group('dir') or '',
            'chg': float(m.group('chg')) if m.group('chg') else None,
            'unit_raw': m.group('unit') or '',
        })
    return items


# ============================ 涓浗搴熷搧缃?鎴愰兘棰戦亾锛堜富婧愶紝鍏?鍚級 ============================
# 鎴愰兘鏈湴姣忔棩鎶ヤ环涓撻〉锛屽湴鍖虹爜 a=6002銆傚垪琛ㄩ〉姣忔棩鏇存柊锛岄渶浠庝腑鎻愬彇鍚勫搧绫绘渶鏂版枃绔?id銆?
ZGFP_LIST = ('https://www.zgfp.com/search/searchprice.aspx?page=1&ChannelId=8'
             '&cid=0&k=&w=&e=2&d=&a=6002')
ZGFP_VIEW = 'https://www.zgfp.com/price/View/{ch}/{aid}.htm'
ZGFP_CATS = [('搴熼摐', 61, '閾?), ('搴熼摑', 40, '閾?),
             ('搴熼挗', 12, '閽?), ('搴熶笉閿堥挗', 39, '涓嶉攬閽?)]
ZGFP_EXTRA = [('搴熼搧', 14), ('搴熼搮', 19), ('搴熼攲', 17), ('搴熺焊', 22)]
ZGFP_DATE_RE = re.compile(r'(\d{4})骞?\d{1,2})鏈?\d{1,2})鏃?)


def parse_zgfp_table(detail):
    """瑙ｆ瀽璇︽儏椤?table 鐨?鍝佺/鏈€浣庝环/鏈€楂樹环锛岃繑鍥炵粺涓€鏉＄洰 dict"""
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
        if not name or name in ('鍝佺', '鎸囨暟鍚嶇О'):
            continue
        if high < low:
            low, high = high, low
        items.append({'name': name, 'low': low, 'high': high,
                      'dir': '', 'chg': None, 'unit_raw': '鍚?})
    return items


def zgfp_chengdu(want_date=None):
    """杩斿洖 (rows, qdate, fallback, extra)銆俽ows 甯?section 瀛楁锛宔xtra 鏄ˉ鍏呭搧绫?dict銆?""
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
                rows.append(dict(section=sec, metal=metal, region='鎴愰兘', **it))
        elif ch in extra_map:
            extra[extra_map[ch]] = items
    return rows, qdate, fallback, extra


FJ139_SEARCH = 'https://www.fj139.com/news/search.php?kw='
FJ139_ITEM = 'https://www.fj139.com/news/show.php?itemid={}'
FJ139_KW = '搴熼噾灞炶鎯呰皟浠锋眹鎬?
FJ139_SECTIONS = [
    ('搴熼摐鏈€鏂拌鎯?, '搴熼摐', '閾?),
    ('搴熼摑鏈€鏂拌鎯?, '搴熼摑', '閾?),
    ('搴熺數鐡舵渶鏂拌鎯?, '搴熺數鐡?, '閾?),
    ('搴熶笉閿堥挗鏈€鏂拌鎯?, '搴熶笉閿堥挗', '涓嶉攬閽?),
]
NAME_ALLOW = {
    '搴熶笉閿堥挗': re.compile(
        r'^(?:鎴愰兘)?(?:涓嶉攬|30[0-9]|31[0-9]|32[01]|20[0-2]|2520|2205|444|43[0-9]'
        r'|409|410|904L|17-4)'),
}
DATE_IN_TITLE = re.compile(r'(\d{4})骞?\d{1,2})鏈?\d{1,2})鏃?)


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
        for blk in re.findall(r'銆怺^銆慮{0,12}銆?.*?)(?=銆恷$)', body, flags=re.S):
            blk = blk.strip()
            m = re.match(r'^(\d{1,2})鏈?\d{1,2})鏃?.*)$', blk, flags=re.S)
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
SD_TITLE_RE = re.compile(r'(\d{4})骞?\d{1,2})鏈?\d{1,2})鏃ュ悇鍦板簾鏃ч噾灞炴姤浠?)


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
    m = re.search(r'鎴愰兘[锛?]([^\n]{5,200})', t)
    if m:
        pat = r'([\u4e00-\u9fa5A-Za-z]{1,8}?)(\d+(?:\.\d+)?)(?=[\u4e00-\u9fa5A-Za-z]|\s|$)'
        for name, val in re.findall(pat, m.group(1)):
            out['cu_kg'][name] = float(val)
    for name, val in re.findall(r'(鎴愰兘閲嶅簾|鎴愰兘閽㈡澘鏂檤鎴愰兘鍓垏鏂?(\d{3,5})', t):
        out['steel_per_t'][name] = float(val)
    return out


def sd_chengdu_rows(sd):
    """鎶婂北涓滈噾灞炵綉鎴愰兘 dict 杞垚缁熶竴 rows銆傝繑鍥?(rows, qdate)銆?
    cu_kg 閲屽惈銆岄摑銆嶇殑褰掑簾閾濓紝鍏朵綑褰掑簾閾滐紙鍏?鍏枻锛夛紱steel_per_t 褰掑簾閽紙鍏?鍚級銆?""
    rows = []
    if not sd:
        return rows, None
    for name, val in (sd.get('cu_kg') or {}).items():
        sec = '搴熼摑' if '閾? in name else '搴熼摐'
        rows.append({'name': name, 'low': val, 'high': val, 'dir': '', 'chg': None,
                     'unit_raw': '鍏枻', 'section': sec, 'metal': sec[1:], 'region': '鎴愰兘'})
    for name, val in (sd.get('steel_per_t') or {}).items():
        nm = name.replace('鎴愰兘', '')
        rows.append({'name': nm, 'low': val, 'high': val, 'dir': '', 'chg': None,
                     'unit_raw': '鍚?, 'section': '搴熼挗', 'metal': '閽?, 'region': '鎴愰兘'})
    qdate = None
    if sd.get('date'):
        try:
            qdate = dt.date.fromisoformat(sd['date'])
        except ValueError:
            qdate = None
    return rows, qdate


# ============================ 搴熼噾灞炶祫璁綉 鍥涘窛搴熼摐搴熼摑锛堜富婧愶紝鍏?鍚級 ============================
# feijs.com 姣忔棩鍙戝竷鍚勭渷搴熼摐搴熼摑鎶ヤ环锛屾暟鍊肩湡瀹炴柊椴滐紙涓庢勃閾?娌摑鏈熻揣鍚诲悎锛夈€?
# 鍏跺垪琛ㄩ〉涓嶅彲璁块棶锛屾枃绔?ID 杩炵画閫掑锛屾晠鐢ㄣ€屾寚鏁版帰娴嬫渶澶?ID + 鍚戝墠鎵弿鏍囬銆嶅畾浣嶆渶鏂颁竴绡囧洓宸濇枃绔犮€?
FEIJS_VIEW = 'http://www.feijs.com/news/news_detail.asp?class=ftfl&id={id}'
FEIJS_SEED_ID = 901849  # 2026-11-26 鍥涘窛鏂囩珷锛屼綔涓烘帰娴嬮敋鐐癸紙ID 鍙涓嶅噺锛屾案涔呮湁鏁堬級
FEIJS_TITLE_RE = re.compile(r'font20s[^>]*>([^<]{4,80})', re.S)
FEIJS_DATE_RE = re.compile(r'(\d{4})/(\d{1,2})/(\d{1,2})')
FEIJS_BODY_RE = re.compile(r'<FONT[^>]*size=4[^>]*>(.*?)</DIV>', re.S | re.I)


def feijs_article(iid):
    """鎶撳彇鎸囧畾 ID 鐨勬枃绔狅紝杩斿洖 (title, qdate, body)锛涙棤鏁堣繑鍥?None銆?""
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
    """鎸囨暟鎺㈡祴褰撳墠鏈€澶ф湁鏁堟枃绔?ID銆?""
    if not feijs_article(seed):
        for i in range(seed, max(1, seed - 200), -1):  # 閿氱偣澶辨晥鏃跺悜鍓嶆壘鏈€杩戞湁鏁?ID
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
    """杩斿洖 (rows, qdate, fallback)銆傚洓宸濆簾閾滃簾閾濆綋鏃ヨ鎯咃紝鍗曚綅鍏?鍚ㄣ€?""
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
        if '鍥涘窛' in title and '搴熼摐' in title:
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
            sec = '搴熼摑' if '閾? in it['name'] else '搴熼摐'
            rows.append(dict(section=sec, metal=sec[1:], region='鍥涘窛', **it))
    return rows, qdate, (qdate is not None and qdate < target)


SINA_URL = ('https://hq.sinajs.cn/list=nf_CU0,nf_AL0,nf_ZN0,nf_PB0,nf_NI0,nf_SN0,'
            'nf_AU0,nf_AG0,nf_RB0,nf_SS0,nf_HC0,nf_I0')
FUT_NAMES = {
    'CU': ('娌摐', '鍚?), 'AL': ('娌摑', '鍚?), 'ZN': ('娌攲', '鍚?), 'PB': ('娌搮', '鍚?),
    'NI': ('娌晬', '鍚?), 'SN': ('娌敗', '鍚?), 'AU': ('榛勯噾', '鍏?), 'AG': ('鐧介摱', '鍗冨厠'),
    'RB': ('铻虹汗閽?, '鍚?), 'SS': ('涓嶉攬閽?, '鍚?), 'HC': ('鐑嵎', '鍚?), 'I': ('閾佺熆鐭?, '鍚?),
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
        nm, unit = FUT_NAMES.get(code, (parts[16] if len(parts) > 16 else code, '鍚?))
        chg = round(last - prev, 2) if prev else None
        pct = round(chg / prev * 100, 2) if prev else None
        rows.append({'name': nm, 'last': last, 'chg': chg, 'pct': pct, 'unit': unit})
    return rows


def to_kg(values, unit_raw, section):
    if unit_raw in ('鍏枻', '鍗冨厠'):
        return values
    if unit_raw == '鍩哄惃':
        return [None for _ in values]
    return [round(v / 1000, 3) if v is not None else None for v in values]


# ============================ 缁勮 + 鎺ㄩ€?ntfy ============================

def build_payload(rows, qdate, fallback, futures, low_src=None):
    """鎶婃垚閮芥潯鐩帇鎴愬墠绔鐢ㄧ殑绾?JSON锛堜綋绉帇鍒?ntfy 鍗曟潯涓婇檺鍐咃級銆?
    low_src锛氱敱 zgfp锛堣繃鏈熷亸浣庯級鏉ユ簮濉厖鐨勬澘鍧楀悕闆嗗悎锛屽墠绔嵁姝ゆ墦銆屾暟鍊煎亸浣庛€嶆爣绛俱€?""
    low_src = low_src or set()
    grouped = {}
    for r in rows:
        kg = to_kg([r['low'], r['high']], r['unit_raw'], r['section'])
        o = {'name': r['name'], 'low': kg[0], 'high': kg[1]}
        # 鍏?鍚ㄥ墠绔彲鐢卞厓/鍏枻脳1000 鎺ㄥ嚭锛屼笉閲嶅浼狅紱鎴愰兘婧愪篃娌℃湁娑ㄨ穼瀛楁
        if r.get('dir') or r.get('chg') is not None:
            chg_kg = r['chg'] / 1000 if r['unit_raw'] not in ('鍏枻', '鍗冨厠') else r['chg']
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
    """浠?ntfy 璇诲洖涓婁竴鏉″惈瀹屾暣 sections 鐨勬暟鎹紝渚涗簯绔姄涓嶅埌搴熸枡鏃剁画鏈熴€?
    鎵句笉鍒拌繑鍥?None銆?""
    # 蹇呴』甯?poll=1锛歯tfy 鐨?/json 绔偣鍙湁 poll=1 鎵嶇珛鍗宠繑鍥炲巻鍙叉秷鎭紝鍚﹀垯浼氭寕浣忕瓑鏂版秷鎭?
    read_url = f'{NTFY_API}/{NTFY_TOPIC}/json?poll=1&since=20h'
    for attempt in range(3):
        try:
            r = requests.get(read_url, headers={'User-Agent': UA}, timeout=25)
            if r.status_code != 200:
                log('  璇诲洖 ntfy 闈?00:', r.status_code)
                time.sleep(3)
                continue
            lines = [x for x in r.text.split('\n') if x.strip()]
            for line in reversed(lines):
                try:
                    o = json.loads(line)
                    p = json.loads(o.get('message', '{}'))
                    if p.get('sections'):
                        log('  鎵惧埌涓婁竴鏉″畬鏁存暟鎹紝鎶ヤ环鏃?', p.get('quote_date', ''))
                        return p
                except Exception:
                    continue
            return None  # 鏈夊搷搴斾絾娌℃湁瀹屾暣鏁版嵁
        except Exception as e:
            log('  璇诲洖 ntfy 澶辫触锛岄噸璇?, attempt + 1, type(e).__name__, str(e)[:50])
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
        log('  鍐欏叆閲嶈瘯', attempt + 1, last)
        time.sleep(3)
    raise RuntimeError(f'鏁版嵁娌″啓杩涘幓锛坽last}锛?)


# 涓€澶╁彧鍦ㄤ袱涓椂娈电湡姝ｅ啓鍏?ntfy锛屽叾浣欏畾鏃惰繍琛岀洿鎺ヨ烦杩囷紝閬垮厤 ntfy 鍖垮悕閰嶉瓒呴檺锛圚TTP 429锛夊鑷村仠鏇淬€?
# 鏃舵鎸夊寳浜椂闂达紝绐楀彛鏀惧浠ュ绾?GitHub Actions 瀹氭椂婕傜Щ锛屽苟瀵瑰簲鐜版湁 cron 鐨?00:00Z / 10:00Z锛?
#   07:00鈥?0:30 鈥斺€?鏃╅棿锛屽彇鏈€杩戜竴鏈熻鎯咃紙褰撳ぉ鏈彂甯冩椂椤甸潰浼氭彁绀恒€屽綋鏃ユ姤浠峰皻鏈彂甯冦€嶏級
#   17:00鈥?0:00 鈥斺€?鍌嶆櫄锛屾簮绔欏綋鏃ヨ鎯呴€氬父 13:00 鍓嶅悗鍙戝竷锛屾鏃跺凡鏄綋澶╃湡瀹炰环
# 鍐欏叆绐楀彛鍙鐩?5 涓?cron 涓殑 08:00 涓?18:00 涓ゆ锛?
# 鎵嬪姩瑙﹀彂鑻ユ兂寮哄埗鍐欏叆锛屾妸鐜鍙橀噺 FORCE_PUBLISH 璁句负 1 鍗冲彲缁曡繃绐楀彛涓庡幓閲嶃€?
PUBLISH_WINDOWS = ((7 * 60, 10 * 60 + 30), (17 * 60, 20 * 60))


def in_publish_window(now=None):
    now = now or dt.datetime.now(CN_TZ)
    mins = now.hour * 60 + now.minute
    return any(a <= mins <= b for a, b in PUBLISH_WINDOWS)


def published_this_window_today():
    """璇诲洖 ntfy锛岃嫢浠婂ぉ鍚屼竴鍙戝竷鏃舵宸插啓杩囦竴娆″垯璺宠繃锛岄槻姝㈠畾鏃朵换鍔￠噸澶嶈Е鍙戝鍐欍€?""
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
            log('=== 璺宠繃锛氫笉鍦ㄥ彂甯冩椂娈碉紙姣忓ぉ浠呭寳浜?08:00 / 18:00 鍐欏叆锛?==')
            return
        if published_this_window_today():
            log('=== 璺宠繃锛氬綋鍓嶆椂娈典粖澶╁凡鍐欏叆杩囷紝閬垮厤閲嶅娑堣€?ntfy 閰嶉 ===')
            return
    log('=== 寮€濮嬫姄鍙栵紙浜戠锛?==')
    # 鏁版嵁婧愮瓥鐣ワ細
    #   搴熼噾灞炶祫璁綉(feijs) 鈥斺€?鍥涘窛搴熼摐/搴熼摑锛屾暟鍊肩湡瀹炴柊椴滐紙涓庢勃閾?娌摑鏈熻揣鍚诲悎锛夛紝涓绘簮
    #   zgfp 鈥斺€?鍝佺被榻愬叏浣嗘姤浠疯繃鏈熷亸浣庯紝浠呯敤浜庤ˉ 閽?涓嶉攬閽?閾?閾?閿?绾革紝骞跺湪椤甸潰鏍囨敞銆屽亸浣庛€?
    #   鏃т富婧愩€屽北涓滈噾灞炵綉銆嶅凡澶辨晥锛?04锛夛紝涓嶅啀浣跨敤銆?
    zg_rows, zg_qdate, zg_fallback, extra = zgfp_chengdu()
    fj_rows, fj_qdate, fj_fallback = feijs_sichuan()

    low_src = set()
    rows = []
    if fj_rows:
        rows.extend(fj_rows)                       # 鐪熷疄鍥涘窛搴熼摐/搴熼摑琛屾儏
        qdate, fallback = (fj_qdate or zg_qdate), fj_fallback
        for r in zg_rows:                          # 閽㈢瓑闈為摐閾濆搧绫讳粛鍙?zgfp锛屾爣鍋忎綆
            if r['section'] in ('搴熼摐', '搴熼摑'):
                continue
            rows.append(r)
            low_src.add(r['section'])
    else:
        rows = list(zg_rows)                       # feijs 娌℃姄鍒帮紝閫€鍥?zgfp锛堝叏閮ㄥ亸浣庯級
        qdate, fallback = zg_qdate, zg_fallback
        low_src.update(r['section'] for r in rows)
    # 琛ュ厖鍝佺被锛堝簾閾?閾?閿?绾革級鏉ヨ嚜 zgfp锛屾爣娉ㄥ亸浣?
    for sec, items in extra.items():
        for it in items:
            rows.append(dict(section=sec, metal=sec, region='鎴愰兘', **it))
            low_src.add(sec)
    log('  鎴愰兘鏉＄洰鏁?', len(rows), '(feijs琛屾儏:', len(fj_rows),
        '/ zgfp琛ュ厖:', len(rows) - len(fj_rows), ') 鎶ヤ环鏃?', qdate, '鍋忎綆鏉垮潡:', sorted(low_src))

    futures = fetch_futures()
    log('  鏈熻揣鏉℃暟:', len(futures))

    if not rows:
        # 浜戠鍋跺皵琚簮绔欓檺娴侊紝鎶撲笉鍒板簾鏂欐椂缁濅笉鑳藉啓绌烘暟鎹鐩栭〉闈€?
        # 绛栫暐锛氳鍥?ntfy 涓婁竴鏉″畬鏁存暟鎹紝缁笂淇濈暀鏈燂紙椤哄甫鍒锋柊鏈熻揣鍜屾椂闂达級銆?
        log('!! 娌℃姄鍒板簾鏂欐暟鎹紝灏濊瘯澶嶇敤涓婁竴鏉″畬鏁存暟鎹画鏈?)
        prev = last_good_payload()
        if prev is None:
            log('!! 涔熸病鏈夊彲澶嶇敤鐨勫巻鍙叉暟鎹紝鏀惧純鍐欏叆锛堜繚鎸侀〉闈㈠師鏍凤級')
            sys.exit(1)
        if futures:
            prev['futures'] = futures
        prev['fetched_at'] = dt.datetime.now(CN_TZ).strftime('%m-%d %H:%M')
        payload = prev
    else:
        payload = build_payload(rows, qdate, fallback, futures, low_src)

    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    log('  鏁版嵁澶у皬:', len(body), '瀛楄妭')
    if len(body) > 4000:
        log('!! 瓒呰繃 ntfy 鍗曟潯涓婇檺')
        sys.exit(1)

    rid = publish(body)
    # 鍐欏叆鎴愬姛鍚庢妸 ntfy 涓婃棭浜庡綋澶╃殑鏃ф秷鎭竻鐞嗘帀锛坣tfy 鏀寔鎸?id 鍒犻櫎锛夛紝
    # 闃叉椤甸潰鍙栨暟鏃跺巻鍙叉秷鎭贩鍏ャ€?
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
    log('鍐欏叆鎴愬姛锛屾秷鎭?id =', rid)
    log('鏁版嵁鍦板潃 =', DATA_URL)
    log('=== 瀹屾垚 ===')


if __name__ == '__main__':
    main()
