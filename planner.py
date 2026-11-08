"""
자동 플래너 계산 (AI 없음). 사이트의 docs/planner.js 와 같은 규칙이다: 한쪽을 고치면 다른 쪽도 고칠 것.

데이터는 docs/planner.json (사이트 '플래너' 탭이 GitHub API 로 저장한다).
아침 브리핑(briefing.py)이 매일 오늘 계획을 다시 계산해 '오늘 할 강의'로 넣고, 소화율 계산용 계획량을 기록한다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

PLANNER = Path(__file__).resolve().parent / "docs" / "planner.json"
DEFAULTS = {"hours": [120, 120, 120, 120, 120, 240, 240], "off": [], "window": 7, "eta_min": 0.3}
EPS = 1e-9
LOG_KEEP_DAYS = 60


def _add(values) -> float:
    """단순 덧셈. 파이썬 3.12 의 sum() 은 보정 합산이라 JS 와 끝자리가 달라져 배정이 어긋난다."""
    total = 0.0
    for v in values:
        total += v
    return total


def settings_of(pl: dict) -> dict:
    return {**DEFAULTS, **(pl.get("settings") or {})}


def cost_of(item: dict, course: dict) -> float:
    return item["min"] * (course.get("mult") or 1)


def avail(st: dict, d: date) -> float:
    return 0 if d.isoformat() in st["off"] else (st["hours"][d.weekday()] or 0)


def eta_of(pl: dict, today: date) -> float:
    """소화율: 최근 n일 실제 완료량 / 계획량. 기록이 없으면 1, 범위는 eta_min ~ 1."""
    st, log = settings_of(pl), pl.get("log") or {}
    planned = done = 0.0
    for i in range(1, st["window"] + 1):
        d = (today - timedelta(days=i)).isoformat()
        if not (log.get(d) or {}).get("planned", 0) > 0:
            continue
        planned += log[d]["planned"]
        for c in pl.get("courses") or []:
            done += _add(cost_of(it, c) for it in c["items"] if it.get("done") == d)
    if not planned:
        return 1
    return min(1, max(st["eta_min"], done / planned))


def days_left(st: dict, d: date, deadline: date) -> int:
    n, x = 0, d
    while x <= deadline:
        if avail(st, x) > 0:
            n += 1
        x += timedelta(days=1)
    return n or 1


def compute(pl: dict, today: date) -> dict:
    st, eta = settings_of(pl), eta_of(pl, today)
    t = today.isoformat()
    courses = []
    for order, c in enumerate(pl.get("courses") or []):
        queue = [it for it in c["items"] if not it.get("done")]
        courses.append({"c": c, "order": order, "queue": queue, "remain": _add(cost_of(it, c) for it in queue),
                        "done_today": _add(cost_of(it, c) for it in c["items"] if it.get("done") == t)})
    dated = sorted((x for x in courses if x["c"].get("deadline")), key=lambda x: (x["c"]["deadline"], x["order"]))
    free = [x for x in courses if not x["c"].get("deadline")]
    done_all = _add(x["done_today"] for x in courses)
    days: list[dict] = []

    d = today
    for _ in range(730):
        if not any(x["queue"] for x in courses):
            break
        full = avail(st, d)
        if full > 0:
            is_today = d == today
            state = {"cap": max(0, full - (done_all if is_today else 0)), "placed": is_today and done_all > 0}
            items: list[dict] = []

            def take(x: dict) -> float:
                it, cost = x["queue"][0], cost_of(x["queue"][0], x["c"])
                if cost > state["cap"] + EPS and state["placed"]:   # 안 들어가면 다음 날로 (차시는 쪼개지 않는다)
                    return 0
                x["queue"].pop(0)
                x["remain"] -= cost
                state["cap"] = max(0, state["cap"] - cost)
                state["placed"] = True
                dl = x["c"].get("deadline")
                items.append({"cid": x["c"]["id"], "iid": it["id"], "course": x["c"]["name"], "title": it["title"],
                              "min": it["min"], "cost": cost, "late": bool(dl and d.isoformat() > dl)})
                return cost

            for x in dated:
                if not x["queue"]:
                    continue
                already = x["done_today"] if is_today else 0
                quota = (x["remain"] + already) / (eta * days_left(st, d, date.fromisoformat(x["c"]["deadline"]))) - already
                used = 0.0
                while x["queue"] and used < quota - EPS and (state["cap"] > EPS or not state["placed"]):
                    got = take(x)
                    if not got:
                        break
                    used += got
            for x in free:
                while x["queue"] and (state["cap"] > EPS or not state["placed"]):
                    if not take(x):
                        break
            if items or is_today:
                days.append({"date": d.isoformat(), "items": items, "total": _add(i["cost"] for i in items), "avail": full})
        d += timedelta(days=1)
    if not days or days[0]["date"] != t:
        days.insert(0, {"date": t, "items": [], "total": 0, "avail": avail(st, today)})

    # 마감 경고: 그 마감까지 끝내야 할 양 / 소화율 - 쓸 수 있는 시간 > 0 이면 못 맞춘다
    warnings: list[dict] = []
    cum = 0.0
    seen: dict[str, list[str]] = {}

    def remain_at(x: dict) -> float:
        return _add(cost_of(it, x["c"]) for it in x["c"]["items"] if not it.get("done"))

    for x in dated:
        r = remain_at(x)
        if not r:
            continue
        cum += r
        dl = x["c"]["deadline"]
        seen.setdefault(dl, []).append(x["c"]["name"])
        same = [y for y in dated if y["c"]["deadline"] == dl and remain_at(y) > 0]
        if same[-1] is not x:
            continue
        have = 0.0
        day = today
        while day.isoformat() <= dl:
            have += avail(st, day)
            day += timedelta(days=1)
        have = max(0, have - done_all)
        need = cum / eta
        if need - have > EPS:
            warnings.append({"deadline": dl, "courses": seen[dl], "need": need, "have": have,
                             "short": need - have, "overdue": dl < t})
    return {"today": t, "eta": eta, "days": days, "warnings": warnings}


def fmt_min(m: float) -> str:
    m = round(m)
    return f"{m // 60}시간 {m % 60}분" if m >= 60 and m % 60 else f"{m // 60}시간" if m >= 60 else f"{m}분"


def for_briefing(today: date) -> dict | None:
    """오늘 할 강의를 계산하고, 오늘 계획량을 log 에 남긴다 (소화율 계산용). 강의가 없으면 None."""
    if not PLANNER.exists():
        return None
    pl = json.loads(PLANNER.read_text(encoding="utf-8"))
    if not pl.get("courses"):
        return None
    r = compute(pl, today)
    first = r["days"][0]
    t = today.isoformat()
    log = pl.setdefault("log", {})
    if t not in log:
        done = _add(cost_of(it, c) for c in pl["courses"] for it in c["items"] if it.get("done") == t)
        log[t] = {"planned": round(first["total"] + done, 1)}
        cutoff = (today - timedelta(days=LOG_KEEP_DAYS)).isoformat()
        pl["log"] = {d: v for d, v in sorted(log.items()) if d >= cutoff}
        PLANNER.write_text(json.dumps(pl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"total": first["total"], "eta": r["eta"], "warnings": r["warnings"],
            "items": [{"course": i["course"], "title": i["title"], "cost": i["cost"], "late": i["late"]} for i in first["items"]]}
