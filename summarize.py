"""
공지 정리·번역 모듈

새로 모인 게시판 글의 상세 페이지를 한 번 읽어 본문을 뽑고, 한국어로 정리한다.
  - ANTHROPIC_API_KEY 가 있으면: Claude 가 핵심을 항목별로 정리한다. 외국어 글은 한국어로 번역한다.
    본문이 이미지(포스터)뿐인 글은 이미지를 읽어 정리한다.
  - 키가 없으면: 본문 앞부분을 그대로 발췌한다 (번역 없음).
첨부파일은 읽지 않는다. 원문 링크는 화면이 정리 끝에 항상 붙인다.

크롤러 원칙은 그대로 지킨다: 상세 페이지·이미지도 robots.txt 확인, 요청 사이 대기, 같은 User-Agent.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Callable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import crawler

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"
MAX_TEXT = 6000          # 모델에 보내는 본문 최대 글자 수
MAX_IMAGES = 3           # 본문이 짧을 때 함께 보내는 이미지 수
MAX_IMAGE_BYTES = 3_500_000
MAX_TRIES = 3            # 실패한 글을 다시 시도하는 횟수
EXTRACT_VERSION = "2"    # 본문 뽑는 방식을 바꾸면 올린다 → 발췌해 둔 글을 새 방식으로 다시 뽑는다
BLOCKS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "dd", "dt",
          "section", "article", "blockquote", "pre"]

# 상세 페이지 본문 칸 (설정의 detail_selector 가 없을 때 차례로 찾는다)
DETAIL_FALLBACK = [".bbs-view_c", ".row.contents", "#bo_v_con", ".fr-view", ".border-view-con",
                   ".c-post", ".contentArea", ".entry-content", "article", "main", "#content"]
# 본문에서 지울 부분: 첨부파일 목록, 메뉴, 이전/다음 글 등
DROP_SELECTORS = ["script", "style", "noscript", "nav", "header", "footer", "form", "button",
                  "#bo_v_file", "#bo_v_link", ".file", ".files", ".attach", ".attachment",
                  "[class*=file-list]", "[class*=attach]", ".prev_next", ".btn-list_w"]
ATTACH_LINE = re.compile(r"(첨부\s*파일|다운로드|\.(hwp|hwpx|pdf|docx?|xlsx?|pptx?|zip)\b|添付|ダウンロード)",
                         re.I)
HANGUL = re.compile(r"[가-힣]")
SKIP_IMG = re.compile(r"(icon|btn|logo|blank|spacer|arrow|bullet|sns|share)", re.I)


# ---------------------------------------------------------------- 본문 뽑기
def extract_detail(html: str, url: str, src: dict) -> tuple[str, list[str]]:
    """(본문 글, 본문 안 이미지 주소들). 첨부파일 목록은 뺀다."""
    soup = BeautifulSoup(html, "html.parser")
    root = None
    for sel in [src.get("detail_selector"), *DETAIL_FALLBACK]:
        if sel and (root := soup.select_one(sel)) is not None:
            break
    if root is None:
        return "", []
    for sel in DROP_SELECTORS:
        for el in root.select(sel):
            el.decompose()
    images = []
    for img in root.select("img"):
        s = img.get("src") or img.get("data-src") or ""
        if s and not s.startswith("data:") and not SKIP_IMG.search(s):
            images.append(urljoin(url, s))
    # 줄은 문단·목록 같은 블록 단위로만 나눈다 (글자 꾸밈 태그에서 문장이 끊기지 않게)
    for br in root.find_all("br"):
        br.replace_with("\n")
    for el in root.find_all(BLOCKS):
        el.insert_before("\n")
        el.append("\n")
    for el in root.find_all(["td", "th"]):
        el.append(" | ")
    lines, seen = [], set()
    for raw in root.get_text("").replace("\xa0", " ").split("\n"):
        line = crawler.clean(raw)
        if len(line) < 2 or line in seen or ATTACH_LINE.search(line):
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines), images[:MAX_IMAGES]


def is_korean(text: str) -> bool:
    letters = re.findall(r"[^\W\d_]", text or "")
    return bool(letters) and len(HANGUL.findall(text)) / len(letters) >= 0.3


def excerpt(text: str, limit: int = 420) -> list[str]:
    """키가 없을 때: 본문 앞부분을 줄 단위로 잘라 쓴다."""
    out, n = [], 0
    for line in text.split("\n"):
        if n >= limit:
            break
        line = line if len(line) <= 200 else line[:200] + "…"
        out.append(line)
        n += len(line)
    return out


# ---------------------------------------------------------------- Claude 호출
PROMPT = """너는 대학 공지를 한국어로 정리하는 도우미다. 아래 공지를 읽고 JSON 하나만 출력하라.

규칙
- 원문이 한국어가 아니면 한국어로 번역해서 정리한다.
- 원문에 있는 내용만 쓴다. 추측하거나 없는 날짜·조건을 만들지 않는다.
- 첨부파일 이름이나 '첨부 참고' 같은 말은 쓰지 않는다.
- 날짜·기간·마감·대상·자격·장소·신청 방법·문의처가 있으면 반드시 포함한다.
- 항목은 3~7개, 각 항목은 한 문장. "대상: …", "기간: …" 처럼 머리말을 붙여도 된다.
- 본문이 거의 없으면 points 에 "본문에 내용이 거의 없다. 원문(첨부)에서 확인할 것" 한 줄만 쓴다.

출력 형식 (다른 말 없이 JSON 만):
{"title_ko": "제목의 한국어 번역 (원래 한국어면 그대로)", "points": ["…", "…"]}

출처: %(source)s
제목: %(title)s
본문:
%(body)s"""


def call_claude(api_key: str, model: str, source: str, title: str, body: str,
                images: list[tuple[str, str]]) -> dict:
    content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
                           for mt, b64 in images]
    content.append({"type": "text", "text": PROMPT % {
        "source": source, "title": title, "body": body[:MAX_TEXT] or "(글 없음. 이미지만 있음)"}})
    r = requests.post(API_URL, timeout=90, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 900, "messages": [{"role": "user", "content": content}]})
    if r.status_code >= 400:
        raise RuntimeError(f"API {r.status_code}: {r.text[:200]}")
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("정리 결과를 읽지 못했다")
    data = json.loads(m.group(0))
    points = [crawler.clean(str(p)) for p in data.get("points", []) if crawler.clean(str(p))]
    if not points:
        raise RuntimeError("정리 결과가 비어 있다")
    return {"title_ko": crawler.clean(str(data.get("title_ko", ""))), "points": points[:8]}


def fetch_images(urls: list[str], session: requests.Session, delay: float) -> list[tuple[str, str]]:
    out = []
    for u in urls:
        if not crawler.robots_allows(u, session):
            continue
        try:
            r = session.get(u, timeout=25)
            time.sleep(delay)
            mt = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if r.ok and mt in ("image/jpeg", "image/png", "image/gif", "image/webp") \
                    and 5_000 < len(r.content) <= MAX_IMAGE_BYTES:
                out.append((mt, base64.b64encode(r.content).decode()))
        except requests.RequestException:
            continue
    return out


# ---------------------------------------------------------------- 실행
def summarize_pending(store: crawler.Store, cfg: dict, limit: int | None = None,
                      progress: Callable[[str], None] | None = None) -> dict:
    """정리가 안 된 글을 최신순으로 limit 개까지 정리한다. 결과 개수를 돌려준다."""
    opt = cfg.get("summary", {}) or {}
    if opt.get("enabled", True) is False:
        return {"done": 0, "mode": "off"}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    mode = "llm" if api_key else "extract"
    model = opt.get("model") or DEFAULT_MODEL
    limit = int(limit or opt.get("per_run", 60))
    delay = float(cfg.get("delay_seconds", 2))
    srcs = {s["name"]: s for s in cfg["sources"]}
    visible = crawler.visible_filter(cfg)

    if store.get_meta("extract_version") != EXTRACT_VERSION:
        with store.lock:
            store.db.execute("UPDATE items SET sum_mode=NULL, sum_state=NULL, summary=NULL WHERE sum_mode='extract'")
            store.db.commit()
        store.set_meta("extract_version", EXTRACT_VERSION)

    session = requests.Session()
    session.headers["User-Agent"] = crawler.USER_AGENT
    todo = [it for it in store.pending_summaries(mode, MAX_TRIES) if visible(it) and it["source"] in srcs]
    stats = {"done": 0, "failed": 0, "mode": mode, "left": max(0, len(todo) - limit)}
    for it in todo[:limit]:
        src = srcs[it["source"]]
        if progress:
            progress(f"정리 {stats['done'] + stats['failed'] + 1}/{min(limit, len(todo))}  {it['title'][:40]}")
        try:
            res = summarize_item(it, src, session, delay, api_key, model)
            store.set_summary(it["id"], res["mode"], res.get("title_ko", ""), res["points"], res["state"])
            stats["done"] += 1
        except Exception as e:  # 한 글이 실패해도 계속
            store.summary_failed(it["id"], f"{type(e).__name__}: {e}"[:200])
            stats["failed"] += 1
    return stats


def summarize_item(it: dict, src: dict, session: requests.Session, delay: float,
                   api_key: str, model: str) -> dict:
    title = it["title"]
    if it["kind"] == "watch":  # 페이지 변경: 바뀐 문장을 정리·번역
        body, images = it.get("change") or "", []
    else:
        url = it["url"]
        list_url = crawler.page_url(src, 1) if src.get("list_url") else ""
        if not url or url == list_url:
            return {"mode": "extract", "points": [], "state": "no_detail"}
        if not crawler.robots_allows(url, session):
            return {"mode": "extract", "points": [], "state": "blocked"}
        html = crawler.fetch(url, src, session)
        time.sleep(delay)
        body, images = extract_detail(html, url, src)

    if not api_key:
        if it["kind"] == "watch":
            return {"mode": "extract", "points": [], "state": "no_key"}
        if len(body) < 30:
            return {"mode": "extract", "points": [], "state": "image_only" if images else "empty"}
        return {"mode": "extract", "points": excerpt(body), "state": "ok"}

    # 한국어 글이고 본문이 충분하면 이미지는 보내지 않는다 (비용 절약)
    imgs = fetch_images(images, session, delay) if len(body) < 300 and images else []
    if len(body) < 30 and not imgs and is_korean(title):
        return {"mode": "llm", "points": [], "state": "empty"}
    out = call_claude(api_key, model, src["name"], title, body, imgs)
    if is_korean(title):
        out["title_ko"] = ""
    return {"mode": "llm", "state": "ok", **out}
