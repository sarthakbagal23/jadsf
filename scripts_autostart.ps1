param([string]$action)

$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder "EDITH_AutoStart.lnk"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($action -eq "enable") {
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($shortcutPath)
    $s.TargetPath = "wscript.exe"
    $s.Arguments = "`"$dir\start_background.vbs`""
    $s.WorkingDirectory = $dir
    $s.Save()
    Write-Host "SUCCESS: EDITH will now automatically boot with Windows!" -ForegroundColor Green
} elseif ($action -eq "disable") {
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath -Force -ErrorAction SilentlyContinue
        Write-Host "SUCCESS: EDITH auto-start removed." -ForegroundColor Yellow
    } else {
        Write-Host "EDITH was not in startup folder."
    }
}
