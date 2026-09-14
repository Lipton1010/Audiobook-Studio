param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot
)

$root = [System.IO.Path]::GetFullPath($AppRoot)
$targets = @(
    'app\server.py',
    'app\launcher.py',
    'app\narrate_worker.py',
    'app\vibevoice_worker.py'
) | ForEach-Object { [System.IO.Path]::GetFullPath((Join-Path $root $_)) }

$running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $command = $_.CommandLine
    $command -and ($targets | Where-Object {
        $command.IndexOf($_, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    })
}

if ($running) {
    exit 9
}
