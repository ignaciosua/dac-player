@echo off
setlocal EnableDelayedExpansion
title DAC6 Audio Compressor - Setup

cls
echo.
echo  ==========================================
echo    DAC6 Audio Compressor  -  Setup
echo  ==========================================
echo.
echo  First-time setup downloads approx 1.1 GB:
echo    - PyTorch CUDA  (~700 MB)
echo    - DAC neural codec model  (~293 MB)
echo    - ffmpeg  (~80 MB, required for MP3/AAC/M4A/Opus)
echo.
echo  Re-running this file is safe.
echo  Already completed steps are skipped.
echo.
pause

:: ── paths ──────────────────────────────────────────────────────────────────
set "DIR=%~dp0"
set "VENV=%DIR%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PYTHONW=%VENV%\Scripts\pythonw.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "MODEL=%USERPROFILE%\.cache\descript\dac\weights_44khz_8kbps_0.0.1.pth"
set "FFMPEG=%DIR%bin\ffmpeg.exe"

:: ─────────────────────────────────────────────────────────────────────────
:: STEP 1 — Python
:: ─────────────────────────────────────────────────────────────────────────
echo.
echo [1/6] Checking Python...
python --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PV=%%v
    echo       Found Python !PV!
    goto :step2
)

echo       Python not found. Downloading Python 3.11.9 (~25 MB)...
powershell -NoProfile -Command ^
  "Invoke-WebRequest 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\py_setup.exe' -UseBasicParsing"
if errorlevel 1 (
    echo.
    echo  ERROR: Could not download Python installer.
    echo  Make sure you have internet access and try again.
    pause & exit /b 1
)
echo       Installing Python 3.11.9...
"%TEMP%\py_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_tcltk=1
del "%TEMP%\py_setup.exe" 2>nul
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
echo       Python 3.11.9 installed.

:: ─────────────────────────────────────────────────────────────────────────
:: STEP 2 — Virtual environment
:: ─────────────────────────────────────────────────────────────────────────
:step2
echo.
if exist "%PYTHON%" (
    echo [2/6] Virtual environment already exists — skipping.
    goto :step3
)
echo [2/6] Creating virtual environment...
python -m venv "%VENV%" --prompt DAC6
if errorlevel 1 (
    echo.
    echo  ERROR: Could not create virtual environment.
    echo  Try running this file as Administrator.
    pause & exit /b 1
)
"%PIP%" install --upgrade pip wheel --quiet --disable-pip-version-check
echo       Done.

:: ─────────────────────────────────────────────────────────────────────────
:: STEP 3 — PyTorch CUDA
:: ─────────────────────────────────────────────────────────────────────────
:step3
echo.
"%PYTHON%" -c "import torch" >nul 2>&1
if not errorlevel 1 (
    echo [3/6] PyTorch already installed — skipping.
    goto :step4
)
echo [3/6] Installing PyTorch CUDA  (~700 MB, this will take a few minutes)...
"%PIP%" install torch torchvision torchaudio ^
  --index-url https://download.pytorch.org/whl/cu121 ^
  --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  ERROR: PyTorch installation failed.
    echo  Check your internet connection.
    echo  You can safely run this file again — this step will be retried.
    pause & exit /b 1
)
echo       PyTorch installed.

:: ─────────────────────────────────────────────────────────────────────────
:: STEP 4 — DAC and other Python dependencies
:: ─────────────────────────────────────────────────────────────────────────
:step4
echo.
"%PYTHON%" -c "import dac" >nul 2>&1
if not errorlevel 1 (
    echo [4/6] DAC dependencies already installed — skipping.
    goto :fix_numpy
)
echo [4/6] Installing DAC and other dependencies...
"%PIP%" install ^
  descript-audio-codec descript-audiotools ^
  soundfile sounddevice ^
  customtkinter tkinterdnd2 ^
  --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  ERROR: Dependency installation failed. See the error above.
    echo  You can safely run this file again — completed steps are skipped.
    pause & exit /b 1
)
echo       Dependencies installed.

:: Pin numpy<2 — runs on every setup run to catch regressions.
:: descript-audiotools can pull in numpy 2.x which causes a DLL crash on Windows.
:fix_numpy
echo.
echo       Pinning numpy 1.x (Windows DLL compatibility)...
"%PIP%" install "numpy<2" --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  ERROR: Could not pin numpy version.
    pause & exit /b 1
)
echo       numpy OK.

:: ─────────────────────────────────────────────────────────────────────────
:: STEP 5 — ffmpeg  (required for MP3, AAC, M4A, Opus)
:: ─────────────────────────────────────────────────────────────────────────
:step5
echo.

:: Already installed locally?
if exist "%FFMPEG%" (
    echo [5/6] ffmpeg already present — skipping.
    goto :step6
)

:: Already on system PATH?
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo [5/6] ffmpeg found in system PATH — skipping local download.
    goto :step6
)

echo [5/6] Installing ffmpeg  (~80 MB, required for MP3/AAC/M4A/Opus)...

:: Try winget first (silent, fastest on Windows 10/11 with App Installer)
winget --version >nul 2>&1
if not errorlevel 1 (
    echo       Trying winget...
    winget install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    where ffmpeg >nul 2>&1
    if not errorlevel 1 (
        echo       ffmpeg installed via winget.
        goto :step6
    )
)

:: Fall back: download static build from gyan.dev (single exe, no DLLs needed)
echo       Downloading ffmpeg static build from gyan.dev...
mkdir "%DIR%bin" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%TEMP%\ffmpeg.zip' -UseBasicParsing; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo  ERROR: Could not download ffmpeg.
    echo  Check your internet connection and run this file again.
    pause & exit /b 1
)

echo       Extracting ffmpeg...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%TEMP%\ffmpeg.zip', '%TEMP%\ffmpeg_extract'); exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo  ERROR: Could not extract ffmpeg zip.
    echo  Run this file again.
    del "%TEMP%\ffmpeg.zip" 2>nul
    pause & exit /b 1
)
del "%TEMP%\ffmpeg.zip" 2>nul

:: Copy executables (static build — only .exe files needed, no DLLs)
for /r "%TEMP%\ffmpeg_extract" %%f in (ffmpeg.exe)  do copy /y "%%f" "%DIR%bin\ffmpeg.exe"  >nul
for /r "%TEMP%\ffmpeg_extract" %%f in (ffprobe.exe) do copy /y "%%f" "%DIR%bin\ffprobe.exe" >nul
rmdir /s /q "%TEMP%\ffmpeg_extract" 2>nul

if not exist "%FFMPEG%" (
    echo.
    echo  ERROR: ffmpeg extraction succeeded but ffmpeg.exe was not found.
    echo  Run this file again.
    pause & exit /b 1
)
echo       ffmpeg installed to %DIR%bin\

:: ─────────────────────────────────────────────────────────────────────────
:: STEP 6 — DAC model weights
:: ─────────────────────────────────────────────────────────────────────────
:step6
echo.
if exist "%MODEL%" (
    echo [6/6] DAC model already cached — skipping.
    goto :shortcuts
)
echo [6/6] Downloading DAC 44 kHz model  (~293 MB)...
echo       Source: github.com/descriptinc/descript-audio-codec/releases
"%PYTHON%" -c "import dac; dac.utils.download(model_type='44khz')"
if errorlevel 1 (
    echo.
    echo  ERROR: Could not download the DAC model.
    echo  Check your internet connection and run this file again.
    pause & exit /b 1
)
echo       Model downloaded.

:: ─────────────────────────────────────────────────────────────────────────
:: Shortcuts
:: ─────────────────────────────────────────────────────────────────────────
:shortcuts
echo.
echo       Creating Desktop shortcut...
set "LNK=%USERPROFILE%\Desktop\DAC6.lnk"
powershell -NoProfile -Command ^
  "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%LNK%'); $s.TargetPath='%PYTHONW:\=\\%'; $s.Arguments='\""%DIR:\=\\%dac6_gui.py\"'; $s.WorkingDirectory='%DIR:\=\\%'; $s.Description='DAC6 Audio Compressor'; $s.Save()"

echo.
echo  ==========================================
echo    Setup complete!
echo    Shortcut created on your Desktop.
echo  ==========================================
echo.
echo  Launching DAC6...

:: ─────────────────────────────────────────────────────────────────────────
:: Launch
:: ─────────────────────────────────────────────────────────────────────────
:launch
if not exist "%PYTHONW%" (
    echo.
    echo  ERROR: Installation incomplete. Run this file again.
    pause & exit /b 1
)
:: Prepend local bin/ so ffmpeg is found by the GUI and all worker subprocesses
set "PATH=%DIR%bin;%PATH%"
start "" "%PYTHONW%" "%DIR%dac6_gui.py"
exit /b 0
