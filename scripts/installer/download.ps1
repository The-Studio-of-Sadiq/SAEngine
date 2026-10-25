<#
.SYNOPSIS
    Save-Download: the one way the installer scripts download a file (dot-source this file).

.DESCRIPTION
    Uses curl.exe (part of Windows 10 1803 and later) so that a download can never hang: the
    connection times out after 30 s, a transfer slower than 50 kB/s for 2 minutes is abandoned,
    one attempt may take at most 2 hours, and a failed attempt is retried 4 times with a growing
    pause. A release build once hung for 3 hours on a stalled Qt source download with
    Invoke-WebRequest, which has no speed limit. The file is written to <OutFile>.partial and only
    renamed when curl succeeds; the callers check the SHA-256 afterwards.
#>

function Save-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $curl) {
        throw 'curl.exe is not on PATH (it is part of Windows 10 1803 and later).'
    }
    $partial = "$OutFile.partial"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    Write-Host "Downloading $Uri"
    $arguments = @('--fail', '--location', '--silent', '--show-error',
        '--connect-timeout', '30', '--speed-limit', '50000', '--speed-time', '120', '--max-time', '7200',
        '--retry', '4', '--retry-delay', '15', '--retry-all-errors',
        '--user-agent', 'saengine-build', '--output', $partial, $Uri)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $curl.Source @arguments
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        throw "Downloading $Uri failed (curl exit code $code, after retries)."
    }
    Move-Item -LiteralPath $partial -Destination $OutFile -Force
}
