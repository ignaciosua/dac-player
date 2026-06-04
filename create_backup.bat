@echo off
:: DAC6 Backup Creator - Descarga TODAS las dependencias
:: Ejecuta este script para crear un backup completo offline

setlocal EnableDelayedExpansion
title DAC6 - Creando Backup Completo

cls
echo.
echo  ==========================================
echo    DAC6 - BACKUP CREATOR
echo  ==========================================
echo.
echo  Este script descargara TODAS las dependencias
echo  necesarias para DAC6 (~3.5 GB total).
echo.
echo  Asegurate de tener:
echo    - Conexion a internet estable
echo    - 5 GB de espacio libre
echo    - Python y pip instalados
echo.
pause

set "DIR=%~dp0"
set "BACKUP=%DIR%backup"

:: Crear estructura de carpetas
echo.
echo [1/6] Creando estructura de carpetas...
mkdir "%BACKUP%\python" 2>nul
mkdir "%BACKUP%\pytorch" 2>nul
mkdir "%BACKUP%\dac" 2>nul
mkdir "%BACKUP%\ffmpeg" 2>nul
mkdir "%BACKUP%\pip_packages" 2>nul
mkdir "%BACKUP%\scripts" 2>nul
echo       Done.

:: 1. Python installer
echo.
echo [2/6] Descargando Python 3.11.9 installer (~25 MB)...
if exist "%BACKUP%\python\python-3.11.9-amd64.exe" (
    echo       Ya existe - skipping.
) else (
    powershell -NoProfile -Command "Invoke-WebRequest 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%BACKUP%\python\python-3.11.9-amd64.exe' -UseBasicParsing"
    if errorlevel 1 (
        echo       ERROR: No se pudo descargar Python installer.
        pause & exit /b 1
    )
    echo       Done.
)

:: 2. PyTorch wheels
echo.
echo [3/6] Descargando PyTorch wheels (~2.3 GB) - esto puede tardar...
pip --version >nul 2>&1
if errorlevel 1 (
    echo       ERROR: pip no esta instalado. Instala Python primero.
    pause & exit /b 1
)

if exist "%BACKUP%\pytorch\torch-*.whl" (
    echo       Wheels ya existen - skipping.
) else (
    pip download torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --python-version 3.11 --platform win_amd64 --only-binary :all: --dest "%BACKUP%\pytorch"
    if errorlevel 1 (
        echo       ERROR: No se pudo descargar PyTorch wheels.
        pause & exit /b 1
    )
    echo       Done.
)

:: 3. DAC model weights
echo.
echo [4/6] Copiando DAC model weights...
set "DAC_CACHE=%USERPROFILE%\.cache\descript\dac"
if exist "%DAC_CACHE%\*.pth" (
    copy /y "%DAC_CACHE%\*.pth" "%BACKUP%\dac\" >nul
    echo       Copiados desde cache local.
) else (
    echo       AVISO: No se encontraron weights en cache.
    echo       Ejecuta DAC6 al menos una vez para descargarlos.
    echo       Los weights se descargaran automaticamente al usar cada modelo.
)

:: 4. ffmpeg
echo.
echo [5/6] Descargando ffmpeg essentials (~80 MB)...
if exist "%BACKUP%\ffmpeg\ffmpeg-release-essentials.zip" (
    echo       Ya existe - skipping.
) else (
    powershell -NoProfile -Command "Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%BACKUP%\ffmpeg\ffmpeg-release-essentials.zip' -UseBasicParsing"
    if errorlevel 1 (
        echo       ERROR: No se pudo descargar ffmpeg.
        pause & exit /b 1
    )
    echo       Done.
)

:: 5. Pip packages
echo.
echo [6/6] Descargando pip packages (~200 MB)...
if exist "%BACKUP%\pip_packages\*.whl" (
    echo       Packages ya existen - skipping.
) else (
    pip download descript-audio-codec audiotools soundfile sounddevice customtkinter tkinterdnd2 "numpy<2" --dest "%BACKUP%\pip_packages"
    if errorlevel 1 (
        echo       ERROR: No se pudo descargar pip packages.
        pause & exit /b 1
    )
    echo       Done.
)

:: Crear script de instalacion offline
echo.
echo Creando script de instalacion offline...
call :create_install_script
echo       Done.

:: Resumen
echo.
echo  ==========================================
echo    BACKUP COMPLETO
echo  ==========================================
echo.
dir /s /b "%BACKUP%\*.exe" "%BACKUP%\*.whl" "%BACKUP%\*.zip" "%BACKUP%\*.pth" 2>nul | find /c /v "" > "%TEMP%\count.txt"
set /p FILE_COUNT=<"%TEMP%\count.txt"
del "%TEMP%\count.txt"

echo  Archivos descargados: !FILE_COUNT!
echo  Ubicacion: %BACKUP%
echo.
echo  Para usar el backup:
echo    1. Copia la carpeta backup\ a otra computadora
echo    2. Ejecuta: backup\scripts\install_offline.bat
echo.
echo  Para hostear en servidor:
echo    1. Sube el contenido de backup\ a tu servidor web
echo    2. Modifica las URLs en DAC6_Setup.bat
echo.
pause
exit /b 0

:create_install_script
(
echo @echo off
echo :: DAC6 - Instalacion Offline desde Backup
echo setlocal EnableDelayedExpansion
echo title DAC6 - Instalacion Offline
echo.
echo cls
echo echo.
echo echo  ==========================================
echo echo    DAC6 - INSTALACION OFFLINE
echo echo  ==========================================
echo echo.
echo pause
echo.
echo set "BACKUP=%%~dp0.."
echo set "DIR=%%BACKUP%%\..\.."
echo set "VENV=%%DIR%%\.venv"
echo.
echo :: 1. Python
echo echo.
echo echo [1/5] Instalando Python 3.11.9...
echo if exist "%%BACKUP%%\python\python-3.11.9-amd64.exe" ^(
echo     "%%BACKUP%%\python\python-3.11.9-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1
echo     echo       Done.
echo ^) else ^(
echo     echo       ERROR: python-3.11.9-amd64.exe no encontrado.
echo     pause ^& exit /b 1
echo ^)
echo.
echo :: 2. Venv
echo echo.
echo echo [2/5] Creando virtual environment...
echo python -m venv "%%VENV%%" --prompt DAC6
echo "%%VENV%%\Scripts\pip.exe" install --upgrade pip wheel --quiet
echo echo       Done.
echo.
echo :: 3. PyTorch
echo echo.
echo echo [3/5] Instalando PyTorch desde backup...
echo "%%VENV%%\Scripts\pip.exe" install --no-index --find-links="%%BACKUP%%\pytorch" torch torchvision torchaudio
echo echo       Done.
echo.
echo :: 4. Pip packages
echo echo.
echo echo [4/5] Instalando dependencias desde backup...
echo "%%VENV%%\Scripts\pip.exe" install --no-index --find-links="%%BACKUP%%\pip_packages" descript-audio-codec audiotools soundfile sounddevice customtkinter tkinterdnd2 "numpy<2"
echo echo       Done.
echo.
echo :: 5. ffmpeg
echo echo.
echo echo [5/5] Instalando ffmpeg...
echo mkdir "%%DIR%%\bin" 2^>nul
echo powershell -NoProfile -Command "Add-Type -A System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory('%%BACKUP%%\ffmpeg\ffmpeg-release-essentials.zip', '%%TEMP%%\ffmpeg_extract'^)"
echo for /r "%%TEMP%%\ffmpeg_extract" %%%%f in ^(ffmpeg.exe^)  do copy /y "%%%%f" "%%DIR%%\bin\ffmpeg.exe"  ^>nul
echo for /r "%%TEMP%%\ffmpeg_extract" %%%%f in ^(ffprobe.exe^) do copy /y "%%%%f" "%%DIR%%\bin\ffprobe.exe" ^>nul
echo rmdir /s /q "%%TEMP%%\ffmpeg_extract" 2^>nul
echo echo       Done.
echo.
echo :: 6. DAC weights
echo echo.
echo echo Copiando DAC model weights...
echo set "DAC_CACHE=%%USERPROFILE%%\.cache\descript\dac"
echo mkdir "%%DAC_CACHE%%" 2^>nul
echo if exist "%%BACKUP%%\dac\*.pth" ^(
echo     copy /y "%%BACKUP%%\dac\*.pth" "%%DAC_CACHE%%\" ^>nul
echo     echo       Done.
echo ^) else ^(
echo     echo       No weights in backup - will download on first use.
echo ^)
echo.
echo echo.
echo echo  ==========================================
echo echo    INSTALACION COMPLETA
echo echo  ==========================================
echo echo.
echo echo  Ejecuta DAC6_Setup.bat para iniciar la GUI.
echo echo.
echo pause
) > "%BACKUP%\scripts\install_offline.bat"
exit /b 0
