"""
텔레그램 알림

GitHub Secret(또는 PC 환경변수) TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 가 둘 다 있을 때만 보낸다. 없으면 아무것도 안 한다.
  - 이번 확인에서 새로 들어온 글 중 config.yaml 의 highlight.alert 핵심 키워드가 든 글
  - 3회 연속 실패한 감시 대상 (3회째에 한 번만)
"""
from __future__ import annotations

import os

import requests

import crawler

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 3800   # 텔레그램 메시지 최대 4096자보다 여유 있게


def enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def send(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > LIMIT and cur:
            chunks.append(cur)
            cur = ""
        cur = (cur + "\n\n" + block) if cur else block
    if cur:
        chunks.append(cur)
    for c in chunks:
        r = requests.post(API.format(token=token), timeout=20,
                          json={"chat_id": chat, "text": c[:4096], "disable_web_page_preview": True})
        if r.status_code >= 400:
            raise RuntimeError(f"텔레그램 {r.status_code}: {r.text[:150]}")


def alert_after_run(store: crawler.Store, cfg: dict, since: str, site_url: str = "") -> int:
    """since(이번 확인 시작 시각) 이후 새로 들어온 안 읽은 글 중 핵심 키워드 글 + 연속 실패 대상을 보낸다."""
    if not enabled():
        return 0
    ok = crawler.visible_filter(cfg)
    subs = {s["name"]: s.get("sub") or s["name"] for s in cfg["sources"]}
    with store.lock:
        rows = [dict(r) for r in store.db.execute(
            "SELECT grp, source, date, title, title_ko, url, summary, kind FROM items"
            " WHERE found_at >= ? AND is_read = 0 ORDER BY date DESC", (since,)).fetchall()]
    hits = [(r, crawler.highlight_hits(r, cfg, "alert")) for r in rows if ok(r)]
    hits = [(r, h) for r, h in hits if h]
    with store.lock:
        broken = [dict(r) for r in store.db.execute(
            "SELECT name, last_error FROM sources WHERE fail_count = 3").fetchall()]
    names = {s["name"] for s in cfg["sources"] if s.get("enabled", True) is not False}
    broken = [b for b in broken if b["name"] in names]
    parts = []
    if hits:
        parts.append(f"[공지·입시 감시] 핵심 키워드 새 글 {len(hits)}건")
        for r, h in hits[:30]:
            title = r["title_ko"] or r["title"]
            parts.append(f"{r['grp']} / {subs.get(r['source'], r['source'])} · {r['date'] or ''}\n"
                         f"{title}\n키워드: {', '.join(h)}\n{r['url']}")
        if len(hits) > 30:
            parts.append(f"…외 {len(hits) - 30}건은 사이트에서 확인")
    if broken:
        parts.append("[공지·입시 감시] 3회 연속 실패한 감시 대상\n" + "\n".join(
            f"- {b['name']}: {(b['last_error'] or '')[:120]}" for b in broken))
    if not parts:
        return 0
    if site_url:
        parts.append(site_url)
    send("\n\n".join(parts))
    return len(hits) + len(broken)
