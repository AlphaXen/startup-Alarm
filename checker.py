"""
K-Startup 모집공고 새 글 알림 봇 (GitHub Actions 버전)
- SLACK_WEBHOOK_URL 환경변수에서 자동으로 읽음
- seen_ids.json을 git에 커밋해서 상태 영구 보존
"""

import re
import requests
import json
import os
import sys
import logging
from datetime import datetime, timezone, timedelta

# ── 환경변수에서 설정 읽기 (GitHub Secret 연동) ──
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

BASE_URL = "https://www.k-startup.go.kr"
LIST_URL = f"{BASE_URL}/web/contents/bizpbanc-ongoing.do"

# GitHub Actions 환경에서는 __file__ 기준 경로 사용
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(BASE_DIR, "seen_ids.json")

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
    Playwright로 실제 브라우저처럼 페이지를 로드해 공고 목록 파싱
    """
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )

            log.info("페이지 로드 중...")
            page.goto(LIST_URL, wait_until="networkidle", timeout=30000)
            log.info("페이지 로드 완료")

            # go_view(숫자) 패턴이 있는 <a> 태그 수집
            links = page.query_selector_all("a[href*='go_view']")
            log.info(f"go_view 링크 {len(links)}개 발견")

            items = []
            for link in links:
                href = link.get_attribute("href") or ""
                match = re.search(r"go_view\((\d+)\)", href)
                if not match:
                    continue

                pbanc_sn = match.group(1)

                h3 = link.query_selector("h3")
                title = h3.inner_text().strip() if h3 else ""
                if not title:
                    continue

                org = ""
                lis = link.query_selector_all("ul li")
                if len(lis) >= 2:
                    org = lis[1].inner_text().strip()

                deadline = ""
                cat = link.query_selector(".category")
                if cat:
                    deadline = cat.inner_text().strip()

                items.append({
                    "pbancSn": pbanc_sn,
                    "title": title,
                    "url": f"{LIST_URL}?pbancSn={pbanc_sn}",
                    "org": org,
                    "deadline": deadline,
                })

            browser.close()

        if items:
            log.info(f"Playwright로 {len(items)}개 공고 수집 완료")
        else:
            log.warning("공고 목록을 찾지 못함. 사이트 HTML 구조를 확인하세요.")

        return items

    except Exception as e:
        log.error(f"공고 수집 실패: {e}")
        return []


# ── 슬랙 알림 발송 ──────────────────────────────

def send_slack(item: dict):
    if not SLACK_WEBHOOK_URL:
        log.error("SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return

    title = item.get("title", "제목 없음")
    url = item.get("url") or LIST_URL
    org = item.get("org", "")
    deadline = item.get("deadline", "")

    meta_parts = []
    if org:
        meta_parts.append(f"🏢 주관: {org}")
    if deadline:
        meta_parts.append(f"📅 {deadline}")
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

#add 
# ── 시간대 판단 ──────────────────────────────────
KST = timezone(timedelta(hours=9))

DAYTIME_START = 6
DAYTIME_END   = 21
NIGHT_INTERVAL_MINUTES = 120

def should_run() -> bool:
    now_kst = datetime.now(KST)
    hour = now_kst.hour
    minute = now_kst.minute

    if DAYTIME_START <= hour < DAYTIME_END:
        log.info(f"주간 시간대 ({hour:02d}:{minute:02d} KST) → 실행")
        return True

    night_hours = {21, 23, 1, 3, 5}
    if hour in night_hours and minute < (NIGHT_INTERVAL_MINUTES // 6):
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
        ann_id = str(item.get("pbancSn", ""))
        if not ann_id:
            continue
        current_ids.add(ann_id)

        if ann_id not in seen:
            new_items.append(item)

    if is_first_run:
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
