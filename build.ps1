# Build helper for whyknot-yt-dlp-plugins.
#
# Mirrors the API surface of WKVRCProxy/build.ps1 (param shape, version
# validation, auto-derive from date) but produces Python sdist + wheel
# artifacts instead of a Windows single-file exe. Used by:
#
#   - .github/workflows/release.yml on tag push (passes -Version <tag-no-v>)
#   - local dev (`./build.ps1` to make a wheel under dist/ for testing)
#
# Versioning scheme matches the wider WhyKnot CalVer: YYYY.M.D.N, where N
# is the daily build counter starting at 0. The -XXXX hex suffix that
# WKVRCProxy uses for local-rebuild disambiguation is intentionally NOT
# applied here -- the plugin repo never has parallel local rebuilds at
# the same daily counter (one push = one version, git is the source of
# truth) and the Python PEP 440 normaliser would mangle the hyphen form.

param(
    # release.yml passes the bare git tag (no leading "v") so the published
    # tag, sdist filename, and wheel filename stay in sync. Local builds
    # leave this empty and get an auto-derived YYYY.M.D.N stamp.
    [string]$Version = "",

    # Skip building the sdist/wheel artifacts. pyproject.toml is still
    # updated with the resolved version.
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$BuildDir  = Join-Path $PSScriptRoot "dist"
$StateFile = Join-Path $PSScriptRoot ".local_build_state.json"

# --- Versioning ---
if ($Version) {
    if ($Version -notmatch '^\d{4}\.\d+\.\d+\.\d+(-beta)?$') {
        throw "Invalid -Version '$Version'. Expected YYYY.M.D.N or YYYY.M.D.N-beta (CalVer)."
    }
    # Translate -beta to PEP 440 pre-release notation (b0) for pyproject.toml.
    # The tag itself keeps the -beta suffix; only the version written to the
    # package metadata is normalised. Example:
    #   2026.5.17.0-beta -> 2026.5.17.0b0
    # If you need to ship a second pre-release for the same numeric base,
    # bump the patch instead (2026.5.17.1-beta).
    $FullVersion = $Version -replace '-beta$','b0'
} else {
    $Today = Get-Date -Format "yyyy.M.d"
    $BuildCount = 0
    if (Test-Path $StateFile) {
        $State = Get-Content $StateFile | ConvertFrom-Json
        if ($State.Date -eq $Today) { $BuildCount = [int]$State.Count + 1 }
    }
    $FullVersion = "$Today.$BuildCount"
    @{ Date = $Today; Count = $BuildCount } | ConvertTo-Json | Out-File $StateFile -Encoding utf8
}
Write-Host "Building Version: $FullVersion" -ForegroundColor Magenta

# --- Update pyproject.toml in place ---
$Pyproject = Join-Path $PSScriptRoot "pyproject.toml"
$content = Get-Content $Pyproject -Raw
$content = $content -replace '(?m)^version = "[^"]+"', "version = `"$FullVersion`""
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($Pyproject, $content, $Utf8NoBom)

# --- Build sdist + wheel ---
if (-not $SkipBuild) {
    if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
    New-Item -ItemType Directory $BuildDir -Force | Out-Null

    # Use uv if available (faster + matches the production install path);
    # fall back to `python -m build` for environments without uv.
    $buildTool = if (Get-Command uv -ErrorAction SilentlyContinue) { "uv" }
                 elseif (Get-Command pip -ErrorAction SilentlyContinue) { "pip" }
                 else { throw "Neither uv nor pip is on PATH; cannot build artifacts." }

    if ($buildTool -eq "uv") {
        & uv build --out-dir $BuildDir
    } else {
        # Ensure `build` is installed; non-fatal if already present.
        & python -m pip install --quiet --upgrade build
        & python -m build --outdir $BuildDir
    }
    if ($LASTEXITCODE -ne 0) { throw "Build failed (exit $LASTEXITCODE)." }

    Write-Host "Artifacts:" -ForegroundColor Green
    Get-ChildItem $BuildDir | ForEach-Object { Write-Host "  $($_.Name)" }
}

Write-Host "Done. version=$FullVersion" -ForegroundColor Green
