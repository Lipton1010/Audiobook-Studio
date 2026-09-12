$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$outputRoot = (Resolve-Path -LiteralPath (Join-Path $repo 'Output')).Path
$fixture = Join-Path $outputRoot ('installer-record-test-' + [guid]::NewGuid().ToString('N'))
$script = Join-Path $repo 'install/record_installer.ps1'
$commit = (git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the test checkout' }
New-Item -ItemType Directory -Path $fixture | Out-Null
try {
    foreach ($name in @('Setup_AudiobookStudio', 'Setup_AudiobookStudio_Patch')) {
        foreach ($suffix in @('.exe', '-manifest.txt')) {
            Copy-Item -LiteralPath (Join-Path $outputRoot "$name$suffix") -Destination $fixture
        }
    }
    $full = Join-Path $fixture 'Setup_AudiobookStudio.exe'
    Copy-Item -LiteralPath $full -Destination (Join-Path $fixture 'Setup_AudiobookStudio_0.0.1.exe')
    foreach ($name in @('Setup_AudiobookStudio', 'Setup_AudiobookStudio_Patch')) {
        & $script -OutputDirectory $fixture -Artifact $name -Commit $commit
        if (!$?) { throw 'Build recording failed' }
        $entry = Get-Content -LiteralPath (Join-Path $fixture "$name-build.json") -Raw | ConvertFrom-Json
        if ($entry.sha256 -ne (Get-FileHash -LiteralPath (Join-Path $fixture "$name.exe")).Hash) {
            throw 'Receipt hash is wrong'
        }
        $expected = if ($name -eq 'Setup_AudiobookStudio') {
            "Installer_AudiobookStudio_$($entry.version).exe"
        } else {
            "Patch_AudiobookStudio_$($entry.version).exe"
        }
        if ($entry.distribution_name -ne $expected) {
            throw 'Distribution name does not match the authorized beta handoff pattern'
        }
    }
    if (@(Get-ChildItem -LiteralPath $fixture -Filter *.exe -File).Count -ne 2) {
        throw 'Not exactly two current executables'
    }
    $older = @(Get-ChildItem -LiteralPath (Join-Path $fixture 'Old, do not use') -Filter *.exe -Recurse -File)
    if ($older.Count -ne 1 -or (Get-FileHash -LiteralPath $older[0].FullName).Hash -ne (Get-FileHash -LiteralPath $full).Hash) {
        throw 'Archive did not preserve bytes'
    }
    $receiptPath = Join-Path $fixture 'Setup_AudiobookStudio_Patch-build.json'
    $entry = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $entry.sha256 = 'bad'
    $entry | ConvertTo-Json | Set-Content -LiteralPath $receiptPath
    & $script -OutputDirectory $fixture -Artifact Setup_AudiobookStudio -Commit $commit
    if (!(Select-String -LiteralPath (Join-Path $fixture '00_CURRENT_INSTALLERS.txt') -SimpleMatch 'HASH MISMATCH')) {
        throw 'Mismatched receipt not flagged'
    }
    Write-Output 'PASS: authorized distribution names, two current EXEs, lossless archive, stale receipt warning.'
} finally {
    $resolved = (Resolve-Path -LiteralPath $fixture).Path
    if ((Split-Path -Parent $resolved) -ne $outputRoot -or (Split-Path -Leaf $resolved) -notlike 'installer-record-test-*') {
        throw 'Refusing cleanup outside the test fixture'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
