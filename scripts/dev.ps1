param(
    [switch]$InstallOnly,
    [switch]$RunOnly,
    [switch]$NoReload,
    [int]$Port = 8000,
    [string]$BindAddress = '127.0.0.1'
)

if ($InstallOnly -and $RunOnly) {
    throw 'Use either -InstallOnly or -RunOnly, not both.'
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = $null
$pythonArgs = @()

foreach ($candidate in @('python', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) {
        continue
    }
    if ($cmd.Name -eq 'py') {
        $pythonExe = $cmd.Path
        $pythonArgs = @('-3')
    } else {
        $pythonExe = $cmd.Path
        $pythonArgs = @()
    }
    break
}

if (-not $pythonExe) {
    throw 'Python 3.11+ is required to run this project.'
}

$devScript = Join-Path $scriptRoot 'dev.py'

$cliArgs = @()
if ($InstallOnly) { $cliArgs += '--install-only' }
if ($RunOnly) { $cliArgs += '--run-only' }
if ($NoReload) { $cliArgs += '--no-reload' }
$cliArgs += '--port'
$cliArgs += $Port
$cliArgs += '--bind-address'
$cliArgs += $BindAddress

& $pythonExe @pythonArgs $devScript @cliArgs
