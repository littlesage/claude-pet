# 클로드 펫 설치 — 바로가기 · 아이콘 · Claude Code 훅 등록
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# 되돌리려면 uninstall.ps1 을 실행한다.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pet = Join-Path $root 'pet.pyw'

function Find-Pythonw {
    foreach ($name in @('pythonw.exe', 'pyw.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

$pythonw = Find-Pythonw
if (-not $pythonw) {
    Write-Host '[!] Python을 찾지 못했습니다. https://www.python.org 에서 설치한 뒤 다시 실행하세요.'
    exit 1
}
Write-Host "[1/4] Python: $pythonw"

# 의존 패키지
$py = $pythonw -replace 'pythonw\.exe$', 'python.exe' -replace 'pyw\.exe$', 'py.exe'
if (-not (Test-Path $py)) { $py = 'python' }
& $py -m pip install --quiet --disable-pip-version-check Pillow numpy
Write-Host '[2/4] Pillow, numpy 확인 완료'

# 아이콘
$icon = Join-Path $root 'ClaudePet.ico'
try {
    & $py (Join-Path $root 'make_icon.py') | Out-Null
} catch {
    Write-Host '    (아이콘 생성 건너뜀 - assets 이미지가 없을 수 있습니다)'
}
Write-Host '[3/4] 아이콘 준비'

# 바로가기: 바탕화면 + 시작 프로그램
$ws = New-Object -ComObject WScript.Shell
foreach ($spot in @(
    @{ Dir = [Environment]::GetFolderPath('Desktop'); Name = '클로드 펫.lnk' },
    @{ Dir = [Environment]::GetFolderPath('Startup'); Name = 'ClaudePet.lnk' }
)) {
    $lnk = $ws.CreateShortcut((Join-Path $spot.Dir $spot.Name))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$pet`""
    $lnk.WorkingDirectory = $root
    $lnk.Description = '클로드 펫 - Claude Code 세션 알림 펫'
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    Write-Host "      $($spot.Name) -> $($spot.Dir)"
}
Write-Host '[4/4] 바로가기 생성 (바탕화면 + 시작 프로그램)'

# Claude Code 훅 등록
$settings = Join-Path $env:USERPROFILE '.claude\settings.json'
if (-not (Test-Path $settings)) {
    Write-Host ''
    Write-Host '[i] ~/.claude/settings.json 이 없어 훅 등록을 건너뜁니다.'
    Write-Host '    Claude Code를 한 번 실행한 뒤 이 스크립트를 다시 돌리세요.'
    exit 0
}

Copy-Item $settings "$settings.bak" -Force
$json = Get-Content $settings -Raw | ConvertFrom-Json
$hookPath = (Join-Path $root 'pet_hook.py') -replace '\\', '/'

foreach ($evt in @('Notification', 'Stop')) {
    if (-not $json.hooks) {
        $json | Add-Member -NotePropertyName hooks -NotePropertyValue ([PSCustomObject]@{}) -Force
    }
    $cmd = "python `"$hookPath`" $($evt.ToLower())"
    $existing = $json.hooks.$evt
    $already = $false
    if ($existing) {
        foreach ($group in $existing) {
            foreach ($h in $group.hooks) { if ($h.command -like '*pet_hook.py*') { $already = $true } }
        }
    }
    if ($already) {
        Write-Host "      $evt 훅은 이미 등록되어 있습니다"
        continue
    }
    $entry = [PSCustomObject]@{ hooks = @([PSCustomObject]@{
        type = 'command'; command = $cmd; timeout = 10
        statusMessage = '클로드 펫 알림'; async = $true }) }
    if ($existing) {
        $json.hooks.$evt = @($existing) + $entry
    } else {
        $json.hooks | Add-Member -NotePropertyName $evt -NotePropertyValue @($entry) -Force
    }
    Write-Host "      $evt 훅 등록"
}
$json | ConvertTo-Json -Depth 20 | Set-Content $settings -Encoding utf8
Write-Host ''
Write-Host "완료. 백업: $settings.bak"
Write-Host '훅은 새로 시작하는 Claude Code 세션부터 적용됩니다.'
Write-Host '바탕화면의 「클로드 펫」을 실행해 보세요.'
