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

## 알아둘 점
- **읽음·별표**는 기기마다 따로 저장된다 (휴대폰에서 읽어도 PC에선 새 글로 보인다).
- **미리보기·구조 자동 추정**은 웹에서는 안 된다 (브라우저 보안 규칙상 다른 사이트를 직접 못 읽는다). 웹에서 대상을 추가하면 다음 확인 결과의 '감시 대상별 상태'로 확인한다. 미리보기가 필요하면 PC 대시보드(app.py)를 쓴다.
- **해외 서버**: GitHub 서버는 미국에 있다. 해외 접속을 막는 학교 사이트가 있으면 상태표에 오류로 뜬다. 그런 곳은 PC 대시보드로 본다.
- **60일 규칙**: 공개 저장소에서 60일 동안 활동이 없으면 GitHub 가 예약 실행을 자동으로 끈다. 확인 결과가 바뀔 때마다 저장소에 기록이 남지만, 혹시 멈추면 Actions 탭에서 다시 켠다(Enable workflow).
- **되돌리기**: 웹에서 바꾼 설정은 저장소의 config.yaml **History** 에 모두 남는다.
- PC 대시보드(app.py)와 웹 버전은 데이터가 따로다 (PC: `notices.db`, 웹: `data/notices.db`). 같은 config.yaml 을 쓴다.
