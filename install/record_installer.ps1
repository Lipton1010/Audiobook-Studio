param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][ValidateSet('Setup_AudiobookStudio', 'Setup_AudiobookStudio_Patch')][string]$Artifact,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit
)

$ErrorActionPreference = 'Stop'

function Get-Sha256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($stream)
        return ([System.BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
    }
}

$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$exe = Get-Item -LiteralPath (Join-Path $outputRoot "$Artifact.exe")
$manifest = Get-Item -LiteralPath (Join-Path $outputRoot "$Artifact-manifest.txt")
$version = $exe.VersionInfo.ProductVersion.Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Missing product version: $($exe.FullName)" }
$sha256 = Get-Sha256 $exe.FullName
$distributionPrefix = if ($Artifact -eq 'Setup_AudiobookStudio') {
    'Installer_AudiobookStudio'
} else {
    'Patch_AudiobookStudio'
}

$record = [ordered]@{
    file = $exe.Name
    version = $version
    source_commit = $Commit
    artifact_written_utc = $exe.LastWriteTimeUtc.ToString('o')
    bytes = $exe.Length
    sha256 = $sha256
    distribution_name = "${distributionPrefix}_${version}.exe"
    manifest_sha256 = Get-Sha256 $manifest.FullName
    status = 'Beta candidate; exact-build release checklist still required.'
}
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputRoot "$Artifact-build.json") -Encoding UTF8

# Keep historical copies recoverable, away from the two fixed handoff filenames.
$older = @(Get-ChildItem -LiteralPath $outputRoot -File | Where-Object {
    $_.Name -match '^Setup_AudiobookStudio(?:_Patch)?_\d+\.\d+\.\d+\.exe$'
})
if ($older.Count) {
    $archive = Join-Path $outputRoot ('Old, do not use\' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $archive | Out-Null
    foreach ($file in $older) {
        Move-Item -LiteralPath $file.FullName -Destination (Join-Path $archive $file.Name)
    }
}

$lines = @(
    'CURRENT AUDIOBOOK STUDIO INSTALLERS',
    '',
    'Use only the two fixed filenames in this folder. Old, do not use contains older builds.',
    'Full installer: Setup_AudiobookStudio.exe (new installation)',
    'Patch: Setup_AudiobookStudio_Patch.exe (existing installation)',
    '',
    'These are beta candidates. Build success does not certify installed operation.',
    'See RELEASE_CHECKLIST.md in the project root for outstanding validation.',
    ''
)
foreach ($name in @('Setup_AudiobookStudio', 'Setup_AudiobookStudio_Patch')) {
    $path = Join-Path $outputRoot "$name.exe"
    $receipt = Join-Path $outputRoot "$name-build.json"
    if (!(Test-Path -LiteralPath $path)) {
        $lines += "$name.exe : NOT BUILT"
    } elseif (!(Test-Path -LiteralPath $receipt)) {
        $lines += "$name.exe : build record missing; verify before handoff"
    } else {
        $entry = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
        $actual = Get-Sha256 $path
        if ($actual -ne $entry.sha256) {
            $lines += "$name.exe : HASH MISMATCH; verify before handoff"
        } else {
            $lines += @(
                "$name.exe : version $($entry.version)",
                "Source commit: $($entry.source_commit)",
                "Google Drive filename: $($entry.distribution_name)",
                "Artifact written (UTC): $($entry.artifact_written_utc)",
                "Bytes: $($entry.bytes)",
                "SHA256: $($entry.sha256)",
                ''
            )
        }
    }
}
$lines | Set-Content -LiteralPath (Join-Path $outputRoot '00_CURRENT_INSTALLERS.txt') -Encoding UTF8
Write-Output "Build identity recorded in $outputRoot\00_CURRENT_INSTALLERS.txt"
