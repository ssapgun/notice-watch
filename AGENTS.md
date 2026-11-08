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
| `calendar_events.py` | 일정: schedule.json + 학사 공지 기간 추출 → data.json calendar, docs/calendar.ics, 텔레그램 미리 알림(meta 로 중복 방지). 날짜 없는 카드는 config exams |
| `briefing.py`, `briefing.yaml`, `.github/workflows/briefing.yml` | 아침 브리핑(매일 06:40): Open-Meteo 날씨·미세먼지(키 없음), briefing.yaml 의 RSS 밤사이 뉴스(제목·출처·링크만, robots.txt 확인·피드 사이 대기), 오늘·다가오는 일정(calendar_events), ANTHROPIC_API_KEY 있으면 헤드라인 기반 '밤사이 핵심'. → docs/data/briefing.json(사이트 '브리핑' 탭, #briefing), docs/data/briefing/날짜.json(14일), 텔레그램 요약. 설정은 config.yaml 과 분리 |
| `gcal_sync.py`, `.github/workflows/gcal.yml` | 구글 캘린더 전용 캘린더와 schedule.json 양방향 동기화(1시간마다·schedule.json 푸시 때). 서비스 계정(GOOGLE_SERVICE_ACCOUNT·GOOGLE_CALENDAR_ID). 상태는 data/gcal_state.json |
| `schedule.json` | 날짜가 정해진 일정 저장소. 웹 '일정' 탭이 GitHub API 로, 동기화 작업이 구글 쪽 변경으로 고친다. deleted:true 는 삭제 기록, hidden_auto 는 숨긴 자동 일정 |
| `app.py` | 파이썬 표준 라이브러리 웹서버(`ThreadingHTTPServer`). `127.0.0.1:8765`. API 와 자동 확인 스레드 |
| `static/index.html` | 화면 전체 (HTML+CSS+JS 한 파일, 빌드 도구 없음) |
| `config.yaml` | 감시 대상 목록. 화면에서 저장하면 `crawler.save_config` 가 다시 쓴다 |
| `notices.db`, `page_snapshots/` | PC 대시보드가 실행 중 만드는 데이터. 커밋 대상 아님 |
| `build_site.py`, `.github/workflows/crawl.yml` | 웹 버전: GitHub Actions 가 6시간마다 실행, 결과를 `data/`(커밋됨)와 `docs/data/data.json` 에 저장 |
| `docs/index.html` | 웹 버전 화면 (GitHub Pages). 읽음·별표는 브라우저 저장, 설정 수정은 GitHub API 로 config.yaml 커밋. `static/index.html` 과 CSS 를 맞춰 둔다 |
| `planner.py`, `docs/planner.js`, `docs/planner.json` | 자동 플래너('플래너' 탭). 강의 목차는 사용자가 붙여넣는다(로그인 수집 금지). 하루 배정·이월·소화율·마감 경고를 코드로 계산하고 AI 는 쓰지 않는다. 같은 계산이 planner.js(화면)와 planner.py(아침 브리핑)에 있어 함께 고친다. 진도는 planner.json 에 저장되며 공개 저장소라 공개된다 |
| `docs/readiness.json` | '지원 준비도' 탭. 합격 확률을 만들지 않는다. conditions 는 공고에서 확인한 조건만(출처 필수, 모르면 manual). 후기는 자동 수집하지 않고(링커리어 약관 제39조) 사용자가 읽고 넣은 익명 숫자와 링크만 samples 에 둔다. 표본 3명 미만이면 통계를 내지 않는다. 내 스펙·지원 결과는 브라우저에만 저장한다 |
| `local_titles.py` | config.yaml 의 `web_skip`(GitHub 서버에서 접속이 막히는 대상)을 내 PC에서 읽어 `manual_items` 에 제목을 넣는다. build_site.py 는 web_skip 대상을 건너뛰고 manual_items 를 공지 목록에 보여 준다 |
| `docs/words.json` | 공지 보기·브리핑 탭 '오늘의 단어'(웹 버전만): AI·코딩, 건설, 일본어 단어(JLPT N5~N4), 일본어 문장. 날짜마다 묶음별로 돌아가며 보여 준다. 손으로 고친다 |

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
- 의존성은 `requirements.txt` 의 5개만 쓴다 (google-auth 는 구글 캘린더 동기화용, 사용자 승인). 새 패키지가 꼭 필요하면 이유를 적고 사용자에게 먼저 묻는다.
- 화면 문구와 오류 메시지는 한국어, 평서문("~했다", "~할 것").
- 한 사이트가 실패해도 전체 확인은 계속돼야 한다 (`run_crawl` 의 try/except 유지).
- 설정 저장은 반드시 `save_config` 를 거친다 (.bak 백업과 원자적 쓰기 때문).
- 새 감시 대상을 넣을 때는 공식 교수·연구실 목록에서 기초·지반 또는 모듈러 연구실을 확인하고, `note` 에 근거를 적는다.
- 진로용 분류(공모전·대외활동·건설 교육·AI·코딩 교육·외부장학·봉사활동·자격증)는 사용자 진로(시공사 → CM/PM·구조설계·시행사 또는 대학원)에 맞는 것만 include/exclude 로 거른다. 모음 사이트(콘테스트코리아·위비티·드림스폰)는 첫 페이지만 읽는다. 링커리어는 약관 제39조 때문에 자동 확인하지 않는다(바로가기만). 새 사이트를 넣을 때는 robots.txt 와 함께 이용약관의 자동 수집 조항도 확인한다. 기자단·서포터즈는 건설·건축·토목·국토·주거·재해/건설안전 관련만.
- 공지 보기 왼쪽 분류는 config `group_folders` 묶음으로 열고 닫는다. 대상의 분류(group)를 바꾸면 build_site.py 가 예전 글도 새 분류로 보여 준다. 대상 이름을 바꾸면 `renamed_sources`(예전 이름: 새 이름)에 적는다. 소분류는 `sub_rules`(글 제목 키워드, 위 규칙부터 적용)가 있으면 내용별, `flat_groups` 는 소분류 없음, 나머지는 게시판별이다.

## 수정 후 확인 순서
1. `python -c "import crawler, app"` 로 문법 확인.
2. `python app.py` 실행 → 감시 대상 관리 → 바꾼 대상 **미리보기**.
3. 공지 보기 → **지금 확인** → 하단 '감시 대상별 상태'에 오류가 없는지 본다.
