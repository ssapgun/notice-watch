"""
웹 버전용 실행 스크립트 (GitHub Actions 가 6시간마다 실행한다)

1. config.yaml 의 감시 대상을 확인한다 (crawler.py 의 엔진을 그대로 사용).
2. 결과를 data/notices.db, data/page_snapshots/ 에 저장한다 (저장소에 커밋되어 다음 실행으로 이어진다).
3. 웹 화면이 읽을 docs/data/data.json 을 만든다.

내 PC에서 시험할 때:  python build_site.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import calendar_events
import crawler
import notify
import summarize

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUT = BASE / "docs" / "data" / "data.json"
MAX_ITEMS = 1500


def main() -> int:
    DATA.mkdir(exist_ok=True)
    crawler.SNAP_DIR = DATA / "page_snapshots"   # 로컬 대시보드(app.py)의 데이터와 섞이지 않게 분리
    store = crawler.Store(DATA / "notices.db")
    cfg = crawler.load_config()

    # 웹에서 잘못 저장된 대상이 있어도 나머지는 돌아가게: 검사에 실패한 대상은 오류로만 기록
    valid = []
    for src in cfg["sources"]:
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

    # 시험 일정: 직접 적은 시험(config exams) + 학사 공지에서 뽑은 기간 → 사이트·구글 캘린더(.ics)·텔레그램
    events = calendar_events.all_events(store, cfg)
    (OUT.parent.parent / "calendar.ics").write_text(calendar_events.build_ics(events), encoding="utf-8", newline="")
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
            " summary, title_ko, sum_mode, sum_state FROM items "
            "ORDER BY COALESCE(NULLIF(date,''), substr(found_at,1,10)) DESC, id DESC").fetchall()]
    items = [r for r in rows if ok(r)]
    for r in items:
        r["summary"] = summarize.clean_points(json.loads(r["summary"])) if r["summary"] else []
    items = crawler.collapse_reposts(items)[:MAX_ITEMS]   # 같은 게시판 재공지는 하나로
    payload = {
        "generated_at": crawler.now_str(),
        "last_run": store.get_meta("last_run"),
        "new_this_run": new,
        "summary_mode": st["mode"],
        "auto_check_hours": cfg.get("auto_check_hours", 6),
        "sources": cfg["sources"],
        "excluded": cfg.get("excluded", []),
        "links": cfg.get("links", []),
        "topics": cfg.get("topics", []),
        "calendar": {"events": events, "undated": calendar_events.undated(cfg),
                     "ics_url": (cfg.get("site_url", "").rstrip("/") + "/calendar.ics") if cfg.get("site_url") else ""},
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
