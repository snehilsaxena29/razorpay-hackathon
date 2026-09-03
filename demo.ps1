# demo.ps1 — the Windows equivalent of `make demo`.
#
# `make` is usually absent on Windows and the demo is recorded there, so this is
# a first-class path rather than a courtesy. It is a thin wrapper: the CLI is the
# real interface, and this file must never grow logic of its own.

$ErrorActionPreference = "Stop"

# The console defaults to a legacy code page that cannot encode the rupee sign.
# The CLI reconfigures its own streams, but setting this here means anything
# else in the pipeline (tee, redirection to a file) survives too.
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

python -m gauntlet demo @args

# Exit codes are part of the contract: 0 clean, 1 at least one attack succeeded,
# 2 degraded, 3 could not start. `gauntlet demo` returns 1 on a normal run
# because the naive agent is supposed to fail — that is the demonstration, not
# an error, so this script passes the code through unchanged rather than
# swallowing it.
exit $LASTEXITCODE
