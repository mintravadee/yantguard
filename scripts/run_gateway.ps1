# Yant Guard - start the gateway (Windows). Normally started by run_gateway.bat.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"

# Install packages only the first time, or when requirements.txt changes.
$marker = ".venv\.deps-installed"
$needInstall = (-not (Test-Path $marker)) -or ((Get-Item $marker).LastWriteTime -lt (Get-Item "requirements.txt").LastWriteTime)

if ($needInstall) {
    Write-Host "Installing requirements (first run takes a few minutes) ..."
    & $py -m pip install --upgrade pip
    # Min's pins come from another machine: skip uvloop/httptools (not for Windows) and relax click.
    $tmp = Join-Path $env:TEMP "yantguard-requirements-win.txt"
    Get-Content "requirements.txt" |
        Where-Object { $_ -notmatch '^(uvloop|httptools)==' } |
        ForEach-Object { $_ -replace '^click==.*$', 'click>=8.2.1' } |
        Set-Content $tmp -Encoding ascii
    & $py -m pip install -r $tmp
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Pinned install failed. Installing the core packages without pins instead ..."
        & $py -m pip install fastapi "uvicorn[standard]" python-dotenv google-genai groq httpx pydantic python-multipart pytest
        if ($LASTEXITCODE -ne 0) {
            Write-Host "pip failed again. Copy the last 15 lines above and send them to Claude."
            exit 1
        }
    }
    New-Item -ItemType File -Path $marker -Force | Out-Null
} else {
    Write-Host "Packages already installed."
}

# Create .env from the template when it is missing or empty, then stop so the keys can be filled in.
$envMissing = (-not (Test-Path ".env")) -or ((Get-Item ".env").Length -eq 0)
if ($envMissing) {
    Copy-Item ".env.example" ".env" -Force
    Write-Host "Created .env from .env.example. Open .env, paste your GEMINI_API_KEY and/or GROQ_API_KEY after the = sign, save, and start again."
    exit 1
}

# Warn about missing provider keys (names only, never values).
$envText = Get-Content ".env" -Raw
foreach ($name in @("GROQ_API_KEY", "GEMINI_API_KEY")) {
    if ($envText -notmatch "(?m)^$name=\S+") { Write-Host "WARNING: $name is missing in .env - that provider will answer 503." }
}

Write-Host ""
Write-Host "Starting server. Your browser will open http://127.0.0.1:8000/docs  (Ctrl+C here to stop)"
Start-Process cmd -ArgumentList '/c timeout /t 6 /nobreak >nul & start "" http://127.0.0.1:8000/docs' -WindowStyle Hidden
& $py -m uvicorn app.main:app --reload
