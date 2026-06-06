#!/usr/bin/env python3
"""
data.json을 읽어 HTML 요약 이메일을 발송한다.
GitHub Actions에서 SMTP 환경변수(Secrets)를 사용해 실행된다.

필요 환경변수(GitHub Secrets):
  SMTP_HOST   예) smtp.gmail.com
  SMTP_PORT   예) 465
  SMTP_USER   보내는 계정
  SMTP_PASS   앱 비밀번호
  MAIL_TO     받는 주소(쉼표로 여러 명 가능)
"""
import json, os, smtplib, ssl, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

UP = "#0a8f4d"
DOWN = "#c0392b"
DIM = "#888"


def fmt(n, dec):
    if n is None:
        return "—"
    return f"{n:,.{dec}f}"


def row_html(label, price, base, dec):
    if price is None:
        return f'<tr><td style="padding:7px 12px;border-bottom:1px solid #eee">{label}</td>' \
               f'<td colspan="2" style="padding:7px 12px;border-bottom:1px solid #eee;color:{DIM}">데이터 없음</td></tr>'
    up = base is not None and price >= base
    col = UP if up else DOWN
    if base:
        diff = price - base
        pct = diff / base * 100
        chg = f'{"+" if up else ""}{pct:.2f}% ({"+" if up else ""}{fmt(diff, dec)})'
    else:
        chg = "—"
    return (
        f'<tr>'
        f'<td style="padding:7px 12px;border-bottom:1px solid #eee">{label}</td>'
        f'<td style="padding:7px 12px;border-bottom:1px solid #eee;text-align:right;font-weight:700">{fmt(price, dec)}</td>'
        f'<td style="padding:7px 12px;border-bottom:1px solid #eee;text-align:right;color:{col};font-weight:600">{chg}</td>'
        f'</tr>'
    )


def build_email(data):
    cards = data["cards"]
    fg = data.get("fearGreed", {})
    updated = datetime.datetime.fromisoformat(data["updatedAt"]).astimezone()
    upstr = updated.strftime("%Y-%m-%d %H:%M")

    # 1일 기준 등락 (전일종가 대비)
    body_rows = ""
    for c in cards:
        p = c["periods"].get("1d", {})
        price = p.get("price")
        base = p.get("prevClose")
        if base is None and p.get("series"):
            base = p["series"][0][1]
        body_rows += row_html(c["label"], price, base, c["decimals"])

    # Fear & Greed
    fg_html = ""
    if fg.get("score") is not None:
        score = round(fg["score"])
        rating = fg.get("rating", "")
        fg_html = (
            f'<div style="margin:18px 0;padding:14px 16px;background:#f7f8fa;border-radius:10px">'
            f'<span style="font-size:13px;color:#666">CNN Fear &amp; Greed Index</span><br>'
            f'<span style="font-size:30px;font-weight:800">{score}</span> '
            f'<span style="font-size:14px;color:#666">/ {rating}</span></div>'
        )

    html = f"""\
<html><body style="margin:0;background:#eef0f3;padding:18px;font-family:-apple-system,'Malgun Gothic',sans-serif;color:#222">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid #e3e6ea">
    <div style="padding:18px 20px;background:#15161d;color:#fff">
      <div style="font-size:17px;font-weight:700">📊 금융 대시보드 일일 요약</div>
      <div style="font-size:12px;color:#9aa;margin-top:3px">데이터 시각: {upstr}</div>
    </div>
    <div style="padding:16px 18px">
      {fg_html}
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="color:#888;font-size:11px">
          <th style="text-align:left;padding:0 12px 6px">지표</th>
          <th style="text-align:right;padding:0 12px 6px">현재가</th>
          <th style="text-align:right;padding:0 12px 6px">전일 대비</th>
        </tr></thead>
        <tbody>{body_rows}</tbody>
      </table>
      <p style="font-size:11px;color:#aaa;margin-top:16px">
        전일종가 대비 등락 기준. 자세한 차트는 대시보드에서 확인하세요.
      </p>
    </div>
  </div>
</body></html>"""
    return html, upstr


def main():
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)
    html, upstr = build_email(data)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    pwd = os.environ["SMTP_PASS"]
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 금융 대시보드 요약 ({upstr})"
    msg["From"] = user
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, pwd)
            s.sendmail(user, to, msg.as_string())
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(user, to, msg.as_string())
    print(f"[email] sent to {to}")


if __name__ == "__main__":
    main()
