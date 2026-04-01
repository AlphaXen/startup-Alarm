"""
K-Startup 모집공고 새 글 알림 봇
- 30분마다 실행하여 새 공고가 올라오면 슬랙으로 알림 발송
- 실행 방법: python checker.py
- 자동 실행: crontab에 등록 (README 참고)
"""

import requests
import json
import os
import logging
from datetime import datetime

# ─────────────────────────────────────────
# ★ 여기에 슬랙 Webhook URL 입력 ★
# 발급 방법: README 참고
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"
# ─────────────────────────────────────────

BASE_URL = "https://www.k-startup.go.kr"
# 사이트 내부 API 엔드포인트 (브라우저 개발자 도구 Network 탭에서 확인한 주소)
# 실제 엔드포인트가 다를 경우 아래 HEADERS와 함께 수정 필요
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

SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_ids.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "monitor.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── 상태 저장/불러오기 ──────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(ids: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f, ensure_ascii=False)


# ── 공고 목록 가져오기 ──────────────────────

def fetch_announcements() -> list[dict]:
    """
    방법 1: 내부 JSON API 직접 호출 (가볍고 빠름)
    실패 시 방법 2(Selenium)로 전환하는 구조.
    
    ★ API 엔드포인트/파라미터가 맞지 않으면:
      브라우저 F12 → Network → XHR 탭에서
      'list' 또는 'pbanc'가 포함된 요청을 찾아서
      URL과 파라미터를 아래에 맞게 수정하세요.
    """
    params = {
        "pageIndex": 1,
        "pageUnit": 20,  # 최신 20개만 확인
    }

    try:
        resp = requests.get(LIST_API, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # 응답 구조에 따라 아래 키 경로를 수정하세요
        # 예: data["result"]["list"] 또는 data["data"] 등
        items = data.get("result", data.get("list", []))
        if not items:
            log.warning("API 응답에서 공고 목록을 찾지 못했습니다. 응답 구조를 확인하세요.")
            log.debug(f"응답 내용: {str(data)[:500]}")
        return items

    except Exception as e:
        log.error(f"API 호출 실패: {e}")
        log.info("Selenium 방식으로 재시도합니다...")
        return fetch_announcements_selenium()


def fetch_announcements_selenium() -> list[dict]:
    """
    방법 2: Selenium으로 실제 브라우저 렌더링 후 파싱
    pip install selenium webdriver-manager
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={HEADERS['User-Agent']}")

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )
        driver.get(f"{BASE_URL}/web/contents/bizpbanc-ongoing.do")

        # 공고 목록이 로드될 때까지 대기 (최대 15초)
        # ★ 실제 HTML 구조에 맞게 selector 수정 필요
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list-area li, table.board-list tbody tr")))

        items = []
        # 공고 카드/행 파싱 (사이트 구조에 따라 수정)
        rows = driver.find_elements(By.CSS_SELECTOR, ".list-area li, table.board-list tbody tr")
        for row in rows:
            try:
                title_el = row.find_element(By.CSS_SELECTOR, ".tit, .title, td.subject a")
                link_el = row.find_element(By.CSS_SELECTOR, "a")
                ann_id = link_el.get_attribute("href") or title_el.text
                items.append({
                    "id": ann_id,
                    "title": title_el.text.strip(),
                    "url": link_el.get_attribute("href"),
                })
            except Exception:
                continue

        driver.quit()
        log.info(f"Selenium으로 {len(items)}개 공고 수집 완료")
        return items

    except ImportError:
        log.error("selenium 또는 webdriver-manager 미설치. pip install selenium webdriver-manager")
        return []
    except Exception as e:
        log.error(f"Selenium 실패: {e}")
        return []


# ── 슬랙 알림 발송 ─────────────────────────

def send_slack(item: dict):
    """
    슬랙 Incoming Webhook으로 Block Kit 메시지 발송
    텍스트보다 보기 좋은 카드 형태로 전송됨
    """
    title = item.get("title", "제목 없음")
    url = item.get("url") or item.get("link") or f"{BASE_URL}/web/contents/bizpbanc-ongoing.do"
    org = item.get("org", item.get("organizer", ""))
    deadline = item.get("deadline", item.get("endDate", ""))

    # 부가 정보 텍스트 조합
    meta_parts = []
    if org:
        meta_parts.append(f"🏢 주관: {org}")
    if deadline:
        meta_parts.append(f"📅 마감: {deadline}")
    meta_text = "  |  ".join(meta_parts) if meta_parts else ""

    # 슬랙 Block Kit 구조 (카드 형태)
    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🔔 K-Startup 새 공고 등록",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<{url}|{title}>*",
                },
            },
            *(
                [
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": meta_text}],
                    }
                ]
                if meta_text
                else []
            ),
            {"type": "divider"},
        ]
    }

    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        if resp.text != "ok":
            log.warning(f"슬랙 응답 이상: {resp.text}")
        else:
            log.info("슬랙 알림 발송 성공")
    except Exception as e:
        log.error(f"슬랙 발송 실패: {e}")


# ── 메인 로직 ───────────────────────────────

def main():
    log.info("=== K-Startup 모니터링 시작 ===")
    seen = load_seen()

    announcements = fetch_announcements()
    if not announcements:
        log.warning("공고 목록을 가져오지 못했습니다.")
        return

    new_items = []
    current_ids = set()

    for item in announcements:
        # ID 추출 (API 응답 구조에 따라 키 이름 수정)
        ann_id = str(
            item.get("pbancSn")
            or item.get("id")
            or item.get("seq")
            or item.get("title", "")
        )
        current_ids.add(ann_id)

        if ann_id and ann_id not in seen:
            new_items.append(item)
            log.info(f"새 공고 발견: {item.get('title', ann_id)}")

    if new_items:
        for item in new_items:
            send_slack(item)
        log.info(f"총 {len(new_items)}개 새 공고 알림 발송 완료")
    else:
        log.info("새 공고 없음")

    # 현재 목록 기준으로 seen 갱신 (삭제된 공고 정리)
    updated_seen = seen | current_ids
    save_seen(updated_seen)
    log.info("=== 모니터링 종료 ===")


if __name__ == "__main__":
    main()
