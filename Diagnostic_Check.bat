@echo off
:: DAC6 Environment Diagnostic Script
:: Run this to collect environment information

echo ================================================
echo DAC6 ENVIRONMENT DIAGNOSTIC
echo ================================================
echo.

echo Checking Python version...
python --version
echo.

echo Checking pip packages...
python -m pip list | findstr /i "torch numpy dac audiotools soundfile"
echo.

echo Checking CUDA availability...
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}'); print(f'PyTorch version: {torch.__version__}')"
echo.

echo Checking GPU info...
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv 2>nul || echo No NVIDIA GPU detected
echo.

echo Checking ffmpeg...
where ffmpeg 2>nul || echo ffmpeg not found in PATH
ffmpeg -version 2>nul | findstr /i "ffmpeg version"
echo.

echo Checking DAC model weights...
python -c "import os; cache=os.path.expanduser('~/.cache/descript/dac'); print(f'Cache dir: {cache}'); import os.path; print(f'Exists: {os.path.exists(cache)}'); import glob; print(f'Files: {len(glob.glob(cache + \"/**\", recursive=True))}')" 2>nul || echo DAC not installed
echo.

echo ================================================
echo DIAGNOSTIC COMPLETE
echo ================================================
echo.
echo Please share this output with the AI for analysis
pause
