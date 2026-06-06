#!/usr/bin/env python3
"""
금융 대시보드 데이터 수집기.
Yahoo Finance + CNN Fear&Greed에서 기간별(1일/5일/30일/1년/3년) 데이터를 받아
data.json 하나로 저장한다. GitHub Actions(서버)에서 실행되므로 CORS/프록시 불필요.
"""
import urllib.request, urllib.parse, json, ssl, time, datetime, sys

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

YH_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CNN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    "Origin": "https://edition.cnn.com",
}

# 기간 정의: key -> (yahoo range, yahoo interval)
RANGES = {
    "1d":  ("1d",  "5m"),
    "5d":  ("5d",  "15m"),
    "1mo": ("1mo", "60m"),
    "1y":  ("1y",  "1d"),
    "3y":  ("3y",  "1wk"),
}

# 표시할 카드: (id, 라벨, Yahoo 심볼, 소수자릿수)
CARDS = [
    ("chfkrw", "스위스프랑 (CHF/KRW)", "CHFKRW=X", 2),
    ("usdkrw", "미국달러 (USD/KRW)",   "KRW=X",    2),
    ("eurkrw", "유로 (EUR/KRW)",       "EURKRW=X", 2),
    ("jpykrw", "엔 (100엔/KRW)",       "JPYKRW=X", 2, 100),
    ("dxy",    "달러인덱스 (DXY)",      "DX-Y.NYB", 3),
    ("vix",    "VIX 변동성지수",        "^VIX",     2),
    ("gspc",   "S&P 500",              "^GSPC",    2),
    ("ixic",   "나스닥 종합",           "^IXIC",    2),
    ("dji",    "다우존스 산업평균",      "^DJI",     2),
    ("cl",     "WTI 원유",             "CL=F",     2),
    ("ks11",   "코스피 (KOSPI)",       "^KS11",    2),
    ("kq11",   "코스닥 (KOSDAQ)",      "^KQ11",    2),
]


def http_get(url, headers, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            return urllib.request.urlopen(req, timeout=25, context=CTX).read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fetch_yahoo(symbol, rng, interval):
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/"
         + urllib.parse.quote(symbol)
         + f"?range={rng}&interval={interval}")
    raw = http_get(u, YH_HEADERS)
    d = json.loads(raw)
    res = d["chart"]["result"][0]
    meta = res["meta"]
    ts = res.get("timestamp", []) or []
    closes_raw = res["indicators"]["quote"][0].get("close", []) or []
    # null 제거 (타임스탬프와 짝 유지)
    series = []
    for t, c in zip(ts, closes_raw):
        if c is not None:
            series.append([int(t) * 1000, round(float(c), 4)])
    price = meta.get("regularMarketPrice")
    if price is None and series:
        price = series[-1][1]
    prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
    return {
        "price": price,
        "prevClose": prev_close,
        "series": series,
    }


def fetch_card(card):
    # card: (id, label, symbol, decimals[, scale])
    cid, label, symbol, dec = card[0], card[1], card[2], card[3]
    scale = card[4] if len(card) > 4 else 1
    periods = {}
    for key, (rng, interval) in RANGES.items():
        try:
            d = fetch_yahoo(symbol, rng, interval)
            if scale != 1:
                if d.get("price") is not None:
                    d["price"] = round(d["price"] * scale, 4)
                if d.get("prevClose") is not None:
                    d["prevClose"] = round(d["prevClose"] * scale, 4)
                d["series"] = [[t, round(v * scale, 4)] for t, v in d.get("series", [])]
            periods[key] = d
        except Exception as e:
            periods[key] = {"price": None, "prevClose": None, "series": [], "error": str(e)[:80]}
    return {"id": cid, "label": label, "symbol": symbol, "decimals": dec, "periods": periods}


def fetch_fng():
    try:
        raw = http_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", CNN_HEADERS)
        d = json.loads(raw)
        fg = d["fear_and_greed"]
        hist = d.get("fear_and_greed_historical", {}).get("data", [])
        # [timestamp(ms), score] 형태로 정리
        series = [[int(p["x"]), round(float(p["y"]), 1)] for p in hist if p.get("y") is not None]
        return {
            "score": round(float(fg["score"]), 1),
            "rating": fg.get("rating"),
            "timestamp": fg.get("timestamp"),
            "previous_close": fg.get("previous_close"),
            "previous_1_week": fg.get("previous_1_week"),
            "previous_1_month": fg.get("previous_1_month"),
            "previous_1_year": fg.get("previous_1_year"),
            "series": series,
        }
    except Exception as e:
        return {"error": str(e)[:120]}


def fetch_bls_series(series_id, start_year, end_year):
    """BLS 공개 API에서 월별 시계열을 받아 [ms, value] 리스트로 반환."""
    body = json.dumps({
        "seriesid": [series_id],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }).encode()
    headers = {**YH_HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/" + series_id,
        data=body, headers=headers)
    raw = urllib.request.urlopen(req, timeout=25, context=CTX).read()
    d = json.loads(raw)
    data = d["Results"]["series"][0]["data"]
    out = []
    for row in data:
        if not row["period"].startswith("M"):
            continue
        val = row.get("value", "").strip()
        if not val or val in ("-", "."):
            continue
        try:
            fval = float(val)
        except ValueError:
            continue
        month = int(row["period"][1:])
        ms = int(datetime.datetime(int(row["year"]), month, 1,
                                   tzinfo=datetime.timezone.utc).timestamp() * 1000)
        out.append([ms, fval])
    out.sort(key=lambda x: x[0])
    return out


def fetch_bls_multi(series_ids, start_year, end_year):
    """여러 BLS 시리즈를 한 번에 요청. 반환: {series_id: [[ms,val],...]}"""
    body = json.dumps({
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }).encode()
    headers = {**YH_HEADERS, "Content-Type": "application/json"}
    last_err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                data=body, headers=headers)
            raw = urllib.request.urlopen(req, timeout=40, context=CTX).read()
            d = json.loads(raw)
            if d.get("status") == "REQUEST_SUCCEEDED":
                break
            last_err = str(d.get("status")) + " " + " ".join(d.get("message", []))[:80]
        except Exception as e:
            last_err = str(e)[:80]
        time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError("BLS: " + (last_err or "unknown"))
    result = {}
    for ser in d["Results"]["series"]:
        out = []
        for row in ser["data"]:
            if not row["period"].startswith("M"):
                continue
            val = (row.get("value") or "").strip()
            if not val or val in ("-", "."):
                continue
            try:
                fval = float(val)
            except ValueError:
                continue
            month = int(row["period"][1:])
            ms = int(datetime.datetime(int(row["year"]), month, 1,
                                       tzinfo=datetime.timezone.utc).timestamp() * 1000)
            out.append([ms, fval])
        out.sort(key=lambda x: x[0])
        result[ser["seriesID"]] = out
    return result


def fetch_bls_series(series_id, start_year, end_year):
    """단일 시리즈 (하위호환)."""
    return fetch_bls_multi([series_id], start_year, end_year).get(series_id, [])


def _yoy(series):
    """월별 지수 시계열 → 전년동월 대비 % 시계열."""
    idx = {ms: v for ms, v in series}
    out = []
    for ms, v in series:
        dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
        try:
            prev_ms = int(dt.replace(year=dt.year - 1).timestamp() * 1000)
        except ValueError:
            continue
        if prev_ms in idx and idx[prev_ms]:
            out.append([ms, round((v / idx[prev_ms] - 1) * 100, 2)])
    return out


def _mom_change(series):
    """월별 레벨 시계열 → 전월 대비 증감 시계열 (절대 변화량)."""
    out = []
    for i in range(1, len(series)):
        out.append([series[i][0], round(series[i][1] - series[i-1][1], 1)])
    return out


def _cut(series, n):
    return series[-n:] if len(series) > n else series[:]


def _econ_periods(series, last_price, prev_base):
    """경제지표는 월별이라 기간 구간을 길이로 근사."""
    periods = {}
    for key, n in [("1d", 13), ("5d", 13), ("1mo", 13), ("1y", 13), ("3y", 37)]:
        s = _cut(series, n)
        periods[key] = {"price": last_price, "prevClose": prev_base, "series": s}
    return periods


def build_econ_cards():
    """3페이지 경제지표 카드들을 생성한다.
    CPI·근원CPI: 전년比 %(pp) / 실업률·PPI(전년比): %(pp) /
    비농업고용: 전월대비 증감(천명) / 기준금리(EFFR): %(pp)."""
    this_year = datetime.datetime.now(datetime.timezone.utc).year
    cards = []

    # ---- BLS 묶음 요청 ----
    SID = {
        "cpi":   "CUSR0000SA0",      # CPI-U all items, SA
        "core":  "CUSR0000SA0L1E",   # Core CPI, SA
        "unemp": "LNS14000000",      # 실업률 U-3, SA
        "nfp":   "CES0000000001",    # 비농업 총고용(천명), SA
        "ppi":   "WPSFD4",           # PPI 최종수요
    }
    try:
        bls = fetch_bls_multi(list(SID.values()), this_year - 4, this_year)
    except Exception as e:
        bls = {}
        print("  ! BLS fail:", str(e)[:80])

    def add_yoy_card(cid, label, sid, note):
        s = bls.get(sid, [])
        yoy = _yoy(s)
        if len(yoy) >= 2:
            cards.append({
                "id": cid, "label": label, "symbol": label, "decimals": 2,
                "diffMode": "pp", "note": note,
                "asof": _month_label(yoy[-1][0]),
                "periods": _econ_periods(yoy, yoy[-1][1], yoy[-2][1]),
            })

    def add_level_card(cid, label, sid, note, dec=1, suffix=""):
        s = bls.get(sid, [])
        if len(s) >= 2:
            cards.append({
                "id": cid, "label": label, "symbol": label, "decimals": dec,
                "diffMode": "pp", "note": note, "unit": suffix,
                "asof": _month_label(s[-1][0]),
                "periods": _econ_periods(s, s[-1][1], s[-2][1]),
            })

    # CPI (전년比)
    add_yoy_card("cpi_yoy", "미국 CPI (전년比 %)", SID["cpi"],
                 "매월 중순 발표 · 전월 기준")
    # 근원 CPI (전년比)
    add_yoy_card("core_cpi", "근원 CPI (전년比 %)", SID["core"],
                 "매월 중순 발표 · 전월 기준 · 식품·에너지 제외")
    # 실업률 (레벨 %)
    add_level_card("unemp", "미국 실업률 (%)", SID["unemp"],
                   "매월 초 발표 (첫 금요일) · 전월 기준", dec=1)
    # 비농업 고용 (전월대비 증감, 천명)
    s_nfp = bls.get(SID["nfp"], [])
    nfp_chg = _mom_change(s_nfp)
    if len(nfp_chg) >= 2:
        cards.append({
            "id": "nfp", "label": "비농업 신규고용 (천명)", "symbol": "NFP", "decimals": 0,
            "diffMode": "delta", "note": "매월 초 발표 (첫 금요일) · 전월 대비 증감",
            "asof": _month_label(nfp_chg[-1][0]),
            "periods": _econ_periods(nfp_chg, nfp_chg[-1][1], nfp_chg[-2][1]),
        })
    # PPI (전년比)
    add_yoy_card("ppi_yoy", "생산자물가 PPI (전년比 %)", SID["ppi"],
                 "매월 중순 발표 · 전월 기준 · CPI 선행지표")

    # ---- 기준금리 EFFR (뉴욕연준) ----
    try:
        effr = fetch_effr()
        if effr and len(effr) >= 2:
            cards.append({
                "id": "effr", "label": "미국 기준금리 EFFR (%)", "symbol": "EFFR",
                "decimals": 2, "diffMode": "pp",
                "note": "FOMC 회의 후 변경 (연 8회) · 실효 연방기금금리",
                "asof": _day_label(effr[-1][0]),
                "periods": _effr_periods(effr),
            })
    except Exception as e:
        print("  ! EFFR fail:", str(e)[:80])

    return cards


def _month_label(ms):
    dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    return f"{dt.year}년 {dt.month}월"


def _day_label(ms):
    dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    return f"{dt.year}-{dt.month:02d}-{dt.day:02d}"


def fetch_effr():
    """뉴욕연준 실효 연방기금금리(EFFR) 일별 시계열 [[ms,val],...] (최근 약 3년)."""
    import datetime as _dt
    end = _dt.date.today()
    start = end.replace(year=end.year - 3)
    url = ("https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
           f"?startDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}&type=rate")
    raw = http_get(url, {"User-Agent": YH_HEADERS["User-Agent"]})
    d = json.loads(raw)
    out = []
    for r in d.get("refRates", []):
        try:
            ds = r["effectiveDate"]; v = float(r["percentRate"])
        except (KeyError, ValueError, TypeError):
            continue
        ms = int(_dt.datetime.strptime(ds, "%Y-%m-%d")
                 .replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)
        out.append([ms, v])
    out.sort(key=lambda x: x[0])
    return out


def _effr_periods(series):
    """EFFR은 일별이라 기간별로 잘라서 제공."""
    span = {"1d": 2, "5d": 6, "1mo": 22, "1y": 252, "3y": len(series)}
    periods = {}
    for key, n in span.items():
        s = _cut(series, n)
        price = s[-1][1] if s else None
        prev = s[-2][1] if len(s) >= 2 else None
        base = prev if key == "1d" else (s[0][1] if s else None)
        periods[key] = {"price": price, "prevClose": base, "series": s}
    return periods


def fetch_treasury_yields():
    """미 재무부 일별 par yield 곡선에서 2년·10년 금리 시계열을 받는다.
    반환: {'2y': [[ms,val],...], '10y': [...]} (최근 약 3년)"""
    import re
    now_year = datetime.datetime.now(datetime.timezone.utc).year
    rows = []  # (date_str, v2, v10)
    for y in range(now_year - 3, now_year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/"
               "interest-rates/pages/xml?data=daily_treasury_yield_curve"
               f"&field_tdr_date_value={y}")
        try:
            x = http_get(url, YH_HEADERS).decode()
        except Exception:
            continue
        for blk in re.findall(r"<m:properties>(.*?)</m:properties>", x, re.S):
            d = re.search(r"<d:NEW_DATE[^>]*>(.*?)</d:NEW_DATE>", blk)
            t2 = re.search(r"<d:BC_2YEAR[^>]*>(.*?)</d:BC_2YEAR>", blk)
            t10 = re.search(r"<d:BC_10YEAR[^>]*>(.*?)</d:BC_10YEAR>", blk)
            if d and t2 and t10 and t2.group(1) and t10.group(1):
                rows.append((d.group(1)[:10], float(t2.group(1)), float(t10.group(1))))
    rows.sort(key=lambda r: r[0])

    def to_ms(ds):
        dt = datetime.datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() * 1000)

    s2 = [[to_ms(d), v2] for d, v2, _ in rows]
    s10 = [[to_ms(d), v10] for d, _, v10 in rows]
    return {"2y": s2, "10y": s10}


def build_yield_cards(tdata):
    """재무부 2년·10년 시계열로 10년·2년 금리 카드와 10-2 금리차 카드를 만든다.
    Yahoo의 기간 구간에 맞춰 일별 데이터를 길이로 잘라 제공한다."""
    s2 = tdata.get("2y", [])
    s10 = tdata.get("10y", [])
    if len(s2) < 2 or len(s10) < 2:
        return []

    # 기간별 길이(거래일 수) 근사. 일/시간봉이 없어 일별로 통일.
    span = {"1d": 2, "5d": 6, "1mo": 22, "1y": 252, "3y": len(s2)}

    def make_card(cid, label, series):
        periods = {}
        for key, n in span.items():
            s = series[-n:] if len(series) > n else series[:]
            price = s[-1][1] if s else None
            prev = s[-2][1] if len(s) >= 2 else None
            # 1일은 직전 거래일 대비, 그 외는 구간 시작 대비
            base = prev if key in ("1d",) else (s[0][1] if s else None)
            periods[key] = {"price": price, "prevClose": base, "series": s}
        return {"id": cid, "label": label, "symbol": label,
                "decimals": 3, "diffMode": "pp", "periods": periods}

    card10 = make_card("tnx", "미국채 10년 금리", s10)
    card2 = make_card("ust2y", "미국채 2년 금리", s2)

    # 금리차 = 10년 - 2년 (날짜 매칭)
    m2 = {t: v for t, v in s2}
    diff_series = [[t, round(v - m2[t], 4)] for t, v in s10 if t in m2]
    cardSp = make_card("spread102", "10-2년 장단기 금리차", diff_series)
    cardSp["label"] = "10-2년 장단기 금리차"

    return [card10, card2, cardSp]



    """10년 금리(tnx)와 2년 금리(ust2y) 시계열을 빼서 10-2 장단기 금리차 카드 생성.
    두 심볼의 타임스탬프 시각이 달라, 날짜(UTC 연-월-일) 단위로 묶어 매칭한다."""
    import datetime as _dt
    by_id = {c["id"]: c for c in cards}
    ten = by_id.get("tnx")
    two = by_id.get("ust2y")
    if not ten or not two:
        return None

    def day_key(ms):
        return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")

    spread = {"id": "spread102", "label": "10-2년 장단기 금리차",
              "symbol": "10Y-2Y", "decimals": 3, "diffMode": "pp", "periods": {}}

    for key in RANGES:
        p10 = ten["periods"].get(key, {})
        p2 = two["periods"].get(key, {})
        # 날짜 -> (마지막 값, 마지막 ms) 로 묶기
        def by_day(p):
            m = {}
            for t, v in (p.get("series") or []):
                m[day_key(t)] = (v, t)
            return m
        d10 = by_day(p10)
        d2 = by_day(p2)
        common = sorted(set(d10) & set(d2))
        series = []
        for day in common:
            v10, t10 = d10[day]
            v2, _ = d2[day]
            series.append([t10, round(v10 - v2, 4)])
        price = None
        if p10.get("price") is not None and p2.get("price") is not None:
            price = round(p10["price"] - p2["price"], 4)
        elif series:
            price = series[-1][1]
        prev = None
        if p10.get("prevClose") is not None and p2.get("prevClose") is not None:
            prev = round(p10["prevClose"] - p2["prevClose"], 4)
        elif len(series) >= 2:
            prev = series[0][1]
        spread["periods"][key] = {"price": price, "prevClose": prev, "series": series}
    return spread


def main():
    cards = [fetch_card(c) for c in CARDS]

    # 미 재무부 공식 par yield로 10년·2년·금리차 카드 생성 → DXY 뒤에 삽입
    try:
        tdata = fetch_treasury_yields()
        yield_cards = build_yield_cards(tdata)
    except Exception as e:
        print("  ! treasury fetch fail:", str(e)[:80])
        yield_cards = []
    if yield_cards:
        idx = next((i for i, c in enumerate(cards) if c["id"] == "dxy"), None)
        pos = (idx + 1) if idx is not None else len(cards)
        cards[pos:pos] = yield_cards

    # 3페이지(경제지표) 카드들
    econ_cards = build_econ_cards()

    fng = fetch_fng()
    out = {
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "fearGreed": fng,
        "cards": cards,           # 시장 지표 (1·2페이지 공용)
        "econCards": econ_cards,  # 경제 지표 (3페이지)
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # 콘솔 요약
    okc = sum(1 for c in cards if c["periods"]["1d"].get("price") is not None)
    print(f"[fetch] market cards ok: {okc}/{len(cards)}  econ: {len(econ_cards)}  "
          f"F&G: {fng.get('score', 'ERR')}  updatedAt={out['updatedAt']}")
    for c in cards + econ_cards:
        if c["periods"]["1d"].get("price") is None:
            print(f"  ! FAIL {c['id']} ({c['symbol']}): {c['periods']['1d'].get('error')}")


if __name__ == "__main__":
    main()
