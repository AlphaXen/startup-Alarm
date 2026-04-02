# K-Startup 공고 모니터링 봇 (GitHub Actions 버전)

새 공고가 올라오면 슬랙으로 자동 알림을 보내는 봇입니다.

## 저장소 구조

```
├── checker.py                        # 메인 스크립트
├── requirements.txt                  # 패키지 목록
├── seen_ids.json                     # 이미 본 공고 ID (자동 관리)
└── .github/
    └── workflows/
        └── monitor.yml               # GitHub Actions 워크플로우
```

---

## 세팅 방법

### 1단계 - 이 저장소를 GitHub에 올리기

```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/본인계정/kstartup-monitor.git
git push -u origin main
```

> 저장소는 **Public**으로 설정해야 Actions 무제한 무료 사용 가능

---

### 2단계 - Slack Webhook URL 발급

1. https://api.slack.com/apps 접속 → **Create New App → From scratch**
2. 앱 이름 입력 → 워크스페이스 선택
3. 좌측 **Incoming Webhooks** → 토글 **On**
4. **Add New Webhook to Workspace** → 알림 받을 채널 선택
5. Webhook URL 복사 (`https://hooks.slack.com/services/...`)

---

### 3단계 - GitHub Secret 등록

1. 저장소 → **Settings** 탭
2. 좌측 **Secrets and variables → Actions**
3. **New repository secret** 클릭
4. Name: `SLACK_WEBHOOK_URL`
5. Secret: 위에서 복사한 Webhook URL 붙여넣기
6. **Add secret**

---

### 4단계 - API 엔드포인트 확인 후 수정 (중요!)

사이트 공고 목록은 JavaScript로 렌더링됩니다.
실제 내부 API 주소를 찾아서 `checker.py`를 수정해야 합니다.

**확인 방법:**
1. Chrome에서 k-startup 모집중 페이지 열기
2. `F12` → **Network 탭** → **Fetch/XHR** 필터
3. 페이지 새로고침
4. `list`, `pbanc`, `ongoing` 포함된 요청 찾기
5. 해당 URL → `checker.py`의 `LIST_API` 변수에 입력
6. 응답 JSON 구조 확인 → `fetch_announcements()` 내 키 경로 수정
7. 공고 고유 ID 필드명 확인 → `main()` 내 `ann_id` 추출 부분 수정

---

### 5단계 - 수동 테스트 실행

저장소 → **Actions 탭** → **K-Startup 공고 모니터링** → **Run workflow**

최초 실행 시엔 알림 없이 현재 공고 목록만 저장됩니다.
그 다음 실행부터 새 공고가 생기면 슬랙 알림이 옵니다.

---

## 실행 스케줄

| 실행 시각 (KST) | cron (UTC) |
|---|---|
| 매일 오전 09:00 | `0 0 * * *` |
| 매일 오후 13:00 | `0 4 * * *` |
| 매일 오후 18:00 | `0 9 * * *` |

`monitor.yml`의 `cron` 값을 수정하면 스케줄을 바꿀 수 있습니다.

---

## 동작 원리

```
Actions 실행
    ↓
checker.py 시작
    ↓
seen_ids.json 로드 (이전에 본 공고 ID 목록)
    ↓
K-Startup API 호출 → 최신 공고 20개 수집
    ↓
새 공고 감지 (seen에 없는 ID)
    ↓
슬랙 알림 발송
    ↓
seen_ids.json 업데이트 → git 커밋 & 푸시
```

`seen_ids.json`을 git에 커밋하는 방식으로 실행 간 상태를 보존합니다.
