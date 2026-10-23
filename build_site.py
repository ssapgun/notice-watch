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

import crawler

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

    new = crawler.run_crawl(store, run_cfg, progress=progress)
    print(f"새 항목 {new}건")

    ok = crawler.visible_filter(cfg)   # 필터를 바꾸기 전에 모인 글도 현재 필터로 가린다
    with store.lock:
        rows = [dict(r) for r in store.db.execute(
            "SELECT id, grp, source, date, title, url, change, kind, found_at, is_read FROM items "
            "ORDER BY COALESCE(NULLIF(date,''), substr(found_at,1,10)) DESC, id DESC").fetchall()]
    items = [r for r in rows if ok(r)][:MAX_ITEMS]
    payload = {
        "generated_at": crawler.now_str(),
        "last_run": store.get_meta("last_run"),
        "new_this_run": new,
        "auto_check_hours": cfg.get("auto_check_hours", 6),
        "sources": cfg["sources"],
        "excluded": cfg.get("excluded", []),
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
