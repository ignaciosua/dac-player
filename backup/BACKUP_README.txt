===============================================
  DAC6 - BACKUP DE DEPENDENCIAS
===============================================

Este folder contiene (o debe contener) TODAS las dependencias
necesarias para que DAC6 funcione sin acceso a internet.

Si los servidores originales caen, puedes hostear estos archivos
en tu propio servidor y modificar DAC6_Setup.bat para que descargue
desde tus URLs.

===============================================
  ESTRUCTURA DEL BACKUP
===============================================

backup/
├── python/
│   └── python-3.11.9-amd64.exe (~25 MB)
│       URL: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
│
├── pytorch/
│   ├── torch-2.5.1+cu121-cp311-cp311-win_amd64.whl (~2.3 GB)
│   ├── torchvision-0.20.1+cu121-cp311-cp311-win_amd64.whl (~5 MB)
│   └── torchaudio-2.5.1+cu121-cp311-cp311-win_amd64.whl (~3 MB)
│       URL base: https://download.pytorch.org/whl/cu121
│       Comando para descargar:
│       pip download torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --python-version 3.11 --platform win_amd64 --only-binary :all:
│
├── dac/
│   ├── weights_44khz_8kbps_0.0.1.pth (~293 MB)
│   ├── weights_24khz_0.0.1.pth (~293 MB)
│   └── weights_16khz_0.0.1.pth (~293 MB)
│       Estos se descargan automáticamente la primera vez que se ejecuta DAC
│       Se encuentran en: %USERPROFILE%\.cache\descript\dac\
│
├── ffmpeg/
│   └── ffmpeg-release-essentials.zip (~80 MB)
│       URL: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
│       Alternativa: https://github.com/GyanD/codexffmpeg/releases/latest
│
├── pip_packages/
│   └── [wheels de todas las dependencias]
│       Comando para descargar TODAS las dependencias:
│       pip download descript-audio-codec audiotools soundfile sounddevice customtkinter tkinterdnd2 --dest pip_packages
│
└── BACKUP_README.txt (este archivo)

===============================================
  COMO USAR EL BACKUP
===============================================

OPCION 1: Instalación completamente offline
--------------------------------------------
1. Copia toda la carpeta backup/ a la máquina sin internet
2. Ejecuta: backup/scripts/install_offline.bat
   (script incluido que instala todo desde archivos locales)

OPCION 2: Hostear en tu propio servidor
----------------------------------------
1. Sube el contenido de backup/ a tu servidor web
2. Modifica DAC6_Setup.bat:
   - Línea ~45: Cambia URL de Python a tu servidor
   - Línea ~95: Cambia index-url de PyTorch a tu servidor
   - Línea ~165: Cambia URL de ffmpeg a tu servidor
3. Distribuye el DAC6_Setup.bat modificado

===============================================
  COMANDOS PARA CREAR EL BACKUP COMPLETO
===============================================

# Crear estructura de carpetas
mkdir backup\python backup\pytorch backup\dac backup\ffmpeg backup\pip_packages

# 1. Descargar Python installer
powershell -Command "Invoke-WebRequest 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile 'backup\python\python-3.11.9-amd64.exe'"

# 2. Descargar PyTorch wheels (requiere pip)
pip download torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --python-version 3.11 --platform win_amd64 --only-binary :all: --dest backup\pytorch

# 3. Copiar DAC model weights (después de ejecutar DAC6 por primera vez)
copy "%USERPROFILE%\.cache\descript\dac\*.pth" backup\dac\

# 4. Descargar ffmpeg
powershell -Command "Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'backup\ffmpeg\ffmpeg-release-essentials.zip'"

# 5. Descargar todas las dependencias pip
pip download descript-audio-codec audiotools soundfile sounddevice customtkinter tkinterdnd2 numpy --dest backup\pip_packages

===============================================
  TAMAÑO TOTAL ESTIMADO
===============================================

Python:          ~25 MB
PyTorch:         ~2.3 GB
DAC weights:     ~880 MB (3 modelos)
ffmpeg:          ~80 MB
Pip packages:    ~200 MB
-----------------------------------
TOTAL:           ~3.5 GB

===============================================
  VERIFICACION DE INTEGRIDAD
===============================================

Después de crear el backup, verifica:

[ ] python-3.11.9-amd64.exe existe y es ~25 MB
[ ] torch wheel existe y es ~2.3 GB
[ ] Al menos 1 archivo .pth en dac/ (~293 MB)
[ ] ffmpeg-release-essentials.zip existe y es ~80 MB
[ ] pip_packages/ contiene múltiples .whl

===============================================
  SCRIPT DE INSTALACION OFFLINE
===============================================

Ver: backup/scripts/install_offline.bat
(archivo separado que instala todo desde archivos locales)

===============================================
  NOTAS IMPORTANTES
===============================================

- Los archivos .whl de PyTorch son específicos para:
  * Python 3.11
  * Windows 64-bit
  * CUDA 12.1
  
- Si necesitas otra configuración, modifica los comandos
  de descarga en consecuencia.

- DAC model weights se descargan automáticamente la primera
  vez que se usa cada modelo. Ejecuta DAC6 al menos una vez
  antes de hacer backup.

- Guarda este backup en un lugar seguro (disco externo,
  nube, servidor propio).

===============================================
  ACTUALIZACION DEL BACKUP
===============================================

Revisa cada 6 meses si hay nuevas versiones:
- PyTorch: https://pytorch.org/get-started/locally/
- DAC: https://github.com/descriptinc/descript-audio-codec
- ffmpeg: https://www.gyan.dev/ffmpeg/builds/

Versión actual de este backup:
- Python: 3.11.9
- PyTorch: 2.5.1+cu121
- DAC: 1.0.0
- ffmpeg: essentials build (última versión)
- Fecha: Junio 2026
