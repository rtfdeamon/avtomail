[CmdletBinding()]
param(
    [switch]$InstallOnly,
    [switch]$RunOnly,
    [switch]$NoReload,
    [int]$Port = 8000,
    [string]$BindAddress = '127.0.0.1'
)

if ($InstallOnly -and $RunOnly) {
    throw "Use either -InstallOnly or -RunOnly, not both."
}

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $scriptRoot 'backend'
$venvPath = Join-Path $scriptRoot '.venv'
$venvScripts = Join-Path $venvPath 'Scripts'
$envFile = Join-Path $scriptRoot '.env'
$logDir = Join-Path $scriptRoot 'logs'

function Get-PythonCommand {
    $candidates = @('python', 'py')
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($cmd.Name -eq 'py') {
                return @($cmd.Path, '-3')
            }
            return ,$cmd.Path
        }
    }
    throw "Python 3.11+ is required but was not found in PATH. Install it from https://www.python.org/downloads/."
}

$PythonCmd = Get-PythonCommand

function Invoke-Python {
    param([string[]]$Arguments)
    $cmdParts = @($PythonCmd)
    $baseArgs = @()
    if ($cmdParts.Count -gt 1) {
        $baseArgs = $cmdParts[1..($cmdParts.Count - 1)]
    }
    & $cmdParts[0] @baseArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Invoke-VenvPython {
    param([string[]]$Arguments)
    $pythonExe = Join-Path $venvScripts 'python.exe'
    if (-not (Test-Path $pythonExe)) {
        throw "Virtual environment Python executable not found at $pythonExe"
    }
    & $pythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Virtualenv python command failed: $($Arguments -join ' ')"
    }
}

function Ensure-PythonVersion {
    $versionOutput = Invoke-Python @('--version')
    if (-not ($versionOutput -match 'Python\s+(\d+)\.(\d+)\.(\d+)')) {
        throw "Unable to parse Python version from '$versionOutput'"
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
        throw "Python 3.11 or newer is required. Current version: $versionOutput"
    }
    Write-Host "Detected $versionOutput"
}

function Ensure-Venv {
    if (-not (Test-Path $venvPath)) {
        Write-Host "Creating virtual environment in .venv"
        Invoke-Python @('-m', 'venv', $venvPath)
    } else {
        Write-Host "Virtual environment already exists"
    }
}

function Install-Dependencies {
    Write-Host "Installing project dependencies"
    Invoke-VenvPython @('-m', 'pip', 'install', '--upgrade', 'pip', 'wheel', 'setuptools')
    Invoke-VenvPython @('-m', 'pip', 'install', '-e', '.[dev]')
}

function Ensure-EnvFile {
    $exampleFile = Join-Path $scriptRoot '.env.example'
    if (-not (Test-Path $envFile) -and (Test-Path $exampleFile)) {
        Write-Host "Creating .env from .env.example"
        Copy-Item $exampleFile $envFile
    }
}

function Load-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) {
            continue
        }
        $separatorIndex = $trimmed.IndexOf('=')
        if ($separatorIndex -lt 0) {
            continue
        }
        $key = $trimmed.Substring(0, $separatorIndex).Trim()
        $value = $trimmed.Substring($separatorIndex + 1).Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Trim('"')
        } elseif ($value.StartsWith("'") -and $value.EndsWith("'")) {
            $value = $value.Trim("'")
        }
        [Environment]::SetEnvironmentVariable($key, $value, 'Process')
    }
}

function Ensure-LogDirectory {
    if (-not (Test-Path $logDir)) {
        Write-Host "Creating log directory at $logDir"
        New-Item -ItemType Directory -Path $logDir | Out-Null
    }
}

function Run-Migrations {
    Write-Host "Running database migrations"
    Push-Location $backendDir
    $previousPythonPath = $env:PYTHONPATH
    try {
        if ($previousPythonPath) {
            $env:PYTHONPATH = "$backendDir;$previousPythonPath"
        } else {
            $env:PYTHONPATH = $backendDir
        }
        Invoke-VenvPython @('-m', 'alembic', '-c', 'alembic.ini', 'upgrade', 'head')
    } finally {
        $env:PYTHONPATH = $previousPythonPath
        Pop-Location
    }
}

function Start-Uvicorn {
    Write-Host "Starting FastAPI server on ${BindAddress}:${Port}"
    $uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', ${BindAddress}, '--port', $Port.ToString())
    if (-not $NoReload) {
        $uvicornArgs += '--reload'
    }
    Push-Location $backendDir
    $previousPythonPath = $env:PYTHONPATH
    try {
        if ($previousPythonPath) {
            $env:PYTHONPATH = "$backendDir;$previousPythonPath"
        } else {
            $env:PYTHONPATH = $backendDir
        }
        Invoke-VenvPython $uvicornArgs
    } finally {
        $env:PYTHONPATH = $previousPythonPath
        Pop-Location
    }
}

Ensure-PythonVersion

if (-not $RunOnly) {
    Ensure-Venv
    Ensure-EnvFile
    Load-DotEnv $envFile
    Install-Dependencies
    Ensure-LogDirectory
    Run-Migrations
}

if (-not $InstallOnly) {
    Load-DotEnv $envFile
    Start-Uvicorn
} else {
    Write-Host "Dependencies installed. Use the script without -InstallOnly to start the server." -ForegroundColor Green
}
