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
    ("irx",    "미국 단기금리 (13주)",  "^IRX",     3),
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


def main():
    cards = [fetch_card(c) for c in CARDS]
    fng = fetch_fng()
    out = {
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "fearGreed": fng,
        "cards": cards,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # 콘솔 요약
    okc = sum(1 for c in cards if c["periods"]["1d"].get("price") is not None)
    print(f"[fetch] cards ok: {okc}/{len(cards)}  F&G: "
          f"{fng.get('score', 'ERR')}  updatedAt={out['updatedAt']}")
    # 실패 카드 표시
    for c in cards:
        if c["periods"]["1d"].get("price") is None:
            print(f"  ! FAIL {c['id']} ({c['symbol']}): {c['periods']['1d'].get('error')}")


if __name__ == "__main__":
    main()
