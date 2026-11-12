@echo off
chcp 65001 >nul
setlocal
rem 막힌 사이트(web_skip)의 제목을 이 PC에서 읽어 GitHub에 올린다. 작업 스케줄러가 하루 두 번 실행한다.
rem 집에서 쓰는 개인 노트북에서만 등록할 것 (부트캠프 노트북·기관 와이파이에서는 그 기관의 IP로 접속하게 된다).
cd /d "%~dp0"
set "LOG=%~dp0local_sync.log"
set PYTHONUTF8=1
echo ===== %date% %time% >> "%LOG%"

rem 등록한 PC·와이파이가 아니면(부트캠프 노트북, 기관 와이파이 등) 아무것도 하지 않는다
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local_sync_guard.ps1" >> "%LOG%" 2>&1
if errorlevel 1 exit /b 0

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BR=%%b"
if not "%BR%"=="main" (
  echo [건너뜀] 지금 브랜치가 main 이 아니다: %BR% >> "%LOG%"
  exit /b 1
)
git diff --quiet -- config.yaml
if errorlevel 1 (
  echo [건너뜀] config.yaml 에 커밋하지 않은 수정이 있다. 정리한 뒤 다시 실행할 것 >> "%LOG%"
  exit /b 1
)

git pull --rebase --autostash origin main >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [실패] git pull >> "%LOG%"
  exit /b 1
)

python local_titles.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [실패] local_titles.py >> "%LOG%"
  exit /b 1
)

git diff --quiet -- config.yaml
if not errorlevel 1 (
  echo 바뀐 제목 없음 >> "%LOG%"
  exit /b 0
)

git add config.yaml
git commit -m "내 PC에서 막힌 사이트 제목 갱신" >> "%LOG%" 2>&1
git push origin main >> "%LOG%" 2>&1
if errorlevel 1 (
  rem 그사이 웹에서 고친 것이 있으면 한 번 더 맞춰서 올린다
  git pull --rebase origin main >> "%LOG%" 2>&1
  git push origin main >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [실패] git push >> "%LOG%"
    exit /b 1
  )
)
echo [완료] 올렸다 >> "%LOG%"
endlocal
