"""
정부 혜택(보조금24) 수집 — 행정안전부_대한민국 공공서비스(혜택) 정보 공개 API (공공데이터포털 15113968).

웹페이지를 긁지 않고 정부가 공개한 API 를 부른다 (원칙 4 의 '비공개·내부 API' 가 아님).
- 주소: https://api.odcloud.kr/api/gov24/v3/serviceList · supportConditions (명세: infuser.odcloud.kr api-docs)
- 인증키: 환경변수 DATA_GO_KR_KEY (GitHub Secret). 코드·config.yaml 에 쓰지 않는다 (원칙 7).
- 요청 사이 delay_seconds(기본 2초) 대기, User-Agent 는 crawler.USER_AGENT, robots.txt 확인 (원칙 1~3).

config.yaml 의 대상 예:
  - name: 정부 혜택 (보조금24)
    group: 지원 정책
    type: gov24
    url: https://www.gov.kr/portal/rcvfvrSvc/main
    birth_year: 2000          # 비우면 나이로 거르지 않는다
    regions: [서울특별시, 서울특별시 동대문구]   # 비우면 지자체 혜택은 모두 뺀다 (전국 혜택만)
    include: [청년, 대학생, ...]   # 서비스명·목적·지원대상·분야에 하나라도 있으면
    exclude: [노인, 영유아, ...]   # 서비스명·지원대상에 있으면 뺀다
"""
from __future__ import annotations

import os
import re
import time
from datetime import date

import requests

import crawler

API = "https://api.odcloud.kr/api/gov24/v3"
PER_PAGE = 1000
MAX_PAGES = 30           # 3만 건 상한 (지금 약 1만 건)
# 지자체·교육청으로 보이는 소관기관 이름 (중앙부처는 '부·처·청·위원회', 공공기관은 '공단·재단' 등으로 끝난다)
_LOCAL_RE = re.compile(r"(특별시|광역시|특별자치시|특별자치도|[가-힣]도|[가-힣]시|[가-힣]군|[가-힣]구|교육청)$")
_LOCAL_HEAD = re.compile(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충북|충남|전라|전북|전남|경상|경북|경남|제주)")


def api_key() -> str:
    return os.environ.get("DATA_GO_KR_KEY", "").strip()


def _get_all(path: str, session: requests.Session, delay: float, key: str) -> list[dict]:
    url = f"{API}/{path}"
    if not crawler.robots_allows(url, session):
        raise PermissionError(f"robots.txt 가 수집을 막고 있다: {url}")
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        r = session.get(url, params={"page": page, "perPage": PER_PAGE, "returnType": "JSON", "serviceKey": key},
                        timeout=60)
        if r.status_code in (401, 403):
            raise PermissionError(f"인증키가 거절됐다 ({r.status_code}): {r.text[:120]}")
        r.raise_for_status()
        d = r.json()
        rows = d.get("data") or []
        out += rows
        time.sleep(delay)
        total = int(d.get("matchCount") or d.get("totalCount") or 0)
        if not rows or len(out) >= total:
            break
    return out


_FULL_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def deadline_of(text: str) -> str:
    """신청기한 칸('2026.12.31까지', '2026. 3. 2 ~ 2026. 12. 31', '상시신청')의 마지막 날짜. 없으면 ''."""
    got = crawler.parse_deadline(text, dday=False)
    if got:
        return got
    hits = _FULL_DATE.findall(text or "")
    if not hits:
        return ""
    y, m, d = (int(x) for x in hits[-1])
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return ""


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def is_local(org: str) -> bool:
    org = (org or "").strip()
    return bool(_LOCAL_RE.search(org) or _LOCAL_HEAD.match(org))


def region_ok(org: str, regions: list[str]) -> bool:
    """중앙부처·공공기관 혜택은 통과. 지자체·교육청 혜택은 regions 의 지역일 때만."""
    org = (org or "").strip()
    if not is_local(org):
        return True
    for r in regions:
        r = r.strip()
        if not r:
            continue
        last = r.split()[-1]
        # '서울특별시', '서울특별시교육청', '서울특별시 동대문구', '동대문구'
        if org in (r, last) or org == r + "교육청" or org.replace(" ", "") == r.replace(" ", ""):
            return True
    return False


def age_ok(cond: dict | None, age: int | None) -> bool:
    if age is None or not cond:
        return True
    lo, hi = _int(cond.get("JA0110")), _int(cond.get("JA0111"))
    if lo is not None and age < lo:
        return False
    if hi is not None and hi > 0 and age > hi:
        return False
    return True


def crawl_gov24(src: dict, session: requests.Session, delay: float) -> list[dict]:
    key = api_key()
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 비밀값이 없다. 저장소 Settings → Secrets → Actions 에 넣을 것")
    services = _get_all("serviceList", session, delay, key)
    conds: dict[str, dict] = {}
    by = src.get("birth_year")
    age = (date.today().year - int(by) - 1) if by else None   # 만 나이 (생일 전 기준, 보수적으로)
    if age is not None:
        conds = {c.get("서비스ID"): c for c in _get_all("supportConditions", session, delay, key)}

    inc = [str(k).lower() for k in src.get("include") or []]
    exc = [str(k).lower() for k in src.get("exclude") or []]
    regions = [str(r) for r in src.get("regions") or []]
    found = []
    for s in services:
        sid, name = s.get("서비스ID"), crawler.clean(s.get("서비스명") or "")
        if not sid or not name:
            continue
        if "개인" not in (s.get("사용자구분") or "개인") and "가구" not in (s.get("사용자구분") or ""):
            continue
        if not region_ok(s.get("소관기관명", ""), regions):
            continue
        if not age_ok(conds.get(sid), age):
            continue
        whole = " ".join(str(s.get(k) or "") for k in ("서비스명", "서비스목적요약", "지원대상", "서비스분야")).lower()
        if inc and not any(crawler.kw_in(k, whole) for k in inc):
            continue
        head = (name + " " + str(s.get("지원대상") or "")).lower()
        if any(crawler.kw_in(k, head) for k in exc):
            continue
        deadline_txt = crawler.clean(s.get("신청기한") or "")
        changed = (s.get("수정일시") or s.get("등록일시") or "")[:8]
        d = crawler.norm_date(changed) or (f"{changed[:4]}-{changed[4:6]}-{changed[6:8]}" if re.fullmatch(r"\d{8}", changed) else "")
        org = crawler.clean(s.get("소관기관명") or "")
        body = "\n".join(x for x in (
            f"소관: {org}" if org else "",
            f"지원 대상: {crawler.clean(s.get('지원대상') or '')}",
            f"지원 내용: {crawler.clean(s.get('지원내용') or '')}",
            f"신청 기한: {deadline_txt}" if deadline_txt else "",
            f"신청 방법: {crawler.clean(s.get('신청방법') or '')}",
        ) if x and not x.endswith(": "))
        url = s.get("상세조회URL") or f"https://www.gov.kr/portal/rcvfvrSvc/dtlEx/{sid}"
        found.append({
            "title": f"[{org}] {name}" if org else name,
            "url": url, "date": d,
            "deadline": deadline_of(deadline_txt),
            "key": f"gov24|{sid}", "tkey": None, "change": body[:1500], "kind": "gov24",
        })
    return found
