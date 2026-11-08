"""
아침 브리핑 (GitHub Actions 가 매일 아침 실행한다: .github/workflows/briefing.yml)

1. 날씨: Open-Meteo (키 없음) — briefing.yaml 의 지역. 기온·하늘·강수확률·미세먼지
2. 밤사이 뉴스: briefing.yaml 의 RSS (robots.txt 확인, 피드 사이 대기). 제목·출처·시각·원문 링크만 싣는다
3. 오늘 일정: 공지 사이트 '일정' 탭과 같은 자료 (schedule.json + 학사 공지 기간)
4. (선택) ANTHROPIC_API_KEY 가 있으면 헤드라인만 보고 '밤사이 핵심' 몇 줄
→ docs/data/briefing.json (사이트 '브리핑' 탭), docs/data/briefing/YYYY-MM-DD.json (최근 14일), 텔레그램 요약

내 PC에서 시험할 때:  python briefing.py --no-telegram
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import yaml

import calendar_events
import crawler
import notify
import planner
import summarize

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "briefing.yaml"
OUT = BASE / "docs" / "data" / "briefing.json"
ARCHIVE = BASE / "docs" / "data" / "briefing"
KEEP_DAYS = 14
KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"

# WMO 날씨 코드 → 한국어 (Open-Meteo)
WMO = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개",
       51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비", 56: "어는 이슬비", 57: "어는 이슬비",
       61: "약한 비", 63: "비", 65: "강한 비", 66: "어는 비", 67: "어는 비",
       71: "약한 눈", 73: "눈", 75: "강한 눈", 77: "싸락눈", 80: "소나기", 81: "소나기", 82: "강한 소나기",
       85: "눈 소나기", 86: "강한 눈 소나기", 95: "뇌우", 96: "우박 동반 뇌우", 99: "우박 동반 뇌우"}


def load_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def now_kst() -> datetime:
    return datetime.now(KST)


# ================================================================ 날씨
def _grade(v: float | None, cuts: tuple[int, int, int]) -> str:
    """환경부 예보 등급: 좋음·보통·나쁨·매우나쁨 (PM10 30/80/150, PM2.5 15/35/75)."""
    if v is None:
        return "정보 없음"
    return "좋음" if v <= cuts[0] else "보통" if v <= cuts[1] else "나쁨" if v <= cuts[2] else "매우나쁨"


def weather(cfg: dict) -> dict:
    w = cfg["weather"]
    base = {"latitude": w["lat"], "longitude": w["lon"], "timezone": "Asia/Seoul", "forecast_days": 1}
    f = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
        **base, "current": "temperature_2m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "hourly": "precipitation_probability,weather_code"}).json()
    a = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality", timeout=20, params={
        **base, "hourly": "pm10,pm2_5"}).json()
    d, h = f["daily"], f["hourly"]
    # 비·눈 올 가능성이 있는 시간대 (강수확률 50% 이상, 오늘 6시 이후)
    wet = [t[11:13] for t, p in zip(h["time"], h["precipitation_probability"]) if p is not None and p >= 50 and t[11:13] >= "06"]
    day_aq = [(t, p10, p25) for t, p10, p25 in zip(a["hourly"]["time"], a["hourly"]["pm10"], a["hourly"]["pm2_5"])
              if t[11:13] >= "06" and t[11:13] <= "21"]
    pm10 = max((x[1] for x in day_aq if x[1] is not None), default=None)
    pm25 = max((x[2] for x in day_aq if x[2] is not None), default=None)
    return {
        "place": w["name"],
        "now": round(f["current"]["temperature_2m"]),
        "sky": WMO.get(d["weather_code"][0], "알 수 없음"),
        "min": round(d["temperature_2m_min"][0]), "max": round(d["temperature_2m_max"][0]),
        "rain_prob": d["precipitation_probability_max"][0],
        "rain_hours": f"{wet[0]}~{int(wet[-1]) + 1:02d}시" if wet else "",
        "pm10": round(pm10) if pm10 is not None else None, "pm10_grade": _grade(pm10, (30, 80, 150)),
        "pm25": round(pm25) if pm25 is not None else None, "pm25_grade": _grade(pm25, (15, 35, 75)),
        "source": "Open-Meteo (모델 예보, 기상청 발표와 다를 수 있음)",
    }


# ================================================================ 뉴스
def _norm(title: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>", "", title)
    return re.sub(r"[\s\W_]+", "", t)[:40]


def read_feed(url: str, session: requests.Session) -> list[dict]:
    r = session.get(url, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate") or ""
        try:
            when = parsedate_to_datetime(pub).astimezone(KST)
        except (TypeError, ValueError):
            continue
        if title and link:
            out.append({"title": title, "url": link, "when": when})
    return out


def news(cfg: dict) -> list[dict]:
    session = crawler.new_session()
    delay = float(cfg.get("delay_seconds", 2))
    now = now_kst()
    hh, mm = (int(x) for x in str(cfg.get("news_since", "18:00")).split(":"))
    since = (now - timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    seen: set[str] = set()
    cache: dict[str, list[dict]] = {}
    result = []
    for cat in cfg["categories"]:
        picked, errors = [], []
        for feed in cat["feeds"]:
            url = feed["url"]
            if url not in cache:
                if not crawler.robots_allows(url, session):
                    errors.append(f"{feed['source']}: robots.txt 금지")
                    cache[url] = []
                    continue
                try:
                    cache[url] = read_feed(url, session)
                except Exception as e:   # 피드 하나가 실패해도 브리핑은 계속
                    errors.append(f"{feed['source']}: {type(e).__name__}")
                    cache[url] = []
                time.sleep(delay)
            inc, exc = feed.get("include") or [], feed.get("exclude") or []
            for it in cache[url]:
                if not (since <= it["when"] <= now):
                    continue
                low = it["title"].lower()
                if inc and not any(k.lower() in low for k in inc):
                    continue
                if any(k.lower() in low for k in exc):
                    continue
                picked.append({**it, "source": feed["source"]})
        picked.sort(key=lambda x: x["when"], reverse=True)
        items = []
        for it in picked:
            key = _norm(it["title"])
            if key in seen:   # 같은 기사는 앞 분야에서 한 번만
                continue
            seen.add(key)
            items.append({"title": it["title"], "url": it["url"], "source": it["source"],
                          "time": it["when"].strftime("%m.%d %H:%M")})
            if len(items) >= int(cfg.get("per_category", 6)):
                break
        result.append({"name": cat["name"], "items": items, "errors": errors})
    return result


# ================================================================ 일정
def schedule(cfg: dict, today: date) -> dict:
    notice_cfg = crawler.load_config()
    store = crawler.Store(BASE / "data" / "notices.db")
    events = calendar_events.all_events(store, notice_cfg, today=today)
    t = today.isoformat()
    until = (today + timedelta(days=int(cfg.get("upcoming_days", 7)))).isoformat()

    def brief(e: dict) -> dict:
        return {k: e.get(k, "") for k in ("date", "start", "time", "exam", "label", "type", "category", "url")}

    todays = [brief(e) for e in events if e["date"] == t or (e.get("start") and e["start"] <= t <= e["date"])]
    upcoming = [brief(e) for e in events if t < e["date"] <= until and not (e.get("start") and e["start"] <= t)]
    return {"today": todays, "upcoming": upcoming}


# ================================================================ 밤사이 핵심 (선택)
def ai_summary(cats: list[dict]) -> list[str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return []
    lines = []
    for c in cats:
        lines.append(f"## {c['name']}")
        lines += [f"- {it['title']} ({it['source']})" for it in c["items"]]
    prompt = ("아래는 밤사이 나온 뉴스 제목 목록이다. 제목에 있는 내용만 근거로, 사용자가 아침에 알아야 할 핵심을 "
              "한국어 평서문 3~5줄로 정리하라. 각 줄은 '- '로 시작하고 60자 이내. 제목에 없는 사실·수치·전망은 쓰지 마라.\n\n"
              + "\n".join(lines))
    r = requests.post(summarize.API_URL, timeout=60, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": summarize.DEFAULT_MODEL, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    return [ln[2:].strip() for ln in text.splitlines() if ln.startswith("- ")][:5]


# ================================================================ 텔레그램
def telegram_text(b: dict, site_url: str) -> str:
    w = b["weather"]
    parts = [f"[아침 브리핑] {b['date_label']}"]
    if w:
        rain = f", 강수확률 {w['rain_prob']}%" + (f" ({w['rain_hours']})" if w["rain_hours"] else "")
        parts.append(f"날씨 · {w['place']}\n{w['sky']}, 지금 {w['now']}° (최저 {w['min']}° / 최고 {w['max']}°){rain}\n"
                     f"미세먼지 {w['pm10_grade']} · 초미세먼지 {w['pm25_grade']}")
    sch = b["schedule"]
    if sch["today"]:
        parts.append("오늘 일정\n" + "\n".join(f"- {e['exam']} {e['label']} {e['type']}".replace("  ", " ")
                                             + (f" {e['time']}" if e["time"] else "") for e in sch["today"]))
    else:
        parts.append("오늘 일정: 없음")
    pl = b.get("planner")
    if pl:
        lines = [f"- {i['title']} ({i['course']}, {planner.fmt_min(i['cost'])})" for i in pl["items"]]
        lines += [f"! {', '.join(w['courses'])}: 마감 {w['deadline']}까지 {planner.fmt_min(w['short'])} 부족" for w in pl["warnings"]]
        parts.append(f"오늘 할 강의 ({planner.fmt_min(pl['total'])})\n" + ("\n".join(lines) or "오늘 배정된 강의 없음"))
    if sch["upcoming"]:
        parts.append("다가오는 일정\n" + "\n".join(f"- {e['date'][5:].replace('-', '.')} {e['exam']} {e['type']}"
                                                for e in sch["upcoming"][:5]))
    if b["ai_summary"]:
        parts.append("밤사이 핵심\n" + "\n".join(f"- {s}" for s in b["ai_summary"]))
    for c in b["news"]:
        if c["items"]:
            parts.append(f"{c['name']}\n" + "\n".join(f"- {it['title']} ({it['source']})" for it in c["items"][:3]))
    if site_url:
        parts.append("전체 보기: " + site_url.rstrip("/") + "/#briefing")
    return "\n\n".join(parts)


# ================================================================ 실행
def main() -> int:
    ap = argparse.ArgumentParser(description="아침 브리핑 만들기")
    ap.add_argument("--no-telegram", action="store_true", help="텔레그램을 보내지 않는다 (시험용)")
    args = ap.parse_args()
    cfg = load_cfg()
    now = now_kst()
    today = now.date()
    b = {"generated_at": now.strftime("%Y-%m-%d %H:%M"), "date": today.isoformat(),
         "date_label": f"{today.month}월 {today.day}일 ({WEEKDAYS[today.weekday()]})",
         "weather": None, "schedule": {"today": [], "upcoming": []}, "news": [], "ai_summary": [], "errors": []}
    for name, fn in (("weather", lambda: weather(cfg)), ("schedule", lambda: schedule(cfg, today)),
                     ("news", lambda: news(cfg)), ("planner", lambda: planner.for_briefing(today))):
        try:
            b[name] = fn()
        except Exception as e:   # 한 부분이 실패해도 나머지는 만든다
            b["errors"].append(f"{name}: {type(e).__name__}: {e}"[:200])
    if cfg.get("ai_summary", True) and b["news"]:
        try:
            b["ai_summary"] = ai_summary(b["news"])
        except Exception as e:
            b["errors"].append(f"ai_summary: {type(e).__name__}: {e}"[:200])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(b, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(text, encoding="utf-8")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    (ARCHIVE / f"{today.isoformat()}.json").write_text(text, encoding="utf-8")
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    for f in ARCHIVE.glob("*.json"):
        if f.stem != "index" and f.stem < cutoff:
            f.unlink()
    write_index()
    n_news = sum(len(c["items"]) for c in b["news"])
    print(f"브리핑 저장: 뉴스 {n_news}건, 오늘 일정 {len(b['schedule']['today'])}건, 오류 {len(b['errors'])}건")
    for e in b["errors"] + [f"{c['name']} · {x}" for c in b["news"] for x in c.get("errors", [])]:
        print(f"[오류] {e}")

    if not args.no_telegram and notify.enabled():
        try:
            notify.send(telegram_text(b, crawler.load_config().get("site_url", "")))
            print("텔레그램 보냄")
        except Exception as e:
            print(f"[텔레그램 오류] {type(e).__name__}: {e}")
    elif not args.no_telegram:
        print("텔레그램 꺼짐 (토큰 없음)")
    return 0



def write_index() -> None:
    """사이트 '브리핑' 탭의 이전 날짜 목록 (최신순)."""
    dates = sorted((f.stem for f in ARCHIVE.glob("*.json") if f.stem != "index"), reverse=True)
    (ARCHIVE / "index.json").write_text(json.dumps({"dates": dates}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
