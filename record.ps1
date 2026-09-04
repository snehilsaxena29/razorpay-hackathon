# record.ps1 — capture cassettes from a live run, on Windows.
#
# The PowerShell equivalent of `make record`. Exists because Windows PowerShell
# 5.1 has no `&&`, `make` is usually absent, and `export` is not a thing — so a
# bash one-liner from the README fails three different ways before it gets to
# the interesting part.
#
# Usage:
#   $env:GROQ_API_KEY = "gsk_..."
#   .\record.ps1
#
# Needs a provider with enough quota for a full run: roughly 200 model calls
# across both agents and the whole catalogue.

$ErrorActionPreference = "Stop"

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $env:GROQ_API_KEY) {
    Write-Host "GROQ_API_KEY is not set in this shell." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  `$env:GROQ_API_KEY = `"gsk_...`""
    Write-Host ""
    Write-Host "Note this sets it for THIS PowerShell window only. Opening a new"
    Write-Host "tab loses it, which is the usual reason a run that worked a moment"
    Write-Host "ago reports no provider."
    exit 3
}

# Confirm the provider before spending a run on it. Model ids get retired, and
# finding that out on call one is much cheaper than finding it out on call 150.
Write-Host "Checking the provider..." -ForegroundColor Cyan
python scripts/smoke_groq.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Provider is not usable; not recording." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Recording a full live run. This takes a while and makes ~200 model calls." -ForegroundColor Cyan
$env:GAUNTLET_RECORD = "1"
$env:GAUNTLET_MODE = "live"
python -m gauntlet compare --agents naive,hardened
$runExit = $LASTEXITCODE
Remove-Item Env:\GAUNTLET_RECORD, Env:\GAUNTLET_MODE -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Verifying the cassette is complete..." -ForegroundColor Cyan

# A partial cassette is worse than none: it produces mostly misses, and a run
# where most attacks error still computes a score from the few that did not.
# Replaying without a key is the only honest check that it is whole.
$savedKey = $env:GROQ_API_KEY
Remove-Item Env:\GROQ_API_KEY
python -m gauntlet run --agent naive
$replayExit = $LASTEXITCODE
$env:GROQ_API_KEY = $savedKey

if ($replayExit -eq 2 -or $replayExit -eq 3) {
    Write-Host ""
    Write-Host "The replay did not fully resolve. Look for 'no recorded response'" -ForegroundColor Yellow
    Write-Host "in the report above: the cassette is incomplete and should be" -ForegroundColor Yellow
    Write-Host "re-recorded rather than shipped." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Cassette replays cleanly." -ForegroundColor Green
}

exit $runExit
