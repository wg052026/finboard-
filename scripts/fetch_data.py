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
    ("jpykrw", "엔 (JPY/KRW)",         "JPYKRW=X", 3),
    ("dxy",    "달러인덱스 (DXY)",      "DX-Y.NYB", 3),
    ("tnx",    "미국채 10년 금리",      "^TNX",     3),
    ("ust2y",  "미국채 2년 금리",       "2YY=F",    3),
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
    cid, label, symbol, dec = card
    periods = {}
    for key, (rng, interval) in RANGES.items():
        try:
            periods[key] = fetch_yahoo(symbol, rng, interval)
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


def build_cpi_card():
    """미국 CPI(전체, 계절조정) 지수와 전년동월 대비(YoY) 상승률 카드."""
    this_year = datetime.datetime.now(datetime.timezone.utc).year
    try:
        # CUSR0000SA0 = CPI-U, all items, 계절조정
        series_idx = fetch_bls_series("CUSR0000SA0", this_year - 4, this_year)
        if len(series_idx) < 2:
            return None

        # YoY 상승률 시계열 계산 (12개월 전 대비 %)
        idx_map = {ms: v for ms, v in series_idx}
        yoy = []
        for ms, v in series_idx:
            dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
            prev_dt = dt.replace(year=dt.year - 1)
            prev_ms = int(prev_dt.timestamp() * 1000)
            if prev_ms in idx_map and idx_map[prev_ms]:
                yoy.append([ms, round((v / idx_map[prev_ms] - 1) * 100, 2)])

        if len(yoy) < 2:
            return None

        last_yoy = yoy[-1][1]
        prev_yoy = yoy[-2][1] if len(yoy) >= 2 else None

        # 기간별로는 동일한 월별 데이터를 길이만 잘라서 제공
        def cut(series, months):
            return series[-months:] if len(series) > months else series
        periods = {}
        for key, n in [("1d", 13), ("5d", 13), ("1mo", 13),
                       ("1y", 13), ("3y", 37)]:
            s = cut(yoy, n)
            periods[key] = {
                "price": last_yoy,
                "prevClose": prev_yoy,
                "series": s,
            }
        return {
            "id": "cpi_yoy",
            "label": "미국 CPI (전년比 %)",
            "symbol": "CPI YoY",
            "decimals": 2,
            "diffMode": "pp",
            "periods": periods,
        }
    except Exception as e:
        return {"id": "cpi_yoy", "label": "미국 CPI (전년比 %)",
                "symbol": "CPI YoY", "decimals": 2, "diffMode": "pp",
                "periods": {k: {"price": None, "prevClose": None,
                                "series": [], "error": str(e)[:80]}
                            for k in RANGES}}


def build_spread_card(cards):
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

    # 10-2년 장단기 금리차 카드를 2년 금리(ust2y) 바로 뒤에 삽입
    spread = build_spread_card(cards)
    if spread:
        idx = next((i for i, c in enumerate(cards) if c["id"] == "ust2y"), None)
        if idx is not None:
            cards.insert(idx + 1, spread)
        else:
            cards.append(spread)

    # 3페이지(경제지표) 카드들
    econ_cards = []
    cpi = build_cpi_card()
    if cpi:
        econ_cards.append(cpi)

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
