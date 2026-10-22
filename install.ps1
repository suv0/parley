# Installs (or updates) Parley for the current Windows user. Run it again any time; it is safe.
#   1. finds Python 3.11 or newer
#   2. makes a private Python environment in %USERPROFILE%\.parley\venv
#   3. installs Parley there, downloads the speech models (about 640 MB, once),
#      adds the read-aloud hook to Claude Code, adds Start menu and startup shortcuts,
#      checks the microphone, and starts Parley.
# Not under AppData on purpose: the Microsoft Store's Python redirects writes there.
param([switch]$NoStart)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$data = Join-Path $env:USERPROFILE '.parley'
$venv = Join-Path $data 'venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

function Say($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Find-Python {
    $candidates = @(
        @{ exe = 'py'; args = @('-3.13') }, @{ exe = 'py'; args = @('-3.12') }, @{ exe = 'py'; args = @('-3.11') },
        @{ exe = 'py'; args = @('-3') }, @{ exe = 'python'; args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $version = & $c.exe @($c.args) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and "$version" -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
            return $c
        }
    }
    return $null
}

Say 'Python'
$python = Find-Python
if (-not $python) {
    Write-Host 'Parley needs Python 3.11 or newer, and none was found.'
    $answer = Read-Host 'Install Python 3.12 now with winget? (y/n)'
    if ($answer -notmatch '^[yY]') {
        Write-Host 'Install Python from https://www.python.org/downloads/ and run this again.'
        exit 1
    }
    winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $python = Find-Python
    if (-not $python) { Write-Host 'Python was installed. Open a new window and run this again.'; exit 1 }
}
& $python.exe @($python.args) --version

Say 'Python environment'
New-Item -ItemType Directory -Force $data | Out-Null
if (-not (Test-Path $venvPython)) {
    & $python.exe @($python.args) -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not make the Python environment.' }
}
& $venvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
& $venvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $here 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installing the Python packages failed. If you use a very new Python, try Python 3.12.' }
& $venvPython -m pip install --disable-pip-version-check --quiet --no-deps --force-reinstall $here
if ($LASTEXITCODE -ne 0) { throw 'Installing Parley failed.' }
Write-Host 'Packages installed.'

$setupArgs = @('-m', 'parley', 'setup')
if ($NoStart) { $setupArgs += '--no-start' }
& $venvPython @setupArgs
$code = $LASTEXITCODE
if ($code -eq 0) {
    Write-Host "`nDone. Click the Claude message box once, then say ""Hey Claude""." -ForegroundColor Green
} elseif ($code -eq 2) {
    Write-Host "`nInstalled, but Windows is blocking the microphone. Fix that, then start Parley from the Start menu." -ForegroundColor Yellow
} else {
    Write-Host "`nSomething went wrong. Run:  $venvPython -m parley doctor" -ForegroundColor Red
}
exit $code
