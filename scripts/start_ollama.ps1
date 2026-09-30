param([switch]$Cpu, [switch]$Restart)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$ollamaExe = Join-Path $projectRoot '.runtime\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollamaExe)) { throw 'Ollama runtime is missing.' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot '.runtime\models'
$env:OLLAMA_IGPU_ENABLE = $(if ($Cpu) { '0' } else { '1' })
$env:OLLAMA_VULKAN = $(if ($Cpu) { '0' } else { '1' })
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_CONTEXT_LENGTH = '131072'
$env:OLLAMA_FLASH_ATTENTION = '0'
$env:OLLAMA_KV_CACHE_TYPE = 'f16'
if ($Restart) {
    $listeners = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
    foreach ($serverId in ($listeners.OwningProcess | Select-Object -Unique)) {
        if (-not $serverId) { continue }
        $serverProcess = Get-Process -Id $serverId -ErrorAction Stop
        if ($serverProcess.Path -ne $ollamaExe) { throw 'Port 11434 belongs to a different installation; refusing to stop it.' }
        Stop-Process -Id $serverId
        $serverProcess.WaitForExit(10000) | Out-Null
    }
}
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null; Write-Output 'Ollama is already running. Use -Restart to apply changed server settings.'; exit 0 } catch {}
Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime\ollama-out.log') -RedirectStandardError (Join-Path $projectRoot '.runtime\ollama-err.log')
Write-Output 'Ollama local server started at 127.0.0.1:11434.'
