# local_sync.bat 를 이 PC·이 와이파이에서 돌려도 되는지 검사한다.
#   -Save : 지금 PC 정보를 보여 주고 '집' 을 입력하면 허용 정보(local_sync.allow)를 저장한다 (local_sync_register.ps1 이 부른다)
#   (없음) : 지금 PC 이름과 와이파이가 저장한 것과 같으면 0, 아니면 0이 아닌 값으로 끝난다 (local_sync.bat 이 부른다)
# 부트캠프 노트북·기관 와이파이에서 크롤링이 돌지 않게 하려는 장치다.
param([switch]$Save)

function Get-Ssid {
  $m = netsh wlan show interfaces 2>$null | Select-String '^\s*SSID\s*:\s*(.+?)\s*$' | Select-Object -First 1
  if ($m) { $m.Matches[0].Groups[1].Value } else { '' }
}

$allow = Join-Path $PSScriptRoot 'local_sync.allow'
$pc = $env:COMPUTERNAME
$ssid = Get-Ssid   # 저장할 때와 검사할 때 같은 방식으로 읽는다

if ($Save) {
  Write-Host ''
  Write-Host "컴퓨터 이름 : $pc"
  Write-Host "사용자      : $env:USERNAME"
  Write-Host ("와이파이    : " + $(if ($ssid) { $ssid } else { '(읽지 못함: 유선이거나 연결 없음)' }))
  Write-Host ''
  Write-Host '이 PC가 집의 개인 노트북이고, 지금 집 와이파이에 연결돼 있을 때만 등록한다.'
  Write-Host '부트캠프 노트북이거나 기관·학교·카페 와이파이라면 등록하지 말 것.'
  if (-not $ssid) { Write-Host '와이파이 이름을 읽지 못해 등록하지 않았다. 집 와이파이에 연결한 뒤 다시 실행할 것.'; exit 1 }
  $ans = Read-Host "위 정보가 맞으면 '집' 이라고 입력 (다른 입력은 취소)"
  if ("$ans".Trim() -ne '집') { Write-Host '취소했다. 등록하지 않았다.'; exit 1 }
  [IO.File]::WriteAllLines($allow, [string[]]@("computer=$pc", "ssid=$ssid"), (New-Object Text.UTF8Encoding $false))
  Write-Host '허용 정보를 저장했다: local_sync.allow (이 PC에만 있고 GitHub 에 올라가지 않는다)'
  exit 0
}

[Console]::OutputEncoding = [Text.Encoding]::UTF8   # local_sync.log 에 한글이 깨지지 않게 (와이파이 이름을 읽은 뒤에 바꾼다)
if (-not (Test-Path $allow)) {
  Write-Output '[건너뜀] 등록하지 않은 PC다 (local_sync.allow 없음). 집의 개인 노트북에서 local_sync_register.ps1 로 등록할 것'
  exit 2
}
$kv = @{}
Get-Content $allow -Encoding UTF8 | ForEach-Object { $k, $v = $_ -split '=', 2; if ($k) { $kv[$k.Trim()] = "$v".Trim() } }
if ($kv['computer'] -ne $pc) { Write-Output "[건너뜀] 등록한 PC($($kv['computer']))가 아니다: $pc"; exit 3 }
if ($kv['ssid'] -ne $ssid) {
  Write-Output ("[건너뜀] 등록한 와이파이($($kv['ssid']))가 아니다: " + $(if ($ssid) { $ssid } else { '연결 없음' }))
  exit 4
}
exit 0
