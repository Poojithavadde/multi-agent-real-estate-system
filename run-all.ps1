$ErrorActionPreference = "Stop"

Write-Host "Starting federated multi-agent real estate system..." -ForegroundColor Cyan

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCmd = "python"
$envFile = Join-Path $root ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Count -eq 2) {
            [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim())
        }
    }
    Write-Host "Loaded environment values from .env" -ForegroundColor DarkCyan
}

function Start-Agent {
    param(
        [string]$Name,
        [string]$WorkingDir,
        [string]$Command
    )

    $proc = Start-Process -FilePath "powershell" `
        -ArgumentList "-NoExit", "-Command", $Command `
        -WorkingDirectory $WorkingDir `
        -PassThru

    Write-Host "$Name started (PID: $($proc.Id)) in $WorkingDir" -ForegroundColor Green
}

Start-Agent `
    -Name "Customer Agent" `
    -WorkingDir (Join-Path $root "customer-onboarding-agent") `
    -Command "$pythonCmd -m uvicorn app:app --host 0.0.0.0 --port 8101 --reload"

Start-Agent `
    -Name "Marketing Agent" `
    -WorkingDir (Join-Path $root "marketing-intelligence-agent") `
    -Command "$pythonCmd -m uvicorn app:app --host 0.0.0.0 --port 8103 --reload"

Start-Agent `
    -Name "Deal Agent" `
    -WorkingDir (Join-Path $root "deal-onboarding-agent") `
    -Command "`$env:MARKETING_AGENT_URL='http://127.0.0.1:8103'; $pythonCmd -m uvicorn app:app --host 0.0.0.0 --port 8102 --reload"

Start-Agent `
    -Name "Concierge Agent" `
    -WorkingDir (Join-Path $root "concierge-agent") `
    -Command "`$env:LLM_PROVIDER='$env:LLM_PROVIDER'; `$env:GROQ_API_KEY='$env:GROQ_API_KEY'; `$env:GROQ_MODEL='$env:GROQ_MODEL'; `$env:HF_API_TOKEN='$env:HF_API_TOKEN'; `$env:HF_MODEL='$env:HF_MODEL'; `$env:CUSTOMER_AGENT_URL='http://127.0.0.1:8101'; `$env:DEAL_AGENT_URL='http://127.0.0.1:8102'; `$env:MARKETING_AGENT_URL='http://127.0.0.1:8103'; $pythonCmd -m uvicorn app:app --host 0.0.0.0 --port 8114 --reload"

Write-Host ""
Write-Host "All agents launched in separate PowerShell windows." -ForegroundColor Cyan
Write-Host "Concierge endpoint: http://127.0.0.1:8114/a2a/handle_request" -ForegroundColor Yellow
