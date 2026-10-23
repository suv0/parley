# Runs inside Windows Sandbox: a clean Windows with no Python and no winget.
# Installs Python the way a first-time user would, then installs Utter from GitHub's ZIP.
# Everything it prints goes to results\install.log, which you can read from the host.
$ErrorActionPreference = 'Continue'
$out = 'C:\utter-test\results'
New-Item -ItemType Directory -Force $out | Out-Null
Start-Transcript -Path "$out\install.log" -Force
$ProgressPreference = 'SilentlyContinue'

Write-Host '== Is there a Python or winget? (a bare PC has neither)'
Get-Command py, python, winget -ErrorAction SilentlyContinue | Format-Table Name, Source

Write-Host '== Installing Python 3.12 from python.org'
$py = "$env:TEMP\python.exe"
Invoke-WebRequest https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe -OutFile $py
Start-Process $py -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1' -Wait
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

Write-Host '== Downloading Utter (Code -> Download ZIP)'
Invoke-WebRequest https://github.com/suv0/utter/archive/refs/heads/main.zip -OutFile "$env:TEMP\utter.zip"
Expand-Archive "$env:TEMP\utter.zip" "$env:USERPROFILE\Downloads" -Force

Write-Host '== Running install.ps1 (what install.cmd runs)'
$start = Get-Date
& powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\utter-main\install.ps1"
Write-Host "install.ps1 exited with $LASTEXITCODE after $([int]((Get-Date) - $start).TotalSeconds) s"

Write-Host '== utter doctor'
& "$env:USERPROFILE\.utter\venv\Scripts\python.exe" -m utter doctor
Write-Host '== Is Utter running?'
Get-Process pythonw* -ErrorAction SilentlyContinue | Format-Table Name, Id
Get-Content "$env:USERPROFILE\.utter\utter.log" -Tail 15 -ErrorAction SilentlyContinue
Stop-Transcript
New-Item -ItemType File "$out\done.txt" -Force | Out-Null
