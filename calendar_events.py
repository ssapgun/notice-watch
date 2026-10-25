"""
시험 일정 캘린더

- config.yaml 의 exams: 직접 적어 둔 시험 일정 (확인된 날짜만). 날짜가 없는 시험은 status(상시·미발표·미정)로 둔다.
- config.yaml 의 academic_calendar: 학사 공지(복학·수강신청·등록 등)에서 기간을 자동으로 뽑아 일정에 더한다.
- docs/calendar.ics 로 내보내 구글 캘린더에서 'URL로 추가'해 구독할 수 있다.
- 텔레그램이 켜져 있으면 접수 마감·시험 며칠 전에 한 번씩 알린다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta

import crawler

# 일정 종류별 미리 알림 (며칠 전). config.yaml 의 calendar_alert_days 로 바꿀 수 있다
DEFAULT_ALERT_DAYS = {"접수 시작": [0], "접수 마감": [3, 0], "시험": [7, 1], "결과 발표": [0], "공지 기간": [3, 0], "행사": [7, 1]}

FULL = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?")
MD_WEEK = re.compile(r"(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?\s*\(\s*[월화수목금토일]")
RANGE_SEP = re.compile(r"^\s*\)?\s*(?:\(\s*[월화수목금토일]\s*\))?\s*(?:\d{1,2}\s*:\s*\d{2})?\s*[~∼–-]")
# 기간 뒤쪽이 연도·요일 없이 '~ 1월 8일' / '~ 11. 6.' 로만 적힌 경우
RANGE_TAIL = re.compile(r"^\s*\)?\s*(?:\(\s*[월화수목금토일]\s*\))?\s*(?:\d{1,2}\s*:\s*\d{2})?\s*[~∼–-]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def _d(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_periods(text: str, base_year: int) -> list[tuple[date, date]]:
    """'2026. 11. 2.(월) ~ 11. 6.(금)', '2026.11.02 ~ 2026.11.06' 같은 기간을 찾는다.
    연도가 없는 날짜는 요일 표시 '(월)' 이 붙은 것만 인정한다 (오인식 방지)."""
    marks = []
    for m in FULL.finditer(text):
        dd = _d(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dd:
            marks.append((m.start(), m.end(), dd))
    for m in MD_WEEK.finditer(text):
        if any(s <= m.start() < e for s, e, _ in marks):
            continue
        dd = _d(base_year, int(m.group(1)), int(m.group(2)))
        if dd:
            marks.append((m.start(), m.end(), dd))
    marks.sort()
    out = []
    i = 0
    while i < len(marks):
        s, e, start = marks[i]
        end = start
        if i + 1 < len(marks) and len(text[e:marks[i + 1][0]]) <= 25 and RANGE_SEP.search(text[e:marks[i + 1][0]]):
            end = marks[i + 1][2]
            i += 1
        else:
            t = RANGE_TAIL.match(text[e:e + 40])
            if t:
                end = _d(start.year, int(t.group(1)), int(t.group(2))) or start
        if end < start:   # 12월 ~ 1월
            end = _d(start.year + (1 if end.month < start.month else 0), end.month, end.day) or start
            if end < start:
                end = start
        out.append((start, end))
        i += 1
    return out


def exam_events(cfg: dict) -> list[dict]:
    out = []
    for ex in cfg.get("exams") or []:
        for ev in ex.get("events") or []:
            out.append({
                "exam": ex["name"], "category": ex.get("category", ""), "label": ev.get("label", ""),
                "type": ev["type"], "date": str(ev["date"]), "time": ev.get("time", ""),
                "url": ev.get("url") or ex.get("url", ""), "note": ev.get("note", ""),
                "remind": ex.get("remind"), "auto": False,
            })
    return out


def academic_events(store: crawler.Store, cfg: dict, today: date) -> list[dict]:
    """학사 공지에서 신청 기간을 뽑는다. 제목에 keywords 중 하나가 든 글만, 끝나는 날이 오늘 이후인 기간만."""
    ac = cfg.get("academic_calendar") or {}
    sources, kws = ac.get("sources") or [], ac.get("keywords") or []
    if not sources or not kws:
        return []
    ok = crawler.visible_filter(cfg)
    q = ",".join("?" * len(sources))
    with store.lock:
        rows = [dict(r) for r in store.db.execute(
            f"SELECT source, date, title, url, summary, kind FROM items WHERE source IN ({q})", sources).fetchall()]
    out, seen = [], set()
    for r in rows:
        if not ok(r) or not any(k in r["title"] for k in kws):
            continue
        pts = json.loads(r["summary"]) if r.get("summary") else []
        text = r["title"] + "\n" + "\n".join(pts)
        base = int((r["date"] or str(today))[:4])
        n_found = 0
        for start, end in find_periods(text, base):
            if n_found >= 3:   # 한 공지에서 최대 3개 기간
                break
            if end < today or end > today + timedelta(days=200):
                continue
            key = (r["url"], end)
            if key in seen:
                continue
            seen.add(key)
            n_found += 1
            title = re.sub(r"^\s*\[[^\]]{1,10}\]\s*", "", r["title"])
            out.append({
                "exam": title, "category": "학사", "label": "",
                "type": "공지 기간", "date": end.isoformat(), "time": "",
                "start": start.isoformat() if start != end else "",
                "url": r["url"], "note": "공지 본문에서 자동으로 뽑은 기간이다. 원문으로 확인할 것.",
                "remind": None, "auto": True,
            })
    return out


def all_events(store: crawler.Store, cfg: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    evs = exam_events(cfg) + academic_events(store, cfg, today)
    for e in evs:
        e["id"] = hashlib.md5(f"{e['exam']}|{e['label']}|{e['type']}|{e['date']}".encode()).hexdigest()[:12]
    return sorted(evs, key=lambda e: (e["date"], e["time"] or "99"))


def undated(cfg: dict) -> list[dict]:
    return [{"name": ex["name"], "category": ex.get("category", ""), "status": ex.get("status", "미정"),
             "note": ex.get("note", ""), "url": ex.get("url", "")}
            for ex in cfg.get("exams") or [] if ex.get("status")]


# ---------------------------------------------------------------- 구글 캘린더 구독용 .ics
def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    b = line.encode("utf-8")
    if len(b) <= 74:
        return line
    parts, cur = [], b""
    for ch in line:
        c = ch.encode("utf-8")
        if len(cur) + len(c) > 73:
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += c
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def build_ics(events: list[dict], name: str = "공지·입시 감시 시험 일정") -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//notice-watch//exam-calendar//KO",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}", "X-WR-TIMEZONE:Asia/Seoul"]
    for e in events:
        d = date.fromisoformat(e["date"])
        start = date.fromisoformat(e["start"]) if e.get("start") else d
        title = f"[{e['type']}] {e['exam']}" + (f" {e['label']}" if e["label"] else "") + (f" {e['time']}" if e["time"] else "")
        desc = "\n".join(x for x in [e.get("note", ""), e.get("url", "")] if x)
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@notice-watch", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_esc(title)}", f"DESCRIPTION:{_esc(desc)}"]
        if e.get("url"):
            lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


# ---------------------------------------------------------------- 텔레그램 미리 알림
def due_reminders(store: crawler.Store, cfg: dict, events: list[dict], today: date | None = None) -> list[tuple[dict, int]]:
    """오늘 보내야 할 (일정, 며칠 전) 목록. 한 번 보낸 것은 meta 에 기록해 다시 보내지 않는다."""
    today = today or date.today()
    days_map = {**DEFAULT_ALERT_DAYS, **(cfg.get("calendar_alert_days") or {})}
    out = []
    for e in events:
        if e.get("remind") is not None and e["type"] not in (e["remind"] or []):
            continue
        left = (date.fromisoformat(e["date"]) - today).days
        for n in days_map.get(e["type"], []):
            # 정확히 n일 전이거나, 확인이 늦게 돌아 지나쳤으면 그다음 확인에서 (아직 날짜 전이면) 보낸다
            if 0 <= left <= n and not store.get_meta(f"rem|{e['id']}|{n}"):
                out.append((e, left))
                break
    return out


def mark_sent(store: crawler.Store, cfg: dict, sent: list[tuple[dict, int]]) -> None:
    days_map = {**DEFAULT_ALERT_DAYS, **(cfg.get("calendar_alert_days") or {})}
    for e, left in sent:
        for n in days_map.get(e["type"], []):
            if left <= n:   # 이 시점까지의 알림은 모두 보낸 것으로
                store.set_meta(f"rem|{e['id']}|{n}", crawler.now_str())


def reminder_text(items: list[tuple[dict, int]], site_url: str = "") -> str:
    parts = [f"[공지·입시 감시] 다가오는 일정 {len(items)}건"]
    for e, left in items:
        dday = "오늘" if left == 0 else f"D-{left}"
        title = f"{e['exam']}" + (f" {e['label']}" if e["label"] else "")
        parts.append(f"{dday} · {e['type']} · {e['date']}{(' ' + e['time']) if e['time'] else ''}\n{title}"
                     + (f"\n{e['url']}" if e.get("url") else ""))
    if site_url:
        parts.append(site_url)
    return "\n\n".join(parts)
