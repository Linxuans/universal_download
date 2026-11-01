[CmdletBinding()]
param(
    [string]$Proxy = "http://127.0.0.1:7890",
    [switch]$NoProxy,
    [switch]$Check,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'."
}

$Arguments = @((Join-Path $Root "scripts\bootstrap.py"))
if ($NoProxy) {
    $Arguments += "--no-proxy"
} elseif ($Proxy) {
    $Arguments += @("--proxy", $Proxy)
}
if ($Check) { $Arguments += "--check" }
if ($Force) { $Arguments += "--force" }

& $Python.Source @Arguments
exit $LASTEXITCODE