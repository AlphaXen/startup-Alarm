"""
K-Startup 모집공고 새 글 알림 봇 (GitHub Actions 버전)
- SLACK_WEBHOOK_URL 환경변수에서 자동으로 읽음
- seen_ids.json을 git에 커밋해서 상태 영구 보존
"""

import requests
import json
import os
import sys
import logging
from datetime import datetime, timezone, timedelta

# ── 환경변수에서 설정 읽기 (GitHub Secret 연동) ──
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

BASE_URL = "https://www.k-startup.go.kr"

# ★ 브라우저 F12 → Network → XHR 탭에서 실제 API 주소 확인 후 수정
LIST_API = f"{BASE_URL}/web/api/bizpbanc/ongoing/list.do"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE_URL}/web/contents/bizpbanc-ongoing.do",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# GitHub Actions 환경에서는 __file__ 기준 경로 사용
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(BASE_DIR, "seen_ids.json")

# GitHub Actions는 stdout으로만 로그 출력 (파일 로그 없음)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── 상태 저장/불러오기 ──────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    log.info("seen_ids.json 없음 → 최초 실행으로 간주, 현재 목록을 기준으로 저장만 함")
    return set()


def save_seen(ids: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(ids)), f, ensure_ascii=False, indent=2)
    log.info(f"seen_ids.json 저장 완료 ({len(ids)}개)")


# ── 공고 목록 가져오기 ──────────────────────────

def fetch_announcements() -> list[dict]:
    """
    방법 1: 내부 JSON API 직접 호출
    실패 시 방법 2(Selenium)로 자동 전환
    """
    params = {"pageIndex": 1, "pageUnit": 20}
    try:
        resp = requests.get(LIST_API, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # ★ 실제 API 응답 구조에 맞게 키 경로 수정 필요
        # 예: data["result"]["list"] / data["data"] / data["items"] 등
        items = data.get("result", data.get("list", data.get("data", [])))
        if isinstance(items, dict):
            items = items.get("list", [])

        if not items:
            log.warning("API 응답에서 목록을 찾지 못함. 응답 미리보기:")
            log.warning(str(data)[:300])
        else:
            log.info(f"API로 {len(items)}개 공고 수집 완료")
        return items

    except Exception as e:
        log.error(f"API 호출 실패: {e}")
        log.info("Selenium 방식으로 재시도...")
        return fetch_announcements_selenium()


def fetch_announcements_selenium() -> list[dict]:
    """
    방법 2: Selenium + headless Chrome
    GitHub Actions ubuntu-latest에는 Chrome이 기본 설치되어 있음
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"user-agent={HEADERS['User-Agent']}")

        # GitHub Actions 환경: chromedriver 경로 자동 탐색
        service = Service()
        driver = webdriver.Chrome(service=service, options=options)

        driver.get(f"{BASE_URL}/web/contents/bizpbanc-ongoing.do")
        wait = WebDriverWait(driver, 20)

        # ★ 실제 HTML 구조에 맞게 CSS selector 수정 필요
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".list-area li, .board-list tbody tr, .card-list li")
        ))

        items = []
        rows = driver.find_elements(
            By.CSS_SELECTOR, ".list-area li, .board-list tbody tr, .card-list li"
        )
        for row in rows:
            try:
                title_el = row.find_element(By.CSS_SELECTOR, ".tit, .title, td.subject a, .card-title")
                link_el = row.find_element(By.CSS_SELECTOR, "a")
                href = link_el.get_attribute("href") or ""
                items.append({
                    "id": href or title_el.text,
                    "title": title_el.text.strip(),
                    "url": href,
                })
            except Exception:
                continue

        driver.quit()
        log.info(f"Selenium으로 {len(items)}개 공고 수집 완료")
        return items

    except Exception as e:
        log.error(f"Selenium 실패: {e}")
        return []


# ── 슬랙 알림 발송 ──────────────────────────────

def send_slack(item: dict):
    if not SLACK_WEBHOOK_URL:
        log.error("SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return

    title = item.get("title", "제목 없음")
    url = item.get("url") or item.get("link") or f"{BASE_URL}/web/contents/bizpbanc-ongoing.do"
    org = item.get("org") or item.get("organizer") or item.get("InstNm") or ""
    deadline = item.get("deadline") or item.get("endDate") or item.get("pbancEndDt") or ""

    meta_parts = []
    if org:
        meta_parts.append(f"🏢 주관: {org}")
    if deadline:
        meta_parts.append(f"📅 마감: {deadline}")
    meta_text = "  |  ".join(meta_parts)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🔔 K-Startup 새 공고 등록", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*<{url}|{title}>*"},
        },
    ]
    if meta_text:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": meta_text}],
        })
    blocks.append({"type": "divider"})

    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            data=json.dumps({"blocks": blocks}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        if resp.text == "ok":
            log.info(f"슬랙 알림 발송 성공: {title}")
        else:
            log.warning(f"슬랙 응답 이상: {resp.text}")
    except Exception as e:
        log.error(f"슬랙 발송 실패: {e}")


# ── 시간대 판단 ──────────────────────────────────

KST = timezone(timedelta(hours=9))

# KST 06:00 ~ 21:00 → 20분마다 실행 (Actions cron 주기와 동일, 그냥 통과)
# KST 21:00 ~ 06:00 → 2시간마다 실행 (20분마다 트리거되지만 조건 불충족 시 조기 종료)
DAYTIME_START = 6   # KST 06시
DAYTIME_END   = 21  # KST 21시
NIGHT_INTERVAL_MINUTES = 120  # 야간 실행 간격 (2시간)

def should_run() -> bool:
    """
    KST 현재 시각 기준으로 실행 여부를 판단.
    - 06:00 ~ 21:00 : 항상 실행 (20분마다 cron과 동일)
    - 21:00 ~ 06:00 : 2시간 간격의 정각에만 실행 (23:00 / 01:00 / 03:00 / 05:00)
    """
    now_kst = datetime.now(KST)
    hour = now_kst.hour
    minute = now_kst.minute

    if DAYTIME_START <= hour < DAYTIME_END:
        log.info(f"주간 시간대 ({hour:02d}:{minute:02d} KST) → 실행")
        return True

    # 야간: 2시간 간격 정각(±10분 허용)에만 실행
    # 대상 시각: 21, 23, 01, 03, 05시 정각
    night_hours = {21, 23, 1, 3, 5}
    if hour in night_hours and minute < (NIGHT_INTERVAL_MINUTES // 6):
        # cron이 20분마다 실행되므로 첫 번째 트리거(0~19분)만 통과
        log.info(f"야간 시간대 ({hour:02d}:{minute:02d} KST) → 2시간 간격 실행")
        return True

    log.info(f"야간 시간대 ({hour:02d}:{minute:02d} KST) → 이번 실행 스킵")
    return False


# ── 메인 로직 ────────────────────────────────────

def main():
    log.info("=== K-Startup 모니터링 시작 ===")

    if not should_run():
        log.info("=== 스킵 (야간 대기 중) ===")
        sys.exit(0)

    seen = load_seen()
    is_first_run = len(seen) == 0

    announcements = fetch_announcements()
    if not announcements:
        log.warning("공고 목록을 가져오지 못했습니다. 종료.")
        sys.exit(0)

    new_items = []
    current_ids = set()

    for item in announcements:
        # ★ 실제 API 응답의 고유 ID 필드명으로 수정 (예: pbancSn, bizPbancSn 등)
        ann_id = str(
            item.get("pbancSn")
            or item.get("bizPbancSn")
            or item.get("id")
            or item.get("seq")
            or item.get("title", "")
        )
        if not ann_id:
            continue
        current_ids.add(ann_id)

        if ann_id not in seen:
            new_items.append(item)

    if is_first_run:
        # 최초 실행 시엔 알림 없이 현재 목록만 저장
        log.info(f"최초 실행: {len(current_ids)}개 공고를 기준으로 저장. 알림은 다음 실행부터 발송됩니다.")
    elif new_items:
        log.info(f"새 공고 {len(new_items)}개 발견!")
        for item in new_items:
            log.info(f"  → {item.get('title', '제목없음')}")
            send_slack(item)
        log.info("알림 발송 완료")
    else:
        log.info("새 공고 없음")

    save_seen(seen | current_ids)
    log.info("=== 모니터링 종료 ===")


if __name__ == "__main__":
    main()
