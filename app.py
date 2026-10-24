"""
공지·입시 대시보드 (로컬 웹서버)

실행:  python app.py
       → 브라우저가 http://127.0.0.1:8765 를 연다.
       → 켜 둔 동안 config.yaml 의 auto_check_hours 마다 자동으로 확인한다.

이 서버는 내 PC(127.0.0.1)에서만 열린다. 같은 와이파이의 다른 기기에서도 접속할 수 없다.
"""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import crawler
import notify
import summarize

HOST, PORT = "127.0.0.1", 8765
STATIC = Path(__file__).resolve().parent / "static"

store = crawler.Store()
state = {"running": False, "current": "", "done": 0, "total": 0, "group": "",
         "started": None, "finished": None, "new": 0, "error": ""}
state_lock = threading.Lock()
stop_event = threading.Event()


def start_crawl(group: str = "") -> bool:
    with state_lock:
        if state["running"]:
            return False
        state.update(running=True, current="", done=0, total=0, group=group,
                     started=crawler.now_str(), new=0, error="")

    def progress(p: dict) -> None:
        with state_lock:
            state.update(p)

    def work() -> None:
        try:
            cfg = crawler.load_config()
            started = crawler.now_str()
            n = crawler.run_crawl(store, cfg, group or None, progress, stop_event)
            with state_lock:
                state["new"] = n
            # 새 글 정리·번역 (환경변수 ANTHROPIC_API_KEY 가 있으면 Claude, 없으면 본문 발췌)
            summarize.summarize_pending(store, cfg, progress=lambda m: progress({"current": m}))
            try:   # 텔레그램 알림 (환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 가 있을 때만)
                notify.alert_after_run(store, cfg, started)
            except Exception:
                pass
        except Exception as e:  # 설정 파일 오류 등
            with state_lock:
                state["error"] = f"{type(e).__name__}: {e}"
        finally:
            with state_lock:
                state.update(running=False, current="", finished=crawler.now_str())

    threading.Thread(target=work, daemon=True).start()
    return True


def auto_loop() -> None:
    """켜 둔 동안 정해진 간격마다 자동 확인."""
    while not stop_event.is_set():
        try:
            hours = float(crawler.load_config().get("auto_check_hours", 6))
        except Exception:
            hours = 6
        if hours > 0:
            last = store.get_meta("last_run")
            due = (not last) or datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S") >= timedelta(hours=hours)
            if due:
                start_crawl()
        stop_event.wait(60)


def hidden_param(q: dict) -> set[str]:
    """화면에서 끈 주제 (?hide=채용·취업|심리상담·건강)"""
    return {x for x in q.get("hide", "").split("|") if x}


def sub_of(cfg: dict) -> dict:
    """대상 이름 → 소분류(학교·학회·게시판). sub 가 없으면 대상 이름을 그대로 쓴다."""
    return {s["name"]: s.get("sub") or s["name"] for s in cfg["sources"]}


def visible_counts(cfg: dict, hidden: set[str] | None = None) -> tuple[dict, dict]:
    """분류별, 소분류별 전체/안읽음 개수. 현재 필터나 끈 주제에 걸린 글은 세지 않는다."""
    ok = crawler.visible_filter(cfg, hidden)
    subs = sub_of(cfg)
    out: dict = {}
    by_sub: dict = {}
    with store.lock:
        rows = store.db.execute("SELECT grp, source, title, title_ko, kind, is_read FROM items").fetchall()
    for r in rows:
        if ok(dict(r)):
            unread = 0 if r["is_read"] else 1
            c = out.setdefault(r["grp"], {"total": 0, "unread": 0})
            c["total"] += 1
            c["unread"] += unread
            sc = by_sub.setdefault(r["grp"], {}).setdefault(subs.get(r["source"], r["source"]), {"total": 0, "unread": 0})
            sc["total"] += 1
            sc["unread"] += unread
    return out, by_sub


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 콘솔을 조용히
        pass

    # ---- 응답 도우미
    def send_json(self, data, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, ctype: str, download_name: str | None = None) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- 라우팅
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            return self.send_file(STATIC / "index.html", "text/html; charset=utf-8")
        if u.path == "/api/items":
            cfg = crawler.load_config()
            ok = crawler.visible_filter(cfg, hidden_param(q))
            sub, subs = q.get("sub", ""), sub_of(cfg)
            rows = store.items(group=q.get("group", ""), q=q.get("q", ""), unread=q.get("unread") == "1",
                               starred=q.get("starred") == "1", limit=3000)
            rows = [it for it in rows if ok(it) and (not sub or subs.get(it["source"], it["source"]) == sub)]
            return self.send_json([dict(it, summary=json.loads(it["summary"]) if it.get("summary") else [])
                                   for it in rows[:3000]])
        if u.path == "/api/summary":
            cfg = crawler.load_config()
            groups = []
            for s in cfg["sources"]:
                g = s.get("group", "")
                if s.get("enabled", True) is not False and g not in groups:
                    groups.append(g)
            with state_lock:
                st = dict(state)
            counts, sub_counts = visible_counts(cfg, hidden_param(q))
            return self.send_json({
                "groups": groups, "links": cfg.get("links", []), "topics": cfg.get("topics", []), "highlight": cfg.get("highlight", {}),
                "counts": counts, "sub_counts": sub_counts, "sources": store.sources(),
                "configured": [{"name": s["name"], "group": s.get("group", ""), "sub": s.get("sub") or s["name"],
                                "kind": s.get("type", "board"),
                                "url": s.get("url") or crawler.page_url(s, 1)}
                               for s in cfg["sources"] if s.get("enabled", True) is not False],
                "last_run": store.get_meta("last_run"), "auto_hours": cfg.get("auto_check_hours", 6),
                "state": st})
        if u.path == "/api/sources":
            cfg = crawler.load_config()
            return self.send_json({"sources": cfg["sources"], "excluded": cfg.get("excluded", []),
                                   "status": store.sources()})
        if u.path == "/api/export":
            path = crawler.export_xlsx(store)
            return self.send_file(path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  "notices.xlsx")
        self.send_json({"error": "not found"}, 404)

    def allowed(self) -> bool:
        """다른 웹사이트가 내 브라우저를 통해 몰래 설정을 바꾸지 못하게 막는다.
        대시보드 화면이 보내는 요청에만 붙는 머리글과, 출처(Origin)가 이 서버인지 확인한다."""
        if self.headers.get("X-Dashboard") != "1":
            return False
        origin = self.headers.get("Origin")
        return origin in (None, f"http://{HOST}:{PORT}", f"http://localhost:{PORT}")

    def do_POST(self):
        u = urlparse(self.path)
        if not self.allowed():
            return self.send_json({"error": "허용되지 않은 요청"}, 403)
        try:
            b = self.body()
        except ValueError:
            return self.send_json({"error": "요청 형식 오류"}, 400)
        if u.path.startswith("/api/sources/"):
            return self.sources_api(u.path.rsplit("/", 1)[1], b)
        if u.path == "/api/check":
            return self.send_json({"started": start_crawl(b.get("group", ""))})
        if u.path == "/api/mark":
            field = {"read": "is_read", "star": "starred"}[b["field"]]
            store.mark([int(i) for i in b["ids"]], field, int(b["value"]))
            return self.send_json({"ok": True})
        if u.path == "/api/read_all":
            if b.get("sub"):   # 소분류만 읽음 처리
                subs = sub_of(crawler.load_config())
                names = [n for n, sb in subs.items() if sb == b["sub"]]
                if not names:
                    return self.send_json({"ok": True})
                with store.lock:
                    store.db.execute(f"UPDATE items SET is_read=1 WHERE grp=? AND source IN ({','.join('?' * len(names))})",
                                     [b.get("group", ""), *names])
                    store.db.commit()
                return self.send_json({"ok": True})
            store.mark_all_read(b.get("group", ""))
            return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)

    # ---- 감시 대상 관리
    def sources_api(self, action: str, b: dict):
        try:
            if action == "save":
                with state_lock:
                    if state["running"]:
                        raise ValueError("확인이 끝난 뒤에 저장할 것 (지금 확인 중)")
                old = b.get("old_name") or None
                src = crawler.upsert_source(b["source"], old)
                if old and old != src["name"]:
                    store.rename_source(old, src["name"], src["group"])
                return self.send_json({"ok": True, "source": src})
            if action == "delete":
                crawler.delete_source(b["name"])
                store.forget_source(b["name"], bool(b.get("purge")))
                return self.send_json({"ok": True})
            if action == "toggle":
                crawler.set_enabled(b["name"], bool(b["enabled"]))
                return self.send_json({"ok": True})
            if action == "move":
                crawler.move_source(b["name"], int(b["delta"]))
                return self.send_json({"ok": True})
            if action == "test":
                return self.send_json(crawler.test_source(b["source"]))
            if action == "guess":
                return self.send_json(crawler.guess_board(str(b.get("url", "")).strip()))
            if action == "excluded":
                cfg = crawler.load_config()
                cfg["excluded"] = [str(x).strip() for x in b.get("items", []) if str(x).strip()]
                crawler.save_config(cfg)
                return self.send_json({"ok": True})
        except ValueError as e:
            return self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return self.send_json({"error": "not found"}, 404)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=auto_loop, daemon=True).start()
    url = f"http://{HOST}:{PORT}"
    print(f"대시보드: {url}   (끄려면 Ctrl+C)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_event.set()
        print("\n종료")


if __name__ == "__main__":
    main()
