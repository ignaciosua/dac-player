===============================================
  DAC6 AUDIO COMPRESSOR
===============================================

NEURAL AUDIO CODEC - ULTRA HIGH COMPRESSION
Comprimes audio a 4-42 kbps con calidad perceptual
(bitrate depende del modelo y codebooks)

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
- Selecciona Modelo (44khz/24khz/16khz)
- Ajusta Codebooks segun modelo:
  * 44khz: 3-9 codebooks
  * 24khz: 3-32 codebooks  
  * 16khz: 3-12 codebooks
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

MODELOS:
- 44khz (max 9 cb)  = Musica, alta fidelidad
- 24khz (max 32 cb) = Voz, podcasts, maxima calidad
- 16khz (max 12 cb) = Telefonia, bajo ancho de banda

CODEBOOKS - Modelo 44khz (calidad vs tamaño):
- 3 codebooks = ~8 kbps  (ultra bajo bitrate)
- 6 codebooks = ~14 kbps (tamaño reducido)
- 9 codebooks = ~24 kbps (default, excelente balance)

CODEBOOKS - Modelo 24khz (opciones adicionales):
- 16 codebooks = ~42 kbps (muy alta calidad)
- 24 codebooks = ~64 kbps (casi transparente)
- 32 codebooks = ~84 kbps (maxima calidad)

(Bitrates mostrados son para estereo)

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
