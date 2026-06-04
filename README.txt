===============================================
  DAC6 AUDIO COMPRESSOR
===============================================

NEURAL AUDIO CODEC - ULTRA HIGH COMPRESSION
Comprimes audio a 9-21 kbps con calidad perceptual

===============================================
  INSTALACION
===============================================

1. Extrae todos los archivos a una carpeta
2. Ejecuta: DAC6_Setup.bat
3. Espera que descargue todo (~1.1 GB)
4. Al terminar, la GUI se abrira automaticamente

REQUISITOS:
- Windows 10/11
- 2 GB espacio en disco
- Conexion a internet (solo primera vez)
- GPU NVIDIA recomendada (funciona sin GPU pero mas lento)

===============================================
  USO
===============================================

MODO GUI:
- Ejecuta DAC6_Setup.bat para abrir la interfaz
- Arrastra archivos MP3/WAV/FLAC
- Ajusta Codebooks (9 = default, 16 = maxima calidad)
- Ajusta Chunk Size (60s = default)
- Click "ENCODE ALL"

MODO CONSOLA:
python dac6.py encode archivo.mp3 --n-codebooks 9
python dac6.py decode archivo.dac9cb.ncmp
python dac6.py play archivo.dac9cb.ncmp
python dac6.py info archivo.dac9cb.ncmp

===============================================
  CONFIGURACION
===============================================

CODEBOOKS (calidad vs tamaño):
- 6 codebooks  = ~9 kbps  (tamaño minimo)
- 9 codebooks  = ~12 kbps (default, buen balance)
- 16 codebooks = ~21 kbps (maxima calidad)

CHUNK SIZE (velocidad vs memoria GPU):
- 30-60s  = seguro para GPUs con 4GB VRAM
- 120-180s = mas rapido, requiere 6GB+ VRAM
- 250-300s = maximo rendimiento, 8GB+ VRAM

CARACTERISTICAS:
- Resample automatico a 44.1kHz con filtros HQ
- Overlap de 500ms entre chunks (sin artefactos)
- Soporte MP3, WAV, FLAC, M4A, AAC, Opus
- Procesamiento estereo independiente
- Export a MP3 desde GUI

===============================================
  DIAGNOSTICO
===============================================

Si tienes problemas:
1. Ejecuta: Diagnostic_Check.bat
2. Comparte el output con soporte
3. Revisa: DIAGNOSTIC_INFO.txt

LOG FILE: dac6.log (en la carpeta del programa)

===============================================
  CREDITOS
===============================================

DAC Neural Codec: Descript Inc.
GUI & Setup: DAC6 Project
PyTorch: Meta AI
ffmpeg: FFmpeg team

Licencia: MIT
