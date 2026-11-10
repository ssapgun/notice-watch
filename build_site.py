"""
웹 버전용 실행 스크립트 (GitHub Actions 가 6시간마다 실행한다)

1. config.yaml 의 감시 대상을 확인한다 (crawler.py 의 엔진을 그대로 사용).
2. 결과를 data/notices.db, data/page_snapshots/ 에 저장한다 (저장소에 커밋되어 다음 실행으로 이어진다).
3. 웹 화면이 읽을 docs/data/data.json 을 만든다.

내 PC에서 시험할 때:  python build_site.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import calendar_events
import crawler
import notify
import summarize

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUT = BASE / "docs" / "data" / "data.json"
ICS = BASE / "docs" / "calendar.ics"
MAX_ITEMS = 1500


def calendar_payload(cfg: dict, events: list[dict]) -> dict:
    return {"events": events, "undated": calendar_events.undated(cfg),
            "ics_url": (cfg.get("site_url", "").rstrip("/") + "/calendar.ics") if cfg.get("site_url") else "",
            "gcal": bool(cfg.get("google_calendar_url")), "gcal_url": cfg.get("google_calendar_url", ""),
            "synced_at": crawler.now_str()}


def write_calendar(store: crawler.Store, cfg: dict) -> None:
    """확인(크롤링) 없이 일정 부분만 다시 만든다. gcal_sync.py 가 쓴다."""
    events = calendar_events.all_events(store, cfg)
    ICS.write_text(calendar_events.build_ics(events, cfg=cfg), encoding="utf-8", newline="")
    if OUT.exists():
        d = json.loads(OUT.read_text(encoding="utf-8"))
        new = calendar_payload(cfg, events)
        old = {k: v for k, v in (d.get("calendar") or {}).items() if k != "synced_at"}
        if old == {k: v for k, v in new.items() if k != "synced_at"}:
            return   # 바뀐 일정이 없으면 그대로 둔다
        d["calendar"] = new
        OUT.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def manual_items(cfg: dict) -> list[dict]:
    """config.yaml 의 manual_items(웹에서 못 읽는 대상의 공지 제목, local_titles.py 가 채운다)를 목록 항목 모양으로."""
    grp = {s["name"]: s.get("group", "") for s in cfg.get("sources", [])}
    out = []
    for m in cfg.get("manual_items") or []:
        if not m.get("title"):
            continue
        key = f"{m.get('source', '')}|{m['title']}"
        out.append({"id": "m" + hashlib.md5(key.encode()).hexdigest()[:10], "grp": m.get("group") or grp.get(m.get("source"), "기타"),
                    "source": m.get("source", ""), "date": m.get("date", ""), "title": m["title"], "url": m.get("url", ""),
                    "change": "", "kind": "manual", "found_at": m.get("added", ""), "is_read": 0,
                    "summary": [m["note"]] if m.get("note") else [], "title_ko": None, "sum_mode": "", "sum_state": "manual"})
    return out


def main() -> int:
    DATA.mkdir(exist_ok=True)
    crawler.SNAP_DIR = DATA / "page_snapshots"   # 로컬 대시보드(app.py)의 데이터와 섞이지 않게 분리
    store = crawler.Store(DATA / "notices.db")
    cfg = crawler.load_config()

    # 웹에서 잘못 저장된 대상이 있어도 나머지는 돌아가게: 검사에 실패한 대상은 오류로만 기록
    # web_skip: GitHub 서버(해외)에서 접속이 막히는 대상. 웹에서는 건너뛰고 manual_items(내 PC에서 읽은 제목)로 대신 보여 준다
    skip = set(cfg.get("web_skip") or [])
    valid = []
    for src in cfg["sources"]:
        if src.get("name") in skip:
            with store.lock:   # 예전 실패 기록이 상태표에 오류로 남지 않게
                store.db.execute("DELETE FROM sources WHERE name=?", (src["name"],))
                store.db.commit()
            continue
        try:
            clean = crawler.clean_source(src)
        except ValueError as e:
            store.set_source(src, ok=False, error=f"설정 오류: {e}")
            print(f"[설정 오류] {src.get('name')}: {e}")
            continue
        valid.append(clean)
    run_cfg = {**cfg, "sources": valid}

    def progress(p: dict) -> None:
        if p["current"]:
            print(f"  {p['done'] + 1}/{p['total']}  {p['current']}", flush=True)

    started = crawler.now_str()
    new = crawler.run_crawl(store, run_cfg, progress=progress)
    print(f"새 항목 {new}건")

    # 공지 정리·번역 (ANTHROPIC_API_KEY 비밀값이 있으면 Claude, 없으면 본문 발췌)
    st = summarize.summarize_pending(store, cfg, progress=lambda m: print("  " + m, flush=True))
    print(f"공지 정리 {st['done']}건, 실패 {st.get('failed', 0)}건, 남은 글 {st.get('left', 0)}건 ({st['mode']})")

    # 텔레그램 알림 (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 비밀값이 있을 때만)
    try:
        n = notify.alert_after_run(store, cfg, started, cfg.get("site_url", ""))
        print(f"텔레그램 알림 {n}건" if notify.enabled() else "텔레그램 알림 꺼짐 (토큰 없음)")
    except Exception as e:   # 알림이 실패해도 사이트 갱신은 계속
        print(f"[알림 오류] {type(e).__name__}: {e}")

    # 일정: schedule.json(웹·구글 캘린더에서 고침) + 학사 공지에서 뽑은 기간 → 사이트·calendar.ics·텔레그램
    events = calendar_events.all_events(store, cfg)
    ICS.write_text(calendar_events.build_ics(events, cfg=cfg), encoding="utf-8", newline="")
    try:
        due = calendar_events.due_reminders(store, cfg, events)
        if due and notify.enabled():
            notify.send(calendar_events.reminder_text(due, cfg.get("site_url", "")))
            calendar_events.mark_sent(store, cfg, due)
            print(f"일정 알림 {len(due)}건")
    except Exception as e:
        print(f"[일정 알림 오류] {type(e).__name__}: {e}")

    ok = crawler.visible_filter(cfg)   # 필터를 바꾸기 전에 모인 글도 현재 필터로 가린다
    with store.lock:
        rows = [dict(r) for r in store.db.execute(
            "SELECT id, grp, source, date, title, url, change, kind, found_at, is_read,"
            " summary, title_ko, sum_mode, sum_state, images FROM items "
            "ORDER BY COALESCE(NULLIF(date,''), substr(found_at,1,10)) DESC, id DESC").fetchall()]
    # 분류는 지금 설정을 따른다 (대상을 다른 분류로 옮기면 예전 글도 함께 옮겨 보인다). 설정에서 지운 대상의 글은 뺀다
    grp_of = {s["name"]: s.get("group", "") for s in cfg["sources"]}
    renamed = cfg.get("renamed_sources") or {}   # 이름을 바꾼 대상: 예전 이름으로 모인 글도 새 이름으로
    rows = [{**r, "source": renamed.get(r["source"], r["source"])} for r in rows]
    rows = [{**r, "grp": grp_of[r["source"]]} for r in rows if r["source"] in grp_of]
    items = [r for r in rows if ok(r)]
    for r in items:
        r["summary"] = summarize.clean_points(json.loads(r["summary"])) if r["summary"] else []
        imgs = json.loads(r["images"]) if r.get("images") else []
        # 이미지는 본문이 이미지뿐인 공지에만 싣는다 (원본 주소만, 복사하지 않음)
        r["images"] = imgs if r.get("sum_state") in ("image_only", "empty") else []
        if not r["images"]:
            r.pop("images")
    items = crawler.collapse_reposts(items)[:MAX_ITEMS]   # 같은 게시판 재공지는 하나로
    items = sorted(items + manual_items(cfg), key=lambda r: r["date"] or r["found_at"][:10], reverse=True)
    payload = {
        "generated_at": crawler.now_str(),
        "last_run": store.get_meta("last_run"),
        "new_this_run": new,
        "summary_mode": st["mode"],
        "auto_check_hours": cfg.get("auto_check_hours", 6),
        "sources": cfg["sources"],
        "excluded": cfg.get("excluded", []),
        "links": cfg.get("links", []),
        "group_folders": cfg.get("group_folders", []),
        "sub_rules": cfg.get("sub_rules", {}),
        "flat_groups": cfg.get("flat_groups", []),
        "topics": cfg.get("topics", []),
        "calendar": calendar_payload(cfg, events),
        "highlight": {k: v for k, v in (cfg.get("highlight") or {}).items() if k in ("keywords", "exclude", "alert")},
        "status": store.sources(),
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    errs = [s for s in store.sources() if s["last_error"]]
    for s in errs:
        print(f"[오류] {s['name']}: {s['last_error']}")
    print(f"data.json 저장: 항목 {len(items)}개, 오류 {len(errs)}곳")
    return 0


if __name__ == "__main__":
    sys.exit(main())
