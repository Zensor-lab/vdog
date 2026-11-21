# =============================================================================
# vdog prebuilt-firmware setup wrapper for Windows (master plan 0.9.6).
#
# Creates or reuses an ISOLATED local installer environment
# (.venv-installer\ next to this script), installs the hash-pinned
# dependencies from requirements-installer.lock into it, and then runs the same
# install.py entry point inside that environment. All arguments pass through:
#
#   .\install.ps1 check
#   .\install.ps1 ports
#   .\install.ps1 plan --board seeed-xiao-esp32s3-sense
#   .\install.ps1 inspect --port COM4
#   .\install.ps1 install --port COM4 --board seeed-xiao-esp32s3-sense --dry-run
#
# If scripts are blocked in your session, allow them for that process only:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# Guarantees (identical to install.sh): no global Python is used or modified,
# no elevation, no copied virtual environment, no download-and-execute pipe;
# dependencies are installed with --require-hashes from the lockfile; the
# resolved interpreter must be CPython 3.12; every path is quoted by
# PowerShell's argument array, so spaces and non-ASCII paths work; missing
# prerequisites stop with an actionable error.
#
# First setup downloads the pinned wheels, so it needs network access; later
# runs reuse the environment and work offline.
#
# Overrides (all optional): $env:VDOG_INSTALLER_UV,
# $env:VDOG_INSTALLER_VENV_DIR, $env:VDOG_INSTALLER_PYTHON.
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallPy = Join-Path $ScriptDir 'install.py'
$RequirementsLock = Join-Path $ScriptDir 'requirements-installer.lock'
$VenvDir = if ($env:VDOG_INSTALLER_VENV_DIR) { $env:VDOG_INSTALLER_VENV_DIR } else { Join-Path $ScriptDir '.venv-installer' }
$QualifiedPython = if ($env:VDOG_INSTALLER_PYTHON) { $env:VDOG_INSTALLER_PYTHON } else { '3.12.12' }
$QualifiedMinor = '3.12'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
# Marker string the dependency probe runs; keep in sync with the wrapper tests.
$DepProbe = 'import esptool, serial; assert esptool.__version__ == "5.4.0"'

function Stop-Installer {
    param([string]$Message, [string[]]$Details = @())
    Write-Error -Message $Message -ErrorAction Continue
    foreach ($line in $Details) { Write-Host "       $line" -ErrorAction Continue }
    exit 2
}

function Test-InstallerEnvComplete {
    # True only when the isolated interpreter is usable, is the qualified minor
    # version and already carries the locked dependencies.
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { return $false }
    $version = (& $VenvPython -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $version) { return $false }
    if ($version.Trim() -ne $QualifiedMinor) { return $false }
    & $VenvPython -c $DepProbe *> $null
    return ($LASTEXITCODE -eq 0)
}

# --- prerequisites ----------------------------------------------------------
if (-not (Test-Path -LiteralPath $InstallPy -PathType Leaf)) {
    Stop-Installer "install.py not found beside this script in '$ScriptDir'." @(
        'Extract the complete release ZIP and run the wrapper from inside the',
        "extracted 'vdog-xiao-sense-...' directory."
    )
}
if (-not (Test-Path -LiteralPath $RequirementsLock -PathType Leaf)) {
    Stop-Installer "requirements-installer.lock is missing from '$ScriptDir'." @(
        'The bundle is incomplete; re-download it from the GitHub Release and',
        'verify its .sha256 before installing.'
    )
}

# --- fast path: a complete environment needs no uv and no network -----------
# First setup needs uv (and network) to build the environment; every later run
# must work from the environment alone, even if uv is not on this PATH.
if (Test-InstallerEnvComplete) {
    & $VenvPython $InstallPy @args
    exit $LASTEXITCODE
}

$UvBin = $env:VDOG_INSTALLER_UV
if ($UvBin -and -not (Test-Path -LiteralPath $UvBin -PathType Leaf)) {
    Stop-Installer "VDOG_INSTALLER_UV points to '$UvBin', which is not a file." @(
        'Unset it, or point it at a working uv.exe.'
    )
}
if (-not $UvBin) {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { $UvBin = $command.Source }
}
if (-not $UvBin) {
    Stop-Installer "'uv' was not found, and it is required to build the isolated installer environment." @(
        'Install uv with winget install astral-sh.uv, choco install uv, or from',
        'https://docs.astral.sh/uv/, then rerun this script. Do NOT pipe a',
        'downloaded install script into a shell; install a packaged uv instead.',
        'If uv is already installed somewhere unusual, set',
        '$env:VDOG_INSTALLER_UV = "C:\path\to\uv.exe".'
    )
}

function Invoke-Uv {
    param([string[]]$UvArgs, [switch]$Capture)
    # ArgumentList as an array: PowerShell quotes each element, so paths with
    # spaces or non-ASCII characters survive unchanged.
    if ($Capture) {
        & $UvBin @UvArgs 2>$null
    }
    else {
        & $UvBin @UvArgs
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    return $true
}

# --- select the qualified CPython 3.12 --------------------------------------
$Py = (Invoke-Uv @('python', 'find', $QualifiedPython) -Capture) | Select-Object -First 1
if (-not $Py) {
    Write-Host "installer: CPython $QualifiedPython not found locally; installing it with uv (needs network)"
    if (-not (Invoke-Uv @('python', 'install', $QualifiedPython))) {
        Stop-Installer "uv could not provision CPython $QualifiedPython." @(
            'Check network access, or pick another qualified 3.12 patch with',
            '$env:VDOG_INSTALLER_PYTHON (for example "3.12").'
        )
    }
    $Py = (Invoke-Uv @('python', 'find', $QualifiedPython) -Capture) | Select-Object -First 1
}
if (-not $Py) {
    Stop-Installer "uv still cannot locate CPython $QualifiedPython after installation." @(
        "Run '$UvBin python list' to see what is available, then set",
        '$env:VDOG_INSTALLER_PYTHON to a 3.12 interpreter.'
    )
}

# --- create or reuse the isolated environment -------------------------------
if ((Test-Path -LiteralPath $VenvDir) -and -not (Test-Path -LiteralPath $VenvDir -PathType Container)) {
    Stop-Installer "'$VenvDir' exists but is not a directory." @(
        'Move it away, or choose another location with VDOG_INSTALLER_VENV_DIR.'
    )
}
if ((Test-Path -LiteralPath $VenvDir -PathType Container) -and -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Stop-Installer "'$VenvDir' exists but has no usable '$VenvPython'." @(
        'It is a partial or copied environment, which this wrapper will not',
        'repair silently. Remove that directory and rerun, or point',
        'VDOG_INSTALLER_VENV_DIR somewhere else.'
    )
}
if (-not (Test-Path -LiteralPath $VenvDir -PathType Container)) {
    Write-Host "installer: creating the isolated environment $VenvDir"
    if (-not (Invoke-Uv @('venv', '--python', $Py, $VenvDir))) {
        Stop-Installer "uv could not create the isolated environment at '$VenvDir'." @(
            'Check that the parent directory is writable, or set',
            'VDOG_INSTALLER_VENV_DIR to a writable path.'
        )
    }
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Stop-Installer "the environment at '$VenvDir' has no Scripts\python.exe after setup." @(
        'Remove the directory and rerun, or choose another VDOG_INSTALLER_VENV_DIR.'
    )
}

# Never run against an interpreter that is not the qualified minor version.
$Resolved = (& $VenvPython -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Resolved) { $Resolved = '' }
if ($Resolved.Trim() -ne $QualifiedMinor) {
    Stop-Installer "the installer environment at '$VenvDir' reports Python '$($Resolved.Trim())', but this bundle is qualified on CPython $QualifiedMinor only." @(
        "Remove that directory (or set VDOG_INSTALLER_VENV_DIR) and rerun with",
        "VDOG_INSTALLER_PYTHON set to a $QualifiedMinor interpreter."
    )
}

# --- install the locked dependencies with hashes ----------------------------
& $VenvPython -c $DepProbe *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'installer: installing the pinned installer dependencies (needs network on first setup)'
    if (-not (Invoke-Uv @('pip', 'install', '--python', $VenvPython, '--require-hashes', '-r', $RequirementsLock))) {
        Stop-Installer 'the locked installer dependencies could not be installed.' @(
            'First setup needs network access. If the hash check itself failed,',
            "the bundle's requirements-installer.lock was tampered with or is",
            'incomplete: re-download the release ZIP and verify its .sha256.',
            'Never install esptool from an unofficial source into this environment.'
        )
    }
    & $VenvPython -c $DepProbe *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-Installer 'the environment still lacks the qualified esptool 5.4.0 / pyserial pair.' @(
            'Re-run from a clean VDOG_INSTALLER_VENV_DIR with network access;',
            'this wrapper will not fall back to an ambient esptool.'
        )
    }
}

# --- run the same entry point in the isolated environment -------------------
& $VenvPython $InstallPy @args
exit $LASTEXITCODE
