param([int]$Port = 7861, [string]$Config = (Join-Path $PSScriptRoot '.env.content.local'))
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython -X utf8 scripts/start_content_b.py --port $Port --config $Config
} else {
    python -X utf8 scripts/start_content_b.py --port $Port --config $Config
}
