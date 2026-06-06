# 실시간 금융 대시보드 + 매일 메일

GitHub Actions(서버)가 데이터를 받아 `data.json`에 저장하고, 대시보드(GitHub Pages)는
그 파일만 읽습니다. **CORS·프록시·API 키가 전혀 필요 없고, 항상 안정적으로 동작합니다.**

수집 항목: 환율 4종(CHF/USD/EUR/JPY → KRW), 달러인덱스, 미국채 10년·단기(13주),
VIX, S&P500, 나스닥, 다우, WTI, 코스피, 코스닥, CNN Fear & Greed.

## 파일 구조
```
index.html                  대시보드 (data.json만 읽음)
data.json                   Actions가 자동 생성/갱신
scripts/fetch_data.py       데이터 수집
scripts/send_email.py       HTML 메일 발송
.github/workflows/update.yml  자동화
```

## 설치 (5단계)

### 1. 리포지토리에 올리기
이 파일들을 GitHub 리포(예: 기존 `wg052026.github.io` 또는 새 리포)에 푸시합니다.

### 2. 첫 데이터 생성
- 리포 → **Actions** 탭 → "금융 대시보드 업데이트" → **Run workflow** 클릭.
- 끝나면 `data.json`이 커밋됩니다.
- (로컬에서 미리 만들려면: `python scripts/fetch_data.py`)

### 3. GitHub Pages 켜기
- 리포 → **Settings → Pages** → Source를 배포 브랜치로 지정.
- `https://<사용자>.github.io/<리포>/index.html` 로 접속.

### 4. 메일 설정 (Secrets 등록)
리포 → **Settings → Secrets and variables → Actions → New repository secret** 로 아래 등록:

| 이름 | 값 (Gmail 예시) |
|------|------|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | 보내는 Gmail 주소 |
| `SMTP_PASS` | Gmail **앱 비밀번호** (2단계 인증 후 발급) |
| `MAIL_TO` | 받을 주소 (쉼표로 여러 개 가능) |

> Gmail 앱 비밀번호: Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호에서 16자리 발급.
> 네이버메일을 쓰면 `SMTP_HOST=smtp.naver.com`, `SMTP_PORT=465`, 계정 보안설정에서 SMTP 사용 허용.

### 5. 스케줄 확인
`.github/workflows/update.yml`:
- 데이터 갱신: 매시간 정각 (UTC `0 * * * *`)
- 메일 발송: 매일 **KST 07:30** (UTC `30 22 * * *`)

시각을 바꾸려면 cron 값을 수정하세요. (UTC 기준, KST = UTC+9)

## 대시보드 기능
- **기간 선택**: 1일 / 5일 / 30일 / 1년 / 3년 — 누르면 모든 카드가 함께 전환.
- **새로고침 버튼**: 누를 때만 `data.json`을 다시 읽음 (자동 갱신 없음).
- **호버 툴팁**: 차트에 커서를 올리면 그 시점의 값·날짜 표시.
- **Fear & Greed**: 1일은 숫자 게이지, 그 외 기간은 추이 그래프.

## 참고
- 데이터는 Yahoo Finance·CNN 기준이며 무료 데이터 특성상 15~20분 지연될 수 있습니다.
- 미국채 2년물은 무료로 안정적인 소스가 없어 13주 단기금리로 대체했습니다.
- 갱신 주기를 너무 촘촘히 하면 Actions 사용량이 늘어납니다(무료 한도 내 권장: 1시간).
