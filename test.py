"""
K-Startup 공고 수집 로컬 테스트
- Playwright로 페이지 렌더링 후 공고 목록 파싱 확인
"""

import sys
import re

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://www.k-startup.go.kr"
LIST_URL = f"{BASE_URL}/web/contents/bizpbanc-ongoing.do"


def test_fetch():
    from playwright.sync_api import sync_playwright

    print(f"[테스트] K-Startup 공고 페이지 접속 중...\n  URL: {LIST_URL}\n")

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

        page.goto(LIST_URL, wait_until="networkidle", timeout=30000)
        print("[성공] 페이지 로드 완료")

        links = page.query_selector_all("a[href*='go_view']")
        print(f"[확인] go_view 링크 {len(links)}개 발견\n")

        items = []
        for link in links:
            href = link.get_attribute("href") or ""
            match = re.search(r"go_view\((\d+)\)", href)
            if not match:
                continue

            pbanc_sn = match.group(1)

            tit = link.query_selector("p.tit")
            title = tit.inner_text().strip() if tit else ""
            if not title:
                continue

            org = ""
            lis = link.query_selector_all("ul li")
            if len(lis) >= 2:
                org = lis[1].inner_text().strip()

            deadline = ""
            deadline_el = link.query_selector(".right p.txt")
            if deadline_el:
                deadline = deadline_el.inner_text().strip()

            items.append({
                "pbancSn": pbanc_sn,
                "title": title,
                "url": f"{LIST_URL}?pbancSn={pbanc_sn}",
                "org": org,
                "deadline": deadline,
            })

        browser.close()

    if not items:
        print("[실패] 공고를 찾지 못했습니다. 사이트 HTML 구조를 확인하세요.")
        return

    print(f"[결과] 총 {len(items)}개 공고 수집 성공\n")
    print("-" * 60)
    for i, item in enumerate(items[:5], 1):
        print(f"[{i}] {item['title']}")
        if item["org"]:
            print(f"     주관: {item['org']}")
        if item["deadline"]:
            print(f"     기간: {item['deadline']}")
        print(f"     URL: {item['url']}")
        print()

    if len(items) > 5:
        print(f"  ... 외 {len(items) - 5}개")


if __name__ == "__main__":
    test_fetch()
