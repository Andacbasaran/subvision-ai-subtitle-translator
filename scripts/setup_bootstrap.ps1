# SubVision AI - Anlik Ekran Altyazi Cevirici (Tam Otomatik Evrensel Kurulum / Bootstrapper)
# Bilgisayarda Python, Pip, VC++ veya Model kurulu olmasa bile resmi kaynaklardan otomatik indirir.

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AppDir = Split-Path -Parent $ScriptDir
Set-Location $AppDir

$VenvPy = Join-Path $AppDir ".venv\Scripts\python.exe"
$VenvPyw = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$RuntimeDir = Join-Path $AppDir "runtime"
$RuntimePy = Join-Path $RuntimeDir "python.exe"
$RuntimePyw = Join-Path $RuntimeDir "pythonw.exe"
$MarkerFile = Join-Path $RuntimeDir ".deps_installed"

# 1. Eger hazir .venv varsa dogrudan baslat
if (Test-Path $VenvPy) {
    Write-Host "[OK] Mevcut sanal ortam (.venv) bulundu, SubVision AI baslatiliyor..." -ForegroundColor Green
    $LaunchBin = if (Test-Path $VenvPyw) { $VenvPyw } else { $VenvPy }
    Start-Process -FilePath $LaunchBin -ArgumentList "main.py" -WorkingDirectory $AppDir
    exit 0
}

# 2. Eger Portable Python (runtime) daha once kurulduysa dogrudan baslat
if ((Test-Path $RuntimePy) -and (Test-Path $MarkerFile)) {
    Write-Host "[OK] Portable Python ortami hazir, SubVision AI baslatiliyor..." -ForegroundColor Green
    $LaunchBin = if (Test-Path $RuntimePyw) { $RuntimePyw } else { $RuntimePy }
    Start-Process -FilePath $LaunchBin -ArgumentList "main.py" -WorkingDirectory $AppDir
    exit 0
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  SUBVISION AI - ANLIK EKRAN ALTYAZI CEVIRICI KURULUM SIHIRBAZI" -ForegroundColor Yellow
Write-Host "  (Bu islem sadece ilk acilista 1 kez yapilir)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# 2.5. Islemci Mimarisi Algilama (x64 / ARM64 / x86)
$Arch = $env:PROCESSOR_ARCHITECTURE
$ArchW6432 = $env:PROCESSOR_ARCHITEW6432
if ($ArchW6432) { $Arch = $ArchW6432 }
Write-Host "[*] Algilanan Islemci Mimarisi: $Arch" -ForegroundColor Cyan

if ($Arch -eq "x86") {
    Write-Host "[HATA] 32-bit (x86) Windows tespit edildi." -ForegroundColor Red
    Write-Host "       CTranslate2 ve ONNX Runtime yapay zeka kutuphaneleri 64-bit islemci gerektirir." -ForegroundColor Yellow
    Read-Host "Cikmak icin Enter'a basin"
    exit 1
}

if ($Arch -eq "ARM64") {
    Write-Host "[*] Windows ARM64 algilandi: PyPI wheel uyumlulugu icin 64-bit x64 (Prism) calisma ortami kullanilacak." -ForegroundColor Yellow
}

# 3. VC++ Redistributable Kontrolu (ONNXRuntime ve CTranslate2 icin yeni formatli PC'lerde gerekir)
$VcDll = Join-Path $env:SystemRoot "System32\vcruntime140_1.dll"
if (-not (Test-Path $VcDll)) {
    try {
        Write-Host "[*] Microsoft Visual C++ Runtime eksik, resmi Microsoft sunucusundan indiriliyor..." -ForegroundColor Yellow
        $VcInstaller = Join-Path $env:TEMP "vc_redist.x64.exe"
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $VcInstaller
        Write-Host "[*] Visual C++ Runtime kuruluyor (Yonetici izni isteyebilir)..." -ForegroundColor Yellow
        Start-Process -FilePath $VcInstaller -ArgumentList "/install /quiet /norestart" -Wait
    } catch {
        Write-Host "[UYARI] Visual C++ Runtime otomatik kurulamadi: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "        Kurulum devam edecek; acilista DLL hatasi alirsaniz Microsoft VC++ x64 paketini kurun." -ForegroundColor Yellow
    }
}

# 4. Portable Python 3.11.9 Indirme (python.org Resmi Sunucusu - Sistemde Python olmasa bile calisir!)
if (-not (Test-Path $RuntimePy)) {
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    $PyZip = Join-Path $RuntimeDir "python-embed.zip"
    $PyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"

    Write-Host "[1/3] Resmi Portable Python 3.11.9 indiriliyor (~10 MB - python.org)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $PyUrl -OutFile $PyZip

    Write-Host "[1/3] Portable Python arsivi cikartiliyor..." -ForegroundColor Cyan
    Expand-Archive -Path $PyZip -DestinationPath $RuntimeDir -Force
    Remove-Item $PyZip -Force

    # python311._pth dosyasini pip ve yerel modulleri gorecek sekilde yapilandir
    $PthFile = Join-Path $RuntimeDir "python311._pth"
    $PthContent = @(
        "python311.zip",
        ".",
        "..",
        "Lib\site-packages",
        "import site"
    )
    Set-Content -Path $PthFile -Value $PthContent -Encoding Ascii
}

# 5. Pip Paket Yoneticisini Portable Python icine kur (pypa.io Resmi Sunucusu)
$PipExe = Join-Path $RuntimeDir "Scripts\pip.exe"
if (-not (Test-Path $PipExe)) {
    $GetPip = Join-Path $RuntimeDir "get-pip.py"
    Write-Host "[2/3] Resmi Pip paket yoneticisi indiriliyor (bootstrap.pypa.io)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
    & $RuntimePy $GetPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "Pip kurulumu basarisiz oldu (kod: $LASTEXITCODE)." }
    Remove-Item $GetPip -Force
}

# 6. Gerekli Kutuphaneleri (PyQt6, RapidOCR, CTranslate2 vb.) PyPI uzerinden indir
Write-Host "[3/3] Yapay zeka, OCR ve arayuz kutuphaneleri indiriliyor (PyPI)..." -ForegroundColor Cyan
& $RuntimePy -m pip install --prefer-binary -r (Join-Path $AppDir "requirements.txt") --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "Bagimlilik kurulumu basarisiz oldu (kod: $LASTEXITCODE). Internet baglantinizi kontrol edip tekrar deneyin."
}

New-Item -ItemType File -Force -Path $MarkerFile | Out-Null

Write-Host ""
Write-Host "[TAMAMLANDI] Kurulum basariyla bitti! SubVision AI aciliyor..." -ForegroundColor Green
Write-Host "(Not: 227 MB boyutundaki EN->TR ceviri modeli ilk acilista otomatik indirilecektir.)" -ForegroundColor Yellow
$LaunchBin = if (Test-Path $RuntimePyw) { $RuntimePyw } else { $RuntimePy }
Start-Process -FilePath $LaunchBin -ArgumentList "main.py" -WorkingDirectory $AppDir
