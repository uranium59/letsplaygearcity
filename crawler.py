import argparse
import re
import requests
from bs4 import BeautifulSoup, Tag
import time
import json
import os
from collections import deque
from urllib.parse import urljoin, urlparse, parse_qs

# --- 설정 ---
BASE_URL = "https://wiki.gearcity.info/doku.php?id=start"
DOMAIN = "wiki.gearcity.info"
DELAY = float(os.getenv("WIKI_CRAWL_DELAY", "5.0"))  # 매너 딜레이 (초)
REQUEST_TIMEOUT = 15  # 요청 타임아웃 (초)
OUTPUT_FILE = "data/wiki/gearcity_wiki_data.json"

# --- 페이지 필터링 ---
# 전체 섹션 블랙리스트 (page_id 접두사로 매칭)
IGNORE_PREFIXES = [
    "troubleshooting:",     # 트러블슈팅, 로그파일, 재설치
    "modtools:",            # 모드 툴, 에디터
    "artwork:",             # 3D 모델링, DDS 텍스처
    "start:",               # 게임 소개/역사 ("start" 인덱스는 유지)
]

# 개별 페이지 블랙리스트 (인게임 플레이와 무관한 페이지)
IGNORE_PAGES = {
    "gamemanual:settings",                      # 그래픽/오디오/렌더러 설정
    "gamemanual:gui_standalone",                 # 독립형 차체 디자이너 (인게임 아님)
    "gamemanual:gui_help_menu",                  # 도움말 메뉴 설명
    "gamemanual:gui_main_menu",                  # 메인 메뉴 UI
    "gamemanual:gui_new_game",                   # 새 게임 화면 UI
    "gamemanual:gui_dynamicreports",             # 리포트 뷰어 UI
    "gamemanual:gui_reports",                    # 리포트 뷰어 UI
    "gamemanual:game_manual_intro",              # "매뉴얼에 오신 것을 환영합니다"
    "gamemanual:adjusting_saving_windows",       # 창 크기 조절법
    "gamemanual:switching_steam_builds",         # Steam 빌드 전환
    "gamemanual:installing_mods_steamworkshop",  # 모드 설치 (Steamworkshop)
    "gamemanual:installing_map",                 # 맵 수동 설치
    "gamemanual:installing_mods",                # 모드 수동 설치
}

# 본문에서 제거할 DokuWiki UI 요소의 선택자
NOISE_SELECTORS = [
    {"class": "toc"},           # 목차 (Table of Contents)
    {"class": "dw__toc"},       # DokuWiki TOC 래퍼
    {"class": "page-tools"},    # 하단 페이지 도구
    {"class": "breadcrumbs"},   # 상단 경로 표시
    {"id": "dokuwiki__header"}, # 사이트 헤더
    {"id": "dokuwiki__footer"}, # 사이트 푸터
    {"class": "tools"},         # 사이드 도구 모음
    {"class": "pageId"},        # 페이지 ID 표시 (breadcrumb 잔여)
]


def get_page_id(url):
    """URL에서 DokuWiki page ID를 추출한다. (예: 'gamemanual:gm_sales')"""
    qs = parse_qs(urlparse(url).query)
    return qs.get("id", [""])[0]


def is_valid_url(url):
    """같은 도메인의 위키 페이지만 수집, 블랙리스트 페이지 제외"""
    parsed = urlparse(url)
    if parsed.netloc != DOMAIN or "doku.php" not in parsed.path:
        return False
    if "do=" in parsed.query:
        return False

    page_id = get_page_id(url)
    if not page_id:
        return False

    # 섹션 블랙리스트
    if any(page_id.startswith(prefix) for prefix in IGNORE_PREFIXES):
        return False

    # 개별 페이지 블랙리스트
    if page_id in IGNORE_PAGES:
        return False

    return True


def clean_text(text):
    """지저분한 공백 정리: 연속 공백은 하나로, 연속 빈 줄은 두 줄까지만 허용."""
    text = re.sub(r"[ \t]+", " ", text)          # 가로 공백 정리
    text = re.sub(r"\n{3,}", "\n\n", text)       # 3줄 이상 빈 줄 → 2줄
    return text.strip()


def strip_anchor(url):
    """URL에서 #앵커 부분을 제거한다."""
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def extract_title(soup, url):
    """
    페이지 고유 제목을 추출한다.
    우선순위: 본문 내 첫 h1/h2/h3 (TOC 제외) → URL의 id 파라미터 → 'No Title'
    """
    content = soup.find(id="dokuwiki__content")
    if content:
        for heading in content.find_all(["h1", "h2", "h3"]):
            # TOC 내부 헤딩은 건너뛴다
            if heading.find_parent(class_="toc") or heading.find_parent(class_="dw__toc"):
                continue
            text = heading.get_text(strip=True)
            if text:
                return text

    # fallback: URL의 id= 파라미터에서 추출
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    page_id = qs.get("id", [""])[0]
    if page_id:
        # "gamemanual:howto_vehiclepricing" → "Howto Vehiclepricing"
        name = page_id.split(":")[-1]
        return name.replace("_", " ").title()

    return "No Title"


def table_to_markdown(table_tag):
    """HTML <table>을 Markdown 테이블 문자열로 변환한다."""
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            cells.append(cell.get_text(strip=True))
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # 열 수 통일
    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    lines = []
    header = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in rows[0]) + " |"
    lines.append(header)
    lines.append(separator)
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def extract_content(soup):
    """
    본문 영역(#dokuwiki__content)에서 노이즈를 제거하고,
    테이블은 Markdown으로 변환하여 깨끗한 텍스트를 반환한다.
    """
    content = soup.find(id="dokuwiki__content")
    if not content:
        # fallback
        content = soup.find("div", {"class": "dokuwiki"})
    if not content:
        return None

    # 노이즈 요소 제거
    for selector in NOISE_SELECTORS:
        for tag in content.find_all(**selector):
            tag.decompose()

    # <table>을 Markdown 텍스트 노드로 치환
    for table in content.find_all("table"):
        md_table = table_to_markdown(table)
        table.replace_with(md_table)

    # 헤딩에 줄바꿈을 넣어 구조를 유지
    for level in range(1, 7):
        for h in content.find_all(f"h{level}"):
            prefix = "#" * level
            h.replace_with(f"\n\n{prefix} {h.get_text(strip=True)}\n")

    # <li>에 bullet 추가
    for li in content.find_all("li"):
        li.insert(0, "- ")
        li.append("\n")

    # <br> → 줄바꿈
    for br in content.find_all("br"):
        br.replace_with("\n")

    raw = content.get_text()

    # 마지막에 남는 DokuWiki 푸터 잔여물 제거
    raw = re.sub(
        r"\S+\.txt\s*·\s*Last modified:.*$",
        "", raw, flags=re.DOTALL,
    )

    return clean_text(raw)


def save_progress(wiki_data, output_file):
    """수집된 데이터를 중간 저장한다."""
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(wiki_data, f, ensure_ascii=False, indent=2)


def crawl(start_url, max_depth=None, output_file=OUTPUT_FILE):
    """
    BFS 방식으로 위키를 크롤링한다.
    max_depth: None이면 전체 크롤링, 숫자면 해당 깊이까지만 탐색.
               depth 0 = start_url만, 1 = start_url + 거기서 발견된 링크, ...
    """
    visited = set()
    wiki_data = []
    # (url, depth) 튜플로 관리
    queue = deque([(start_url, 0)])

    while queue:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        depth_tag = f"d{depth}" if max_depth is not None else ""
        print(f"[{len(wiki_data)+1}] {depth_tag} Crawling: {url}  (queue: {len(queue)})")

        try:
            response = requests.get(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                print(f"  Failed: {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            # 1. 제목 추출 (페이지 고유 제목)
            title_text = extract_title(soup, url)

            # 2. 링크를 먼저 수집 (extract_content가 soup를 변형하므로)
            found_links = []
            if max_depth is None or depth < max_depth:
                content_for_links = soup.find(id="dokuwiki__content") or soup.find("div", {"class": "dokuwiki"})
                if content_for_links:
                    for link in content_for_links.find_all("a", href=True):
                        full_url = strip_anchor(urljoin(url, link["href"]))
                        if is_valid_url(full_url) and full_url not in visited:
                            found_links.append(full_url)

            # 3. 본문 추출 (노이즈 제거 + 테이블 Markdown 변환)
            body_text = extract_content(soup)
            if not body_text:
                continue

            # 4. 데이터 저장
            page_data = {
                "url": url,
                "title": title_text,
                "depth": depth,
                "content": body_text,
            }
            wiki_data.append(page_data)

            # 5. 중간 저장 (10페이지마다)
            if len(wiki_data) % 10 == 0:
                save_progress(wiki_data, output_file)
                print(f"  [Checkpoint] {len(wiki_data)} pages saved.")

            # 6. 수집한 링크를 큐에 추가
            for link_url in found_links:
                if link_url not in visited:
                    queue.append((link_url, depth + 1))

        except Exception as e:
            print(f"  Error: {e}")

        time.sleep(DELAY)

    return wiki_data


def parse_args():
    parser = argparse.ArgumentParser(description="GearCity Wiki Crawler")
    parser.add_argument(
        "--url", default=BASE_URL,
        help=f"시작 URL (default: {BASE_URL})",
    )
    parser.add_argument(
        "--depth", type=int, default=None,
        help="탐색 깊이 제한. 0=시작페이지만, 1=시작+직접링크, ... (미지정=전체)",
    )
    parser.add_argument(
        "--delay", type=float, default=DELAY,
        help=f"요청 간 딜레이 초 (default: {DELAY})",
    )
    parser.add_argument(
        "-o", "--output", default=OUTPUT_FILE,
        help=f"출력 JSON 경로 (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--no-filter", action="store_true",
        help="페이지 필터링 비활성화 (모든 페이지 수집)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    DELAY = args.delay

    # --no-filter 시 블랙리스트 비우기
    if args.no_filter:
        IGNORE_PREFIXES.clear()
        IGNORE_PAGES.clear()
        print("[Filter OFF] All pages will be collected.")

    depth_str = f"depth={args.depth}" if args.depth is not None else "unlimited"
    filtered = len(IGNORE_PREFIXES) + len(IGNORE_PAGES)
    print(f"--- GearCity Wiki Crawler Start ({depth_str}, {filtered} filter rules) ---")

    wiki_data = crawl(args.url, max_depth=args.depth, output_file=args.output)

    # 최종 저장
    save_progress(wiki_data, args.output)
    print(f"--- Crawling Finished. Total Pages: {len(wiki_data)} ---")