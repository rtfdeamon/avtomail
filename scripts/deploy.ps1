[CmdletBinding()]

param(

    [switch]$SkipInstall,

    [switch]$SkipMigrations,

    [switch]$SkipTests,

    [switch]$StartServer,

    [switch]$StartWorker,

    [int]$Port = 8000,

    [string]$BindAddress = '0.0.0.0'

)



$ErrorActionPreference = 'Stop'



$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$projectRoot = Split-Path -Parent $scriptRoot

$backendDir = Join-Path $projectRoot 'backend'

$venvPath = Join-Path $projectRoot '.venv'

$venvScripts = Join-Path $venvPath 'Scripts'

$envPath = Join-Path $projectRoot '.env'

$storageDir = Join-Path $projectRoot 'storage'

$attachmentsDir = Join-Path $storageDir 'attachments'



function Get-PythonCommand {

    $candidates = @()



    if ($env:VIRTUAL_ENV) {

        $candidates += [pscustomobject]@{ Command = Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe'; Args = @() }

        $candidates += [pscustomobject]@{ Command = Join-Path $env:VIRTUAL_ENV 'bin/python'; Args = @() }

        $candidates += [pscustomobject]@{ Command = Join-Path $env:VIRTUAL_ENV 'bin/python3'; Args = @() }

    }



    $candidates += [pscustomobject]@{ Command = Join-Path $venvScripts 'python.exe'; Args = @() }

    $candidates += [pscustomobject]@{ Command = Join-Path $venvPath 'bin/python'; Args = @() }

    $candidates += [pscustomobject]@{ Command = Join-Path $venvPath 'bin/python3'; Args = @() }



    $candidates += [pscustomobject]@{ Command = 'python'; Args = @() }

    $candidates += [pscustomobject]@{ Command = 'py'; Args = @('-3') }



    foreach ($candidate in $candidates) {

        if (-not $candidate.Command) { continue }

        $isPath = $candidate.Command -like '*\*' -or $candidate.Command -like '*/*'

        if ($isPath -and -not (Test-Path $candidate.Command)) { continue }



        $command = $candidate.Command

        $baseArgs = $candidate.Args

        $versionOutput = @()

        try {

            $versionOutput = & $command @baseArgs '--version' 2>&1 | ForEach-Object { $_.ToString() }

        } catch {

            continue

        }



        if ($versionOutput | Where-Object { $_ -match '^Python\s+\d' }) {

            return ,@($command) + $baseArgs

        }



        if ($versionOutput -join ' ' -match 'No pyvenv') {

            continue

        }

    }



    throw 'Python 3.11+ is required but was not found in PATH.'

}

$pythonCmd = Get-PythonCommand



function Invoke-Python {

    param([string[]]$Arguments)

    $cmdParts = @($pythonCmd)

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

    $cmdParts = @($pythonCmd)

    $command = $cmdParts[0]

    $baseArgs = @()

    if ($cmdParts.Count -gt 1) {

        $baseArgs = $cmdParts[1..($cmdParts.Count - 1)]

    }



    $versionLines = @(& $command @baseArgs '--version' 2>&1 | ForEach-Object { $_.ToString() })

    $versionLine = ($versionLines | Where-Object { $_ -match '^Python\s+\d' } | Select-Object -First 1)

    if (-not $versionLine) {

        $fallbackLines = @(& $command @baseArgs '-c' 'import sys; print("Python", sys.version.split()[0])' 2>&1 | ForEach-Object { $_.ToString() })

        $versionLine = ($fallbackLines | Where-Object { $_ -match '^Python\s+\d' } | Select-Object -First 1)

        if (-not $versionLine) {

            $combined = @($versionLines + $fallbackLines) -join [Environment]::NewLine

            throw "Unable to determine Python version. Output:`n$combined"

        }

    }



    if (-not ($versionLine -match 'Python\s+(\d+)\.(\d+)\.(\d+)')) {

        throw "Unable to parse Python version from '$versionLine'"

    }

    $major = [int]$Matches[1]

    $minor = [int]$Matches[2]

    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {

        throw "Python 3.11 or newer is required. Current version: $versionLine"

    }

    Write-Host "Detected $versionLine"

}



function Ensure-Venv {

    $venvConfig = Join-Path $venvPath 'pyvenv.cfg'

    $venvExists = Test-Path $venvPath

    $configExists = Test-Path $venvConfig

    $venvActive = $false

    if ($env:VIRTUAL_ENV) {

        try {

            $venvActive = ([System.IO.Path]::GetFullPath($env:VIRTUAL_ENV)).TrimEnd('\/') -ieq ([System.IO.Path]::GetFullPath($venvPath)).TrimEnd('\/')

        } catch {

            $venvActive = $false

        }

    }



    if (-not $venvExists) {

        Write-Host 'Creating virtual environment (.venv)'

        Invoke-Python @('-m', 'venv', $venvPath)

        return

    }



    if (-not $configExists) {

        if ($venvActive) {

            Write-Warning 'pyvenv.cfg is missing but the virtual environment is currently active; skipping repair.'

            Write-Warning 'Deactivate the environment and rerun the script if you want it to be recreated.'

            return

        }

        Write-Host 'Repairing virtual environment (.venv)'

        try {

            Invoke-Python @('-m', 'venv', '--upgrade', $venvPath)

        }

        catch {

            Write-Warning "Upgrade of existing virtual environment failed: $($_.Exception.Message)"

            Write-Warning 'Attempting to recreate .venv; close applications using this directory if prompted.'

            try {

                Remove-Item -Recurse -Force $venvPath -ErrorAction Stop

                Invoke-Python @('-m', 'venv', $venvPath)

            }

            catch {

                Write-Warning "Unable to recreate virtual environment at $venvPath. Close running applications and retry manually. Error: $($_.Exception.Message)"

            }

        }

        return

    }



    Write-Host 'Virtual environment already exists'

}



function Install-Dependencies {

    Write-Host 'Installing project dependencies (editable)'

    $runningProcs = Get-Process python -ErrorAction SilentlyContinue | Where-Object {

        $_.Path -and ($_.Path -like (Join-Path $venvPath '*')) -and $_.Id -ne $PID

    }

    foreach ($proc in $runningProcs) {

        try {

            Write-Warning "Stopping process ${($proc.ProcessName)} (PID $($proc.Id)) using the virtual environment."

            Stop-Process -Id $proc.Id -Force -ErrorAction Stop

        } catch {

            Write-Warning "Failed to stop process $($proc.Id): $($_.Exception.Message)"

        }

    }

    $ensurepipFailed = $false

    try {

        Invoke-VenvPython @('-m', 'ensurepip', '--upgrade')

    } catch {

        $ensurepipFailed = $true

        Write-Warning "ensurepip failed: $($_.Exception.Message)"

    }

    try {

        Invoke-VenvPython @('-m', 'pip', 'install', '--upgrade', 'pip', 'wheel', 'setuptools')

    } catch {

        if ($ensurepipFailed) {

            throw "pip is unavailable in the virtual environment and ensurepip could not repair it. Please reinstall the virtualenv manually. Error: $($_.Exception.Message)"

        }

        throw

    }

    Invoke-VenvPython @('-m', 'pip', 'install', '-e', '.[dev]')

}



function Ensure-AttachmentsDirectory {

    if (-not (Test-Path $attachmentsDir)) {

        Write-Host "Creating attachments directory at $attachmentsDir"

        New-Item -ItemType Directory -Path $attachmentsDir | Out-Null

    }

}



function Ensure-EnvFile {

    $defaults = [ordered]@{

        'DATABASE_URL' = 'postgresql+asyncpg://avtomail:avtomail@localhost:5432/avtomail'

        'SECRET_KEY' = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')

        'DEFAULT_ADMIN_EMAIL' = 'admin@example.com'

        'DEFAULT_ADMIN_PASSWORD' = 'ChangeMe!123'

        'CELERY_BROKER_URL' = 'redis://localhost:6379/0'

        'CELERY_RESULT_BACKEND' = 'redis://localhost:6379/0'

        'CELERY_TASK_ALWAYS_EAGER' = 'false'

        'CELERY_TASK_EAGER_PROPAGATES' = 'true'

        'ATTACHMENTS_DIR' = $attachmentsDir

        'MAX_ATTACHMENT_SIZE_MB' = '25'

        'SENTRY_DSN' = ''

        'PROJECT_NAME' = 'Avtomail'

    }



    $existingKeys = @{}

    $needsRewrite = $false

    if (Test-Path $envPath) {

        Write-Host 'Checking existing .env for required settings'

        foreach ($line in Get-Content $envPath) {

            $trimmed = $line.Trim()

            if (-not $trimmed -or $trimmed.StartsWith('#')) {

                continue

            }

            $splitIndex = $trimmed.IndexOf('=')

            if ($splitIndex -lt 1) {

                $needsRewrite = $true

                break

            }

            $key = $trimmed.Substring(0, $splitIndex).Trim()

            $existingKeys[$key] = $true

        }

    }



    if (-not (Test-Path $envPath) -or $needsRewrite) {

        if ($needsRewrite) {

            Write-Host 'Existing .env file is malformed; regenerating defaults'

        } else {

            Write-Host 'Creating new .env file with defaults'

        }

        $content = @("# Auto-generated defaults $(Get-Date -Format o)")

        foreach ($entry in $defaults.GetEnumerator()) {

            $content += ('{0}={1}' -f $entry.Key, $entry.Value)

        }

        Set-Content -Path $envPath -Value $content -Encoding UTF8

        return

    }



    $linesToAppend = @()

    foreach ($entry in $defaults.GetEnumerator()) {

        if (-not $existingKeys.ContainsKey($entry.Key)) {

            $value = $entry.Value

            if ($entry.Key -eq 'SECRET_KEY') {

                $value = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')

            }

            $linesToAppend += ('{0}={1}' -f $entry.Key, $value)

        }

    }



    if ($linesToAppend.Count -gt 0) {

        Add-Content -Path $envPath -Value "# Auto-generated defaults $(Get-Date -Format o)" -Encoding UTF8

        Add-Content -Path $envPath -Value $linesToAppend -Encoding UTF8

    }

}



function Load-DotEnv {

    if (-not (Test-Path $envPath)) {

        return

    }

    foreach ($line in Get-Content $envPath) {

        $trimmed = $line.Trim()

        if (-not $trimmed -or $trimmed.StartsWith('#')) {

            continue

        }

        $splitIndex = $trimmed.IndexOf('=')

        if ($splitIndex -lt 1) {

            continue

        }

        $key = $trimmed.Substring(0, $splitIndex).Trim()

        $value = $trimmed.Substring($splitIndex + 1)

        if ($value.StartsWith('"') -and $value.EndsWith('"')) {

            $value = $value.Trim('"')

        } elseif ($value.StartsWith("'") -and $value.EndsWith("'")) {

            $value = $value.Trim("'")

        }

        [Environment]::SetEnvironmentVariable($key, $value, 'Process')

    }

}



function Run-Migrations {

    Write-Host 'Running Alembic migrations'

    Push-Location $backendDir

    $previousPythonPath = $env:PYTHONPATH

    try {

        if ($previousPythonPath) {

            $env:PYTHONPATH = "$backendDir;$previousPythonPath"

        } else {

            $env:PYTHONPATH = $backendDir

        }

        try {

            Invoke-VenvPython @('-m', 'alembic', '-c', 'alembic.ini', 'upgrade', 'head')

        } catch {

            $message = $_.Exception.Message

            Write-Warning "Database migrations skipped: $message"

            Write-Warning 'Ensure PostgreSQL is running and rerun the script (or specify -SkipMigrations) once the database is available.'

        }

    } finally {

        $env:PYTHONPATH = $previousPythonPath

        Pop-Location

    }

}



function Run-Tests {

    Write-Host 'Running pytest'

    Push-Location $projectRoot

    try {

        Invoke-VenvPython @('-m', 'pytest')

    } finally {

        Pop-Location

    }

}



function Start-Uvicorn {

    Write-Host "Starting API on ${BindAddress}:${Port}"

    Push-Location $backendDir

    $previousPythonPath = $env:PYTHONPATH

    try {

        $env:PYTHONPATH = if ($previousPythonPath) { "$backendDir;$previousPythonPath" } else { $backendDir }

        Invoke-VenvPython @('-m', 'uvicorn', 'app.main:app', '--host', $BindAddress, '--port', $Port.ToString())

    } finally {

        $env:PYTHONPATH = $previousPythonPath

        Pop-Location

    }

}



function Start-CeleryWorker {

    Write-Host 'Starting Celery worker'

    Push-Location $backendDir

    $previousPythonPath = $env:PYTHONPATH

    try {

        $env:PYTHONPATH = if ($previousPythonPath) { "$backendDir;$previousPythonPath" } else { $backendDir }

        Invoke-VenvPython @('-m', 'celery', '-A', 'app.workers.celery_app.celery_app', 'worker', '--loglevel=info')

    } finally {

        $env:PYTHONPATH = $previousPythonPath

        Pop-Location

    }

}



Ensure-PythonVersion



if (-not $SkipInstall) {

    Ensure-Venv

    Ensure-AttachmentsDirectory

    Ensure-EnvFile

    Install-Dependencies

}



Ensure-AttachmentsDirectory

Ensure-EnvFile

Load-DotEnv



if (-not $SkipMigrations) {

    Run-Migrations

}



if (-not $SkipTests) {

    Run-Tests

}



if ($StartWorker) {

    Start-CeleryWorker

}



if ($StartServer) {

    Start-Uvicorn

} else {

    Write-Host 'Deployment completed successfully.' -ForegroundColor Green

    Write-Host 'Use -StartServer and/or -StartWorker to launch services.'

}

