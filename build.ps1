# 단일 실행 파일(.exe) 빌드
#   .\build.ps1 -Template C:\경로\양식.hwpx
param(
    [Parameter(Mandatory = $true)][string]$Template,
    [string]$Icon = "assets\icon.png",
    [string]$Name = "증빙 니가해"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path $Template)) { throw "양식 파일을 찾을 수 없습니다: $Template" }

python make_template.py $Template
python make_icon.py $Icon

python -m PyInstaller --noconfirm --onefile --windowed `
    --icon app_icon.ico --name $Name `
    --distpath dist --workpath build --specpath . app.py

Write-Host "완료: dist\$Name.exe"
