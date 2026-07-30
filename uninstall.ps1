# 클로드 펫 제거 — 바로가기 삭제 · 훅 해제 (파일은 그대로 남는다)
$ErrorActionPreference = 'SilentlyContinue'

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*pet.pyw*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host '[1/3] 실행 중인 펫 종료'

foreach ($p in @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) '클로드 펫.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'ClaudePet.lnk')
)) {
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "      삭제: $p" }
}
Write-Host '[2/3] 바로가기 삭제'

$settings = Join-Path $env:USERPROFILE '.claude\settings.json'
if (Test-Path $settings) {
    Copy-Item $settings "$settings.bak" -Force
    $json = Get-Content $settings -Raw | ConvertFrom-Json
    if ($json.hooks) {
        foreach ($evt in @('Notification', 'Stop')) {
            if (-not $json.hooks.$evt) { continue }
            $kept = @()
            foreach ($group in @($json.hooks.$evt)) {
                $hooks = @($group.hooks | Where-Object { $_.command -notlike '*pet_hook.py*' })
                if ($hooks.Count -gt 0) {
                    $group.hooks = $hooks
                    $kept += $group
                }
            }
            $json.hooks.$evt = $kept
        }
        $json | ConvertTo-Json -Depth 20 | Set-Content $settings -Encoding utf8
        Write-Host "      훅 해제 (백업: $settings.bak)"
    }
}
Write-Host '[3/3] 완료. 폴더를 지우면 완전히 제거됩니다.'
