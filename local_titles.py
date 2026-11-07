"""
웹(GitHub 서버)에서 접속이 막히는 대상의 공지 제목을 내 PC에서 읽어 config.yaml 의 manual_items 에 넣는다.

config.yaml 의 web_skip 에 적힌 대상만 읽는다. 웹 버전은 이 대상들을 크롤링하지 않고 manual_items 를 공지 목록에 보여 준다.
실행:  python local_titles.py   → 끝나면 git add config.yaml → commit → push
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

import crawler

KEEP = 15   # 대상마다 최근 제목 몇 개까지 둘지


def main() -> int:
    cfg = crawler.load_config()
    skip = cfg.get("web_skip") or []
    srcs = {s["name"]: s for s in cfg["sources"]}
    old = [m for m in cfg.get("manual_items") or [] if m.get("source") not in skip]   # 손으로 넣은 다른 항목은 그대로
    added = {(m.get("source"), m.get("title")): m.get("added") for m in cfg.get("manual_items") or []}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fresh = []
    for name in skip:
        src = srcs.get(name)
        if not src:
            print(f"[건너뜀] sources 에 없는 이름: {name}")
            continue
        r = crawler.test_source(src)
        if not r.get("ok"):
            print(f"[실패] {name}: {r.get('error') or r.get('warnings')}")
            fresh += [m for m in cfg.get("manual_items") or [] if m.get("source") == name]   # 실패하면 예전 것 유지
            continue
        if r["kind"] == "board":
            rows = [{"title": it["title"], "date": it["date"], "url": it["url"]} for it in r["items"][:KEEP]]
        else:   # 페이지 변경 감시 대상: keywords 가 든 줄만 제목으로
            kws = src.get("keywords") or []
            lines = r["lines"]
            rows = []
            for i, l in enumerate(lines):
                if kws and not any(k.lower() in l.lower() for k in kws):
                    continue
                nxt = lines[i + 1] if i + 1 < len(lines) else ""   # 제목 바로 다음 줄이 날짜면 붙인다
                rows.append({"title": l, "date": crawler.norm_date(nxt) if re.fullmatch(r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}", nxt) else "",
                             "url": src["url"]})
            rows = rows[:KEEP]
        for row in rows:
            row["added"] = added.get((name, row["title"])) or now
            fresh.append({"source": name, **row})
        print(f"[완료] {name}: {len(rows)}개")
    cfg["manual_items"] = old + fresh
    crawler.save_config(cfg)
    print(f"manual_items {len(cfg['manual_items'])}개 저장 → config.yaml (커밋·푸시하면 사이트에 반영)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
