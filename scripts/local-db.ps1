# Run a Python module against Docker PostgreSQL, without changing .env/Neon.
# Example: .\scripts\local-db.ps1 -m uvicorn app.main:app --reload
$ErrorActionPreference = 'Stop'
$pythonArgs = $args
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements first (see README).'
}
if (!$pythonArgs.Count) { throw 'Pass Python arguments, for example: -m alembic upgrade head' }
$overrides = @{
    DATABASE_URL = 'postgresql+psycopg://yefhamak:local-dev-only@127.0.0.1:5433/yefhamak'
    DIRECT_URL = 'postgresql+psycopg://yefhamak:local-dev-only@127.0.0.1:5433/yefhamak'
    OPENROUTER_API_KEY = 'disabled-local-development'
    LIVE_CHAT_ENABLED = 'false'
}
$previous = @{}
Push-Location $repoRoot
try {
    foreach ($name in $overrides.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $overrides[$name], 'Process')
    }
    & $pythonPath @pythonArgs
    $commandExit = $LASTEXITCODE
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    Pop-Location
}
exit $commandExit
