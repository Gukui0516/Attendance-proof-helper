param([string]$Template, [string]$Renderer)
$ErrorActionPreference = 'Stop'
if (-not $Template -or -not $Renderer) { throw 'Pass -Template original.hwpx -Renderer rhwp.exe' }
$taskPython=(Get-Command python).Source
$taskPythonDir=Split-Path $taskPython
$taskOldPath=$env:PATH
try {
    # Prevent unrelated native DLLs (e.g. Poppler/libheif) on PATH from entering EXE.
    $env:PATH="$env:SystemRoot\System32;$env:SystemRoot;$taskPythonDir"
    & $taskPython -m PyInstaller --noconfirm --onefile --windowed --exclude-module numpy --name Attendance-proof-helper --add-data "${Template};." --add-binary "${Renderer};." --add-data "$PSScriptRoot\licenses;licenses" "$PSScriptRoot\main.py"
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
} finally { $env:PATH=$taskOldPath }
