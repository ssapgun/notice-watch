# 웹 버전 설정 (GitHub, 무료)

PC를 켜 두지 않아도 GitHub 서버가 6시간마다 확인하고, `https://내아이디.github.io/notice-watch/` 주소로 휴대폰·PC 어디서나 본다.
처음 한 번만 아래 순서대로 하면 된다 (20분 정도).

## 1. 저장소 만들기
1. github.com 가입 → 오른쪽 위 **+ → New repository**
2. 이름: `notice-watch`, **Public** 선택 → Create repository
   - 무료 요금제에서 GitHub Pages(웹사이트)는 공개 저장소에서만 된다.
   - 공개라서 주소를 아는 사람은 목록과 config.yaml(지망 학교 목록)을 볼 수 있다. 검색엔진 노출은 막아 뒀다(noindex).
   - 비공개로 하려면 GitHub Pro 이상이 필요하다.

## 2. 파일 올리기
**방법 A (권장): Cursor / GitHub Desktop**
압축 푼 `notice_dashboard` 폴더를 Cursor 로 열고, Claude Code 에게 이렇게 시킨다.
> 이 폴더를 git 저장소로 만들고 https://github.com/내아이디/notice-watch 에 main 브랜치로 올려줘.

**방법 B: 웹에서 직접**
저장소 화면 → **uploading an existing file** → 폴더 안의 파일을 전부 끌어다 놓기 → Commit.
- `.github` 처럼 점으로 시작하는 폴더는 탐색기에서 숨겨져 안 올라가는 경우가 있다.
  올린 뒤 저장소에 `.github/workflows/crawl.yml` 이 없으면: **Add file → Create new file** → 이름 칸에 `.github/workflows/crawl.yml` 입력 → 파일 내용을 붙여넣고 Commit.

## 3. 쓰기 권한 켜기
저장소 **Settings → Actions → General → Workflow permissions → Read and write permissions** → Save.
(확인 결과를 저장소에 저장하기 위해 필요하다)

## 4. 웹사이트 켜기
저장소 **Settings → Pages → Build and deployment**
- Source: **Deploy from a branch**
- Branch: **main**, 폴더 **/docs** → Save

## 5. 첫 확인 실행
저장소 **Actions** 탭 → (처음이면 활성화 버튼) → 왼쪽 **공지·입시 확인** → **Run workflow**.
2~5분 뒤 초록 체크가 뜨면, 1~2분 더 기다렸다가 `https://내아이디.github.io/notice-watch/` 를 연다.

## 6. (선택) 웹에서 '지금 확인'과 대상 수정 쓰기
보기만 할 거면 여기서 끝이다. 웹에서 버튼으로 확인을 돌리거나 감시 대상을 고치려면 토큰이 필요하다.

1. GitHub 오른쪽 위 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Expiration: 90일 등 기한을 정한다.
3. Repository access: **Only select repositories → notice-watch**
4. Permissions → Repository permissions:
   - **Contents: Read and write**
   - **Actions: Read and write**
5. Generate → 나온 토큰(`github_pat_...`)을 복사
6. 웹사이트의 **연결 설정** 탭에 붙여넣고 **저장하고 연결 확인** → "연결됨"이 뜨면 끝.

토큰은 그 기기의 브라우저에만 저장된다. 기기마다 한 번씩 넣는다. 공용 PC에서는 넣지 말 것. 잃어버리면 GitHub 에서 그 토큰을 삭제하고 새로 만든다.

## 7. (선택) 공지 정리·번역 켜기
키가 없어도 각 공지의 본문 앞부분을 발췌해서 보여준다. 다만 번역은 안 되고, 포스터(이미지)만 있는 글은 정리하지 못한다.
Claude 가 핵심을 항목별로 정리하고 일본어·영어·독일어 글을 한국어로 번역하게 하려면 API 키를 넣는다.

1. https://platform.claude.com (Claude Console) 가입 → 결제 메뉴에서 크레딧 충전 (최소 금액이면 충분하다)
2. API 키 메뉴에서 새 키 만들기 → 나온 키(`sk-ant-...`) 복사
3. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `ANTHROPIC_API_KEY`
   - Secret: 복사한 키 → **Add secret**
4. 다음 확인부터 적용된다. 그동안 발췌만 해 둔 글도 차례로 다시 정리된다 (한 번에 최대 80개).

- 쓰는 모델: `claude-haiku-5-5` (config.yaml 의 `summary.model` 에서 바꾼다)
- 비용: 입력 100만 토큰당 $0.10, 출력 100만 토큰당 $0.50. 공지 하나에 대략 입력 3,000 + 출력 400 토큰이라 1건당 약 $0.0005, 100건이면 약 $0.05 다.
- 비밀값(Secret)은 공개 저장소에서도 다른 사람에게 보이지 않는다. 키를 코드나 config.yaml 에 직접 적지 말 것.
- 정리를 끄려면 config.yaml 의 `summary.enabled` 를 `false` 로.

## 8. (선택) 텔레그램 알림 켜기
새 글 중 핵심 키워드(config.yaml 의 `highlight.alert`: 학부연구생, T/O, 모집요강, 연구실탐방, 장학생 모집, 모듈러, 강구조 등)가 든 글과,
3회 연속 실패한 감시 대상을 휴대폰으로 받는다. 토큰을 넣지 않으면 아무것도 보내지 않는다.

1. 텔레그램에서 **@BotFather** 와 대화 → `/newbot` → 봇 이름과 아이디(끝이 bot)를 정하면 토큰(`123456:ABC...`)을 준다. 비밀번호처럼 다룬다.
2. 방금 만든 봇과 대화를 열어 아무 말이나 한 번 보낸다.
3. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` 를 연다 → `"chat":{"id": 숫자` 의 숫자가 채팅 ID 다.
4. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret** 로 두 개를 넣는다.
   - `TELEGRAM_BOT_TOKEN`: 1번의 토큰
   - `TELEGRAM_CHAT_ID`: 3번의 숫자
5. 다음 확인부터 보낸다. 같은 글은 한 번만 온다(처음 들어온 확인에서만).

- 알림 키워드는 config.yaml 의 `highlight.alert`, 화면에서 눈에 띄게 표시할 키워드는 `highlight.keywords`, 오탐을 막는 제외어는 `highlight.exclude`.
- PC 대시보드(app.py)에서 받으려면 같은 이름의 환경변수를 넣고 실행한다.

## 9. 일정 고치기
- 사이트의 **일정** 탭에서 **새 일정 추가**, 각 일정 오른쪽 **수정**(그 안에 삭제)으로 고친다. 6번의 GitHub 연결이 되어 있어야 저장된다.
- 저장하면 저장소의 `schedule.json` 이 바뀌고, '구글 캘린더 동기화' 작업이 바로 한 번 돌아 1~2분 뒤 사이트와 구글 캘린더(10번)에 반영된다.
- 날짜가 아직 없는 시험·공모전 카드는 config.yaml 의 `exams` 에 둔다.
- 텔레그램이 켜져 있으면 접수 마감 3일 전·당일, 시험 7일 전·1일 전에 한 번씩 알린다.
- 읽기 전용 구독 주소(`calendar.ics`)도 그대로 만든다. 10번 양방향 동기화를 켰다면 구독은 넣지 않는다(같은 일정이 두 번 보인다).

## 10. (선택) 구글 캘린더와 양방향 동기화 켜기
사이트에서 고치면 구글 캘린더에, 구글 캘린더에서 고치면 사이트에 1시간 안에 반영된다. 비밀번호를 넘기지 않고, 이 캘린더 하나에만 권한을 주는 **서비스 계정** 방식이다.

**A. 서비스 계정 만들기 (Google Cloud, 무료)**
1. https://console.cloud.google.com 에 구글 계정으로 들어가 위쪽 프로젝트 선택 → **새 프로젝트** (이름 예: notice-watch).
2. **API 및 서비스 → 라이브러리** → `Google Calendar API` 검색 → **사용**.
3. **IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기**. 이름만 넣고(예: notice-sync) 역할은 주지 않고 **완료**.
4. 만든 서비스 계정을 눌러 **키 → 키 추가 → 새 키 만들기 → JSON**. JSON 파일이 내려받아진다. 이 파일은 비밀번호와 같으니 어디에도 올리지 않는다.
5. 서비스 계정의 이메일 주소(`notice-sync@프로젝트.iam.gserviceaccount.com`)를 복사해 둔다.

**B. 전용 캘린더 만들고 공유하기 (구글 캘린더, PC)**
1. 구글 캘린더 왼쪽 '다른 캘린더' 옆 **+ → 새 캘린더 만들기** → 이름 `공지·입시 일정` → 만들기.
2. 그 캘린더의 **설정 및 공유 → 특정 사용자 또는 그룹과 공유 → 사용자 추가** → A-5 의 서비스 계정 이메일, 권한 **일정 변경**.
3. 같은 설정 화면 아래 **캘린더 통합 → 캘린더 ID** (`...@group.calendar.google.com`)를 복사한다.
4. 9번의 `calendar.ics` 를 구독해 두었다면 그 구독은 지운다.

**C. GitHub 비밀값 넣기**
저장소 **Settings → Secrets and variables → Actions → New repository secret** 에 두 개를 넣는다.
- `GOOGLE_SERVICE_ACCOUNT`: A-4 JSON 파일을 메모장으로 열어 내용 전체를 붙여넣는다.
- `GOOGLE_CALENDAR_ID`: B-3 캘린더 ID.

**D. 첫 동기화**
**Actions → 구글 캘린더 동기화 → Run workflow**. 로그에 `구글 캘린더 동기화: ... created N` 이 나오면 끝이다. 이후 1시간마다(매시 17분 무렵) 돈다.

알아둘 점
- 동기화 대상은 이 전용 캘린더 하나뿐이다. 내 기본 캘린더의 일정은 읽지 않는다.
- 같은 일정을 양쪽에서 1시간 안에 다르게 고치면 **나중에 고친 쪽**이 남는다.
- 구글 캘린더에서 새로 만든 일정은 사이트에 분류 '구글 캘린더'로 들어온다. 제목 앞에 `[시험]`, `[접수 마감]` 처럼 종류를 붙이면 그 종류로 들어온다.
- 사이트가 만든 일정의 설명란 맨 아래 `─── 공지·입시 감시 …` 줄은 지우지 않는다. 그 위의 메모·링크를 고치면 사이트에도 반영된다.
- 학사 공지에서 자동으로 뽑은 일정을 구글에서 고치면 직접 관리하는 일정으로 바뀌고, 지우면 다시 나타나지 않는다.
- 키를 새로 만들었거나 유출이 의심되면 A-4 화면에서 옛 키를 삭제하고 C 를 다시 한다.

## 알아둘 점
- **읽음·별표**는 기기마다 따로 저장된다 (휴대폰에서 읽어도 PC에선 새 글로 보인다).
- **미리보기·구조 자동 추정**은 웹에서는 안 된다 (브라우저 보안 규칙상 다른 사이트를 직접 못 읽는다). 웹에서 대상을 추가하면 다음 확인 결과의 '감시 대상별 상태'로 확인한다. 미리보기가 필요하면 PC 대시보드(app.py)를 쓴다.
- **해외 서버**: GitHub 서버는 미국에 있다. 해외 접속을 막는 학교 사이트가 있으면 상태표에 오류로 뜬다. 그런 곳은 PC 대시보드로 본다.
- **60일 규칙**: 공개 저장소에서 60일 동안 활동이 없으면 GitHub 가 예약 실행을 자동으로 끈다. 확인 결과가 바뀔 때마다 저장소에 기록이 남지만, 혹시 멈추면 Actions 탭에서 다시 켠다(Enable workflow).
- **되돌리기**: 웹에서 바꾼 설정은 저장소의 config.yaml **History** 에 모두 남는다.
- PC 대시보드(app.py)와 웹 버전은 데이터가 따로다 (PC: `notices.db`, 웹: `data/notices.db`). 같은 config.yaml 을 쓴다.
