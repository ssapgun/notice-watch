"""
구글 캘린더 양방향 동기화 (GitHub Actions 가 1시간마다, 그리고 웹에서 일정을 고칠 때마다 실행한다)

- 사이트 쪽 원본: schedule.json (+ 학사 공지에서 자동으로 뽑은 기간)
- 구글 쪽: 전용 캘린더 하나 (GOOGLE_CALENDAR_ID). 서비스 계정(GOOGLE_SERVICE_ACCOUNT, JSON 키)으로 접근한다.
- 어느 쪽에서 추가·수정·삭제해도 다음 동기화 때 반대쪽에 반영된다. 양쪽에서 같은 일정을 고쳤으면 나중에 고친 쪽이 이긴다.
- 사이트가 만든 구글 일정에는 extendedProperties.private.nwid 로 사이트 id 를 붙여 둔다.
- 마지막 동기화 상태는 data/gcal_state.json 에 둔다 (id → 구글 id, 구글 updated, 사이트 내용 해시).

비밀값이 없으면 구글 쪽은 건너뛰고, 사이트 일정(data.json·calendar.ics)만 다시 만든다.
내 PC에서 시험할 때:  python gcal_sync.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import calendar_events as ce
import crawler

BASE = Path(__file__).resolve().parent
STATE = BASE / "data" / "gcal_state.json"
TZ = ZoneInfo("Asia/Seoul")
MARK = "─── 공지·입시 감시 사이트와 동기화되는 일정이다. 이 줄 위의 메모·링크를 고치면 사이트에도 반영된다."
TYPES = set(ce.DEFAULT_ALERT_DAYS) | {"일정"}
API = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
TOMB_DAYS = 30


# ---------------------------------------------------------------- 구글 API (REST v3)
class GCal:
    def __init__(self, cal_id: str, session):
        from urllib.parse import quote
        self.base = API.format(cal=quote(cal_id, safe=""))
        self.s = session

    def _ok(self, r):
        if r.status_code >= 400:
            raise RuntimeError(f"구글 캘린더 {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def list(self, time_min: str, time_max: str) -> list[dict]:
        out, token = [], None
        while True:
            params = {"showDeleted": "true", "singleEvents": "true", "maxResults": 2500,
                      "timeMin": time_min, "timeMax": time_max}
            if token:
                params["pageToken"] = token
            j = self._ok(self.s.get(self.base, params=params, timeout=30))
            out += j.get("items", [])
            token = j.get("nextPageToken")
            if not token:
                return out

    def insert(self, body: dict) -> dict:
        body = {**body, **{k: {a: b for a, b in body[k].items() if b is not None} for k in ("start", "end") if k in body}}
        return self._ok(self.s.post(self.base, json=body, timeout=30))

    def patch(self, gid: str, body: dict) -> dict:
        return self._ok(self.s.patch(f"{self.base}/{gid}", json=body, timeout=30))

    def delete(self, gid: str) -> None:
        r = self.s.delete(f"{self.base}/{gid}", timeout=30)
        if r.status_code not in (200, 204, 404, 410):
            self._ok(r)


def google_client() -> GCal | None:
    raw, cal = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "").strip(), os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
    if not raw or not cal:
        return None
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/calendar"])
    return GCal(cal, AuthorizedSession(creds))


# ---------------------------------------------------------------- 사이트 일정 ↔ 구글 일정 변환
def site_hash(e: dict) -> str:
    return hashlib.md5(json.dumps([str(e.get(k) or "") for k in ce.EVENT_FIELDS], ensure_ascii=False).encode()).hexdigest()


def to_google(e: dict) -> dict:
    t = str(e.get("time") or "").strip()
    m = HHMM.match(t)
    title = f"[{e.get('type') or '일정'}] {e['exam']}" + (f" {e['label']}" if e.get("label") else "")
    d = date.fromisoformat(e["date"])
    if m and not e.get("start"):
        st = datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)))
        start = {"dateTime": st.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Asia/Seoul", "date": None}
        end = {"dateTime": (st + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Asia/Seoul", "date": None}
    else:
        if t:
            title += f" {t}"
        s = date.fromisoformat(e["start"]) if e.get("start") else d
        start = {"date": s.isoformat(), "dateTime": None, "timeZone": None}
        end = {"date": (d + timedelta(days=1)).isoformat(), "dateTime": None, "timeZone": None}
    desc = "\n".join(x for x in [e.get("note", ""), e.get("url", "")] if x)
    return {"summary": title, "description": (desc + "\n\n" if desc else "") + MARK,
            "start": start, "end": end,
            "extendedProperties": {"private": {"nwid": e["id"]}}}


def from_google(g: dict, prev: dict | None) -> dict:
    """구글 일정 → 사이트 일정. prev 는 같은 일정의 이전 사이트 내용 (분류·알림 설정을 이어받는다)."""
    prev = prev or {}
    summ = (g.get("summary") or "(제목 없음)").strip()
    m = re.match(r"^\[(.+?)\]\s*(.*)$", summ)
    typ, rest = (m.group(1).strip(), m.group(2).strip()) if m and m.group(1).strip() in TYPES else (prev.get("type") or "일정", summ)
    exam, label = rest, ""
    if prev.get("exam") and rest.startswith(prev["exam"]):
        exam, label = prev["exam"], rest[len(prev["exam"]):].strip()
    s, en = g.get("start") or {}, g.get("end") or {}
    time_, start = "", ""
    if s.get("dateTime"):
        dt = datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(TZ)
        day, time_ = dt.date(), dt.strftime("%H:%M")
        dte = datetime.fromisoformat(en["dateTime"].replace("Z", "+00:00")).astimezone(TZ).date() if en.get("dateTime") else day
        if dte > day:
            start, day = day.isoformat(), dte
    else:
        sd = date.fromisoformat(s["date"])
        day = date.fromisoformat(en["date"]) - timedelta(days=1) if en.get("date") else sd
        if day < sd:
            day = sd
        if day != sd:
            start = sd.isoformat()
        # 시간이 제목 끝에 붙어 있던 일정 (예: '18:00~')
        if prev.get("time") and not HHMM.match(prev["time"]) and label.endswith(prev["time"]):
            label, time_ = label[: -len(prev["time"])].strip(), prev["time"]
        elif prev.get("time") and not HHMM.match(prev["time"]) and exam.endswith(prev["time"]):
            exam, time_ = exam[: -len(prev["time"])].strip(), prev["time"]
    desc = (g.get("description") or "").split("───")[0].strip()
    desc = re.sub(r"<br\s*/?>", "\n", desc)
    desc = re.sub(r"<[^>]+>", "", desc)
    lines = [l.strip() for l in desc.splitlines() if l.strip()]
    url = next((l for l in lines if re.fullmatch(r"https?://\S+", l)), "")
    note = " ".join(l for l in lines if l != url)
    out = {"exam": exam, "category": prev.get("category") or "구글 캘린더", "label": label, "type": typ,
           "date": day.isoformat(), "start": start, "time": time_, "url": url, "note": note}
    if prev.get("remind") is not None:
        out["remind"] = prev["remind"]
    return out


def _ts(s: str) -> datetime:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 동기화 본체
def sync(sched: dict, auto: list[dict], gc, state: dict, today: date | None = None, log=print) -> dict:
    """sched(schedule.json)·state 를 그 자리에서 고친다. 반환: 건수 통계."""
    today = today or date.today()
    tmin, tmax = today - timedelta(days=400), today + timedelta(days=800)
    stats = dict(pushed=0, created=0, pulled=0, imported=0, del_google=0, del_site=0)
    by_id = {e["id"]: e for e in sched["events"]}
    hidden = set(sched.get("hidden_auto") or [])
    tomb = {e["id"] for e in sched["events"] if e.get("deleted")} | hidden
    site = {e["id"]: {**e, "origin": e.get("origin", "site")} for e in sched["events"] if not e.get("deleted")}
    for a in auto:
        if a["id"] not in by_id and a["id"] not in hidden:
            site[a["id"]] = {**a, "origin": "auto", "updated": ""}
    rev = {v["gid"]: k for k, v in state.items() if v.get("gid")}

    gl = gc.list(f"{tmin.isoformat()}T00:00:00Z", f"{tmax.isoformat()}T00:00:00Z")
    G, fresh = {}, []
    for g in gl:
        k = ((g.get("extendedProperties") or {}).get("private") or {}).get("nwid") or rev.get(g["id"])
        if k:
            if k not in G or G[k].get("status") == "cancelled":   # 같은 id 가 둘이면 살아 있는 쪽
                G[k] = g
        elif g.get("status") != "cancelled":
            fresh.append(g)

    def put_site(i: str, fields: dict, origin: str) -> dict:
        e = by_id.get(i)
        if e is None:
            e = {"id": i}
            sched["events"].append(e)
            by_id[i] = e
        for k in ce.EVENT_FIELDS:
            e[k] = fields.get(k, "")
        if "remind" in fields:
            e["remind"] = fields["remind"]
        e.update(origin=origin, updated=_now())
        e.pop("deleted", None)
        return e

    def del_site(i: str) -> None:
        s = site.get(i)
        if s and s["origin"] == "auto":
            if i not in hidden:
                sched.setdefault("hidden_auto", []).append(i)
                hidden.add(i)
        elif i in by_id:
            by_id[i].update(deleted=True, updated=_now())
        stats["del_site"] += 1

    for i in sorted(set(site) | set(G)):
        s, g, st = site.get(i), G.get(i), state.get(i)
        try:
            if g and g.get("status") == "cancelled":
                if s and st:   # 구글에서 지웠다 → 사이트에서도 지운다
                    log(f"  구글에서 삭제 → 사이트 삭제: {s['exam']}")
                    del_site(i)
                elif s and not st:   # 한 번도 맞춘 적 없는데 지워진 기록만 있다 → 새로 만든다
                    j = gc.insert(to_google(s))
                    state[i] = {"gid": j["id"], "g_upd": j.get("updated", ""), "h": site_hash(s), "auto": s["origin"] == "auto"}
                    stats["created"] += 1
                    continue
                state.pop(i, None)
                continue
            if s and not g:
                if st and date.fromisoformat(s["date"]) >= tmin and st.get("gid"):
                    log(f"  구글에 없음 → 사이트 삭제: {s['exam']}")
                    del_site(i)
                    state.pop(i, None)
                    continue
                j = gc.insert(to_google(s))
                state[i] = {"gid": j["id"], "g_upd": j.get("updated", ""), "h": site_hash(s), "auto": s["origin"] == "auto"}
                stats["created"] += 1
                log(f"  구글에 추가: {s['exam']} {s.get('label', '')} ({s['date']})")
                continue
            if g and not s:
                gone_auto = bool(st and st.get("auto")) and _gdate(g) >= today
                if i in tomb or gone_auto:
                    gc.delete(g["id"])
                    stats["del_google"] += 1
                    log(f"  사이트에서 삭제 → 구글 삭제: {g.get('summary')}")
                    state.pop(i, None)
                continue
            # 양쪽에 다 있다
            g_changed = not st or g.get("updated", "") != st.get("g_upd")
            s_changed = not st or site_hash(s) != st.get("h")
            if not st:   # 상태 기록이 없으면 (처음이거나 기록 유실) 내용이 같은지만 본다
                same = from_google(g, s)
                g_changed = s_changed = any(str(same.get(k) or "") != str(s.get(k) or "") for k in ce.EVENT_FIELDS)
                if g_changed:   # 다르면 나중에 고친 쪽
                    if _ts(s.get("updated", "")) >= _ts(g.get("updated", "")):
                        g_changed = False
                    else:
                        s_changed = False
            if g_changed and s_changed:
                if _ts(s.get("updated", "")) >= _ts(g.get("updated", "")):
                    g_changed = False
                else:
                    s_changed = False
            if g_changed and not s_changed:
                f = from_google(g, s)
                e = put_site(i, f, "auto-edited" if s["origin"] in ("auto", "auto-edited") else s["origin"])
                state[i] = {"gid": g["id"], "g_upd": g.get("updated", ""), "h": site_hash(e), "auto": False}
                stats["pulled"] += 1
                log(f"  구글 수정 → 사이트 반영: {e['exam']} ({e['date']})")
            elif s_changed:
                j = gc.patch(g["id"], to_google(s))
                state[i] = {"gid": g["id"], "g_upd": j.get("updated", ""), "h": site_hash(s), "auto": s["origin"] == "auto"}
                stats["pushed"] += 1
                log(f"  사이트 수정 → 구글 반영: {s['exam']} ({s['date']})")
            else:
                state[i] = {"gid": g["id"], "g_upd": g.get("updated", ""), "h": site_hash(s), "auto": s["origin"] == "auto"}
        except Exception as ex:   # 한 건이 실패해도 나머지는 계속
            log(f"  [동기화 오류] {i}: {type(ex).__name__}: {ex}")

    # 구글에서 새로 만든 일정 → 사이트로
    for g in fresh:
        try:
            i = "g" + hashlib.md5(g["id"].encode()).hexdigest()[:11]
            e = put_site(i, from_google(g, None), "google")
            try:
                j = gc.patch(g["id"], {"extendedProperties": {"private": {"nwid": i}}})
                gu = j.get("updated", g.get("updated", ""))
            except Exception as ex:   # 고칠 수 없는 일정(초대받은 일정 등)이면 구글 id 로만 잇는다
                log(f"  [표시 실패] {g.get('summary')}: {ex}")
                gu = g.get("updated", "")
            state[i] = {"gid": g["id"], "g_upd": gu, "h": site_hash(e), "auto": False}
            stats["imported"] += 1
            log(f"  구글에서 추가 → 사이트: {e['exam']} ({e['date']})")
        except Exception as ex:
            log(f"  [가져오기 오류] {g.get('summary')}: {type(ex).__name__}: {ex}")

    # 오래된 삭제 기록 정리
    cut = datetime.now(timezone.utc) - timedelta(days=TOMB_DAYS)
    sched["events"] = [e for e in sched["events"] if not (e.get("deleted") and _ts(e.get("updated", "")) < cut and e["id"] not in state)]
    return stats


def _gdate(g: dict) -> date:
    s = g.get("end") or g.get("start") or {}
    if s.get("date"):
        return date.fromisoformat(s["date"]) - timedelta(days=1)
    if s.get("dateTime"):
        return datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(TZ).date()
    return date.today()


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    import build_site
    store = crawler.Store(BASE / "data" / "notices.db")
    cfg = crawler.load_config()
    sched = ce.load_schedule()
    before = json.dumps(sched, ensure_ascii=False, sort_keys=True)
    gc = google_client()
    if gc is None:
        print("구글 캘린더 동기화 꺼짐 (GOOGLE_SERVICE_ACCOUNT·GOOGLE_CALENDAR_ID 비밀값 없음). 사이트 일정만 다시 만든다.")
    else:
        auto = [e for e in ce.all_events(store, cfg, sched=sched) if e.get("auto")]
        state = load_state()
        st = sync(sched, auto, gc, state)
        save_state(state)
        print("구글 캘린더 동기화: " + ", ".join(f"{k} {v}" for k, v in st.items()))
        if json.dumps(sched, ensure_ascii=False, sort_keys=True) != before:
            ce.save_schedule(sched)
            print("schedule.json 갱신")
    build_site.write_calendar(store, cfg)
    print("일정 화면·calendar.ics 갱신")
    return 0


if __name__ == "__main__":
    sys.exit(main())
