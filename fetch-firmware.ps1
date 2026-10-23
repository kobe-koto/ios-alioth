<#
.SYNOPSIS
  把 iOS 16.5 (20F66, iPhone10,3/10,6) 的 IPSW 固件取到 firmware/ 目录，并校验 MD5。
  文件已存在且完整时直接返回；损坏/不完整则删除重下；下载支持断点续传与重试。

.DESCRIPTION
  URL 与大小取自上游 ios165/fetch-from-ipsw.py（Apple CDN 官方直链）。
  下载完成后按 大小 + MD5 双重校验，避免半截文件或损坏的固件进入后续构建。
  校验通过后写 firmware\.verified，供一键启动脚本快速跳过重复校验。

  注意：这个 IPSW 只是“重建 system.apfs”的原料；一键临时启动用的是 boot/system.apfs，
  不需要固件。启动脚本会在固件缺失时尝试补全，失败也不会阻止启动。

.PARAMETER Force
  即使文件已存在且校验通过，也重新下载。

.PARAMETER CheckOnly
  只校验，不下载；文件缺失或校验失败时以非 0 退出。

.PARAMETER Dir
  固件目录，默认是脚本同级的 firmware/。

.EXAMPLE
  .\fetch-firmware.ps1
  .\fetch-firmware.ps1 -CheckOnly
#>
#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$CheckOnly,
    [string]$Dir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Dir) { $Dir = Join-Path $Root "firmware" }
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

$Name = "iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw"
$Size = 6165698198
$Md5  = "f87b4bd6f3c86fb174ce017b5a5ca97b"
$Url  = "https://updates.cdn-apple.com/2023SpringFCS/fullrestores/032-85130/6AB0D10A-8AF9-4F6C-8CF5-A1B315CABE88/iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw"

$Target = Join-Path $Dir $Name
$Part = "$Target.part"
$Marker = Join-Path $Dir ".verified"

function Get-Md5([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm MD5).Hash.ToLower()
}

function Test-Firmware([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $len = (Get-Item -LiteralPath $Path).Length
    if ($len -ne $Size) {
        Write-Host ("firmware: size {0} != expected {1}" -f $len, $Size) -ForegroundColor Yellow
        return $false
    }
    if (Test-Path -LiteralPath $Marker) {
        $m = (Get-Content -LiteralPath $Marker -Raw).Trim()
        if ($m -eq "$Md5 $Size") {
            Write-Host "firmware: already verified (marker)" -ForegroundColor Green
            return $true
        }
    }
    Write-Host "firmware: checking MD5 (6.2 GB, a few seconds)..." -ForegroundColor Cyan
    $actual = Get-Md5 $Path
    if ($actual -ne $Md5) {
        Write-Host "firmware: MD5 mismatch: $actual" -ForegroundColor Red
        return $false
    }
    Set-Content -LiteralPath $Marker -Value "$Md5 $Size" -Encoding ASCII
    Write-Host "firmware: MD5 OK" -ForegroundColor Green
    return $true
}

if (-not $Force -and (Test-Firmware $Target)) { exit 0 }
if ($CheckOnly) {
    Write-Host "firmware: missing or invalid: $Target" -ForegroundColor Red
    exit 1
}

$curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curl) { throw "找不到 curl.exe（Windows 10 1803+ 自带）；请手动把 $Name 放到 $Dir" }

if ($Force -and (Test-Path -LiteralPath $Target)) { Remove-Item -LiteralPath $Target -Force }
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
if ((Test-Path -LiteralPath $Part) -and ((Get-Item -LiteralPath $Part).Length -gt $Size)) {
    Remove-Item -LiteralPath $Part -Force
}

for ($attempt = 1; $attempt -le 3; $attempt++) {
    Write-Host ""
    Write-Host "firmware: download attempt $attempt/3 ($([math]::Round($Size/1GB,2)) GB, resumable)" -ForegroundColor Cyan
    # -C - 断点续传；--retry 处理 Apple CDN 的短断流
    & $curl -L --fail --retry 5 --retry-delay 3 -C - -o $Part $Url
    if ($LASTEXITCODE -ne 0) { Write-Host "firmware: curl exit $LASTEXITCODE" -ForegroundColor Yellow }
    if (-not (Test-Path -LiteralPath $Part)) { continue }
    $got = (Get-Item -LiteralPath $Part).Length
    if ($got -ne $Size) {
        Write-Host ("firmware: partial {0} / {1}" -f $got, $Size) -ForegroundColor Yellow
        continue
    }
    $actual = Get-Md5 $Part
    if ($actual -ne $Md5) {
        Write-Host "firmware: MD5 mismatch ($actual); starting over" -ForegroundColor Red
        Remove-Item -LiteralPath $Part -Force
        continue
    }
    Move-Item -LiteralPath $Part -Destination $Target -Force
    Set-Content -LiteralPath $Marker -Value "$Md5 $Size" -Encoding ASCII
    Write-Host "firmware: downloaded and verified: $Target" -ForegroundColor Green
    exit 0
}

Remove-Item -LiteralPath $Part -Force -ErrorAction SilentlyContinue
throw "固件下载/校验失败（3 次）。可手动下载：$Url  ->  $Target（MD5 $Md5）"
