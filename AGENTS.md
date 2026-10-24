# 공지·입시 감시 대시보드 — 에이전트 작업 안내

이 프로젝트를 수정하는 AI 에이전트(Cursor 등)가 먼저 읽는 문서다.

## 무엇을 하는 프로그램인가
학교 공지와 국내외 대학원 입시 페이지를 주기적으로 확인해 새 글과 페이지 변경을 한 화면에 모아 보여주는 **로컬 웹 대시보드**.
사용자 관심 분야: 구조공학 중 **기초·지반**, **모듈러(OSC) 공기 단축**. 감시 대상은 이 분야 연구실이 실제로 있는 학과만 둔다.

## 구조
| 파일 | 역할 |
|---|---|
| `crawler.py` | 크롤링 엔진. 저장소(`Store`, SQLite), 게시판 파싱(`parse_list`), 페이지 변경 감지(`crawl_watch`), 설정 편집(`upsert_source` 등), 미리보기(`test_source`), 구조 추정(`guess_board`) |
| `summarize.py` | 공지 정리·번역. 상세 페이지 본문(`detail_selector`)을 뽑아 Claude API(`ANTHROPIC_API_KEY`)로 한국어 정리, 키가 없으면 발췌. 첨부파일은 읽지 않는다 |
| `notify.py` | 텔레그램 알림. TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID 가 있을 때만 핵심 키워드 새 글과 3회 연속 실패 대상을 보낸다 |
| `app.py` | 파이썬 표준 라이브러리 웹서버(`ThreadingHTTPServer`). `127.0.0.1:8765`. API 와 자동 확인 스레드 |
| `static/index.html` | 화면 전체 (HTML+CSS+JS 한 파일, 빌드 도구 없음) |
| `config.yaml` | 감시 대상 목록. 화면에서 저장하면 `crawler.save_config` 가 다시 쓴다 |
| `notices.db`, `page_snapshots/` | PC 대시보드가 실행 중 만드는 데이터. 커밋 대상 아님 |
| `build_site.py`, `.github/workflows/crawl.yml` | 웹 버전: GitHub Actions 가 6시간마다 실행, 결과를 `data/`(커밋됨)와 `docs/data/data.json` 에 저장 |
| `docs/index.html` | 웹 버전 화면 (GitHub Pages). 읽음·별표는 브라우저 저장, 설정 수정은 GitHub API 로 config.yaml 커밋. `static/index.html` 과 CSS 를 맞춰 둔다 |

## 실행 / 확인
```
pip install -r requirements.txt
python app.py              # 대시보드
python crawler.py          # 화면 없이 한 번 확인
python crawler.py --export # 엑셀로 내보내기
```

## 반드시 지킬 원칙 (변경 금지)
1. 매 요청 전 robots.txt 확인(`robots_allows`). 금지된 사이트는 추가하지도, 우회하지도 않는다.
2. 요청 사이 대기(`delay_seconds`, 기본 2초)를 줄이지 않는다.
3. User-Agent 에 크롤러임을 밝힌다(`USER_AGENT`). 브라우저로 위장하지 않는다.
4. 로그인, 캡차 우회, 비공개·내부 API 호출, IP 우회를 하지 않는다. 공개 목록 페이지만 읽는다.
5. 서버는 `127.0.0.1` 에만 연다. POST 는 `X-Dashboard: 1` 머리글과 Origin 검사(`Handler.allowed`)를 통과해야 한다. 이 검사를 지우지 않는다.
6. 개인 용도. 수집한 내용을 재배포하는 기능을 넣지 않는다. 웹 버전에는 원문 전문이 아니라 짧은 정리와 원문 링크만 올린다.
7. API 키는 환경변수·GitHub Secret 으로만 받는다. 코드·config.yaml·data.json 에 쓰지 않는다.

## 코드 규칙
- 의존성은 `requirements.txt` 의 4개만 쓴다. 새 패키지가 꼭 필요하면 이유를 적고 사용자에게 먼저 묻는다.
- 화면 문구와 오류 메시지는 한국어, 평서문("~했다", "~할 것").
- 한 사이트가 실패해도 전체 확인은 계속돼야 한다 (`run_crawl` 의 try/except 유지).
- 설정 저장은 반드시 `save_config` 를 거친다 (.bak 백업과 원자적 쓰기 때문).
- 새 감시 대상을 넣을 때는 공식 교수·연구실 목록에서 기초·지반 또는 모듈러 연구실을 확인하고, `note` 에 근거를 적는다.

## 수정 후 확인 순서
1. `python -c "import crawler, app"` 로 문법 확인.
2. `python app.py` 실행 → 감시 대상 관리 → 바꾼 대상 **미리보기**.
3. 공지 보기 → **지금 확인** → 하단 '감시 대상별 상태'에 오류가 없는지 본다.
