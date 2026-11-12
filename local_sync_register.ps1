# local_sync.bat 를 작업 스케줄러에 등록한다 (매일 08:30, 20:30). 집의 개인 노트북에서만 실행할 것.
# 실행:  local_sync.bat 와 같은 폴더에서 아래 한 줄을 PowerShell 에 붙여 넣는다
#   powershell -ExecutionPolicy Bypass -File .\local_sync_register.ps1
# 지우기: Unregister-ScheduledTask -TaskName notice-watch-local-titles -Confirm:$false
# 먼저 이 PC 정보를 보여 주고 '집' 확인을 받는다. 확인하지 않으면 등록하지 않는다
& (Join-Path $PSScriptRoot 'local_sync_guard.ps1') -Save
if ($LASTEXITCODE -ne 0) { exit 1 }
$bat = Join-Path $PSScriptRoot 'local_sync.bat'
if (-not (Test-Path $bat)) { Write-Error "local_sync.bat 를 찾지 못했다: $bat"; exit 1 }
$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At '08:30'),
  (New-ScheduledTaskTrigger -Daily -At '20:30')
)
# 노트북이 꺼져 있어 놓친 실행은 켜졌을 때 한 번 돈다. 배터리로 쓰는 중에도 돈다. 30분 넘게 걸리면 멈춘다
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'notice-watch-local-titles' -Action $action -Trigger $triggers -Settings $settings `
  -Description 'notice-watch: 막힌 사이트 제목을 이 PC에서 읽어 GitHub에 올린다' -Force | Out-Null
Write-Host "등록했다: notice-watch-local-titles (매일 08:30, 20:30). 기록은 local_sync.log 에 남는다."
