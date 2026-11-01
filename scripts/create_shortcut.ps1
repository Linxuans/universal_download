[CmdletBinding()]
param(
    [string]$Name = "下载工作台",
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = (Get-Command pythonw -ErrorAction Stop).Source
$Target = Join-Path $Root "scripts\gui.py"
$Icon = Join-Path $Root "gui\assets\icon.ico"
if (-not (Test-Path $Target)) { throw "missing $Target" }

$Desktop = if ($Destination) { $Destination } else { [Environment]::GetFolderPath("Desktop") }
$Link = Join-Path $Desktop ($Name + ".lnk")
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = '"' + $Target + '"'
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = $Icon + ",0"
$Shortcut.Description = "FetchDesk 下载工作台"
$Shortcut.WindowStyle = 1
$Shortcut.Save()
Write-Host "created $Link"