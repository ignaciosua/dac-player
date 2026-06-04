===============================================
  DAC6 AUDIO COMPRESSOR - ESTRUCTURA DEL PROYECTO
===============================================

Este workspace contiene TODO lo necesario para DAC6:
- Código fuente
- Instalador
- Sistema de backup
- Documentación

===============================================
  ARCHIVOS PRINCIPALES
===============================================

DAC6_Setup.bat          Instalador principal (ejecuta esto primero)
dac6_gui.py             Interfaz gráfica (58 KB)
dac6_worker.py          Worker subprocess (17 KB)
dac6.py                 CLI version (15 KB)

README.txt              Instrucciones de uso
dac6.log                Log de ejecución (se crea automáticamente)

===============================================
  SISTEMA DE BACKUP
===============================================

backup/                 Carpeta para dependencias offline
├── BACKUP_README.txt   Guía del sistema de backup
├── HOW_TO_HOST.txt     Cómo hostear en tu propio servidor
├── INDEX.txt           Checklist de archivos
├── .gitignore          Archivos a ignorar en git
│
├── python/             Python installer (~25 MB)
├── pytorch/            PyTorch wheels (~2.3 GB)
├── dac/                DAC model weights (~880 MB)
├── ffmpeg/             ffmpeg executable (~80 MB)
├── pip_packages/       Pip dependencies (~200 MB)
└── scripts/            Scripts de instalación offline

create_backup.bat       Crea el backup completo (~3.5 GB)

===============================================
  PAQUETE DE DISTRIBUCION
===============================================

DAC6_Package.zip        Paquete listo para distribuir (27 KB)
Contiene:
- dac6_gui.py
- dac6_worker.py
- dac6.py
- DAC6_Setup.bat
- README.txt
- DIAGNOSTIC_INFO.txt
- Diagnostic_Check.bat

===============================================
  DIAGNOSTICO
===============================================

DIAGNOSTIC_INFO.txt     Información de diagnóstico
Diagnostic_Check.bat    Script de verificación del ambiente

===============================================
  COMO USAR ESTE PROYECTO
===============================================

OPCION 1: Instalación Normal (requiere internet)
-------------------------------------------------
1. Ejecuta: DAC6_Setup.bat
2. Espera que descargue ~1.1 GB
3. La GUI se abrirá automáticamente

OPCION 2: Crear Backup para Uso Offline
----------------------------------------
1. Ejecuta: create_backup.bat
2. Espera que descargue ~3.5 GB
3. Guarda la carpeta backup/ para uso futuro
4. En otra PC: ejecuta backup/scripts/install_offline.bat

OPCION 3: Hostear en Servidor Propio
-------------------------------------
1. Ejecuta: create_backup.bat
2. Sube backup/ a tu servidor web
3. Modifica URLs en DAC6_Setup.bat (ver HOW_TO_HOST.txt)
4. Distribuye tu versión modificada

===============================================
  ESTRUCTURA GENERADA DESPUÉS DE INSTALACIÓN
===============================================

Después de ejecutar DAC6_Setup.bat, se crean:

.venv/                  Virtual environment Python
├── Scripts/
│   ├── python.exe
│   ├── pythonw.exe
│   └── pip.exe
└── Lib/
    └── site-packages/  Todas las dependencias instaladas

bin/                    ffmpeg binaries
├── ffmpeg.exe
└── ffprobe.exe

out/                    Archivos encodificados (.ncmp)
└── decoded/            Archivos decodificados para comparación

%USERPROFILE%\.cache\descript\dac\
└── weights_*.pth       Model weights descargados

dac6.log                Log de operaciones

===============================================
  TAMAÑOS DE ARCHIVOS
===============================================

WORKSPACE INICIAL:
DAC6_Package.zip:       27 KB
Código fuente:          ~90 KB
Documentación:          ~20 KB

DESPUÉS DE INSTALACIÓN:
.venv/:                 ~3 GB
bin/:                   ~80 MB
Model weights:          ~293 MB por modelo

BACKUP COMPLETO:
backup/:                ~3.5 GB

===============================================
  PARA DESARROLLADORES
===============================================

Si quieres modificar el código:

1. Edita dac6_gui.py / dac6_worker.py / dac6.py
2. Prueba ejecutando: .venv\Scripts\pythonw.exe dac6_gui.py
3. Verifica errores en dac6.log
4. Empaqueta: powershell -Command "Compress-Archive -Path ..."

Archivos clave:
- dac6_gui.py líneas 158-198: encode_ch con overlap
- dac6_worker.py líneas 305-355: decode con overlap
- DAC6_Setup.bat líneas 140-200: descarga de ffmpeg

===============================================
  PARA DISTRIBUIR
===============================================

DISTRIBUCIÓN BÁSICA (usuarios con internet):
- Comparte DAC6_Package.zip (27 KB)
- Los usuarios ejecutan DAC6_Setup.bat
- Todo se descarga automáticamente

DISTRIBUCIÓN OFFLINE (usuarios sin internet):
- Ejecuta create_backup.bat
- Comparte la carpeta backup/ completa (~3.5 GB)
- Los usuarios ejecutan backup/scripts/install_offline.bat

DISTRIBUCIÓN CON SERVIDOR PROPIO:
- Sigue guía en backup/HOW_TO_HOST.txt

===============================================
  TROUBLESHOOTING
===============================================

PROBLEMA: Setup falla al descargar Python
SOLUCIÓN: Ejecuta create_backup.bat y usa instalación offline

PROBLEMA: PyTorch no encuentra CUDA
SOLUCIÓN: Instala drivers NVIDIA actualizados

PROBLEMA: ffmpeg no se encuentra
SOLUCIÓN: Verifica que bin/ffmpeg.exe exista

PROBLEMA: Artefactos en el audio
SOLUCIÓN: Aumenta chunk size, verifica que overlap esté habilitado

Para más ayuda:
- Ejecuta: Diagnostic_Check.bat
- Revisa: dac6.log
- Lee: DIAGNOSTIC_INFO.txt

===============================================
  LICENCIAS
===============================================

DAC6:
- Código GUI y setup: MIT License
- descript-audio-codec: MIT License (Descript Inc.)
- PyTorch: BSD License (Meta AI)
- ffmpeg: GPL v3
- customtkinter: MIT License

===============================================
  CHANGELOG
===============================================

v1.0 (Junio 2026):
- Sistema de overlap de 500ms entre chunks
- Resample automático con alta calidad
- Chunk size configurable 10-300s
- Codebooks configurables 3-16
- Instalador automático completo
- Sistema de backup offline
- Eliminado Low VRAM mode (causaba artefactos)

===============================================
  CREDITOS
===============================================

DAC Neural Codec: Descript Inc.
PyTorch: Meta AI
ffmpeg: FFmpeg Project
GUI Framework: CustomTkinter
Setup & Integration: DAC6 Project

===============================================
  CONTACTO
===============================================

Para preguntas, bugs o contribuciones:
[Añade tu información de contacto aquí]

GitHub: [Añade tu repo aquí]
