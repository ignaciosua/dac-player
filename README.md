# DAC6 Audio Compressor

**Neural audio compression GUI using Descript Audio Codec (DAC). GPU-accelerated batch processing for music and speech compression with transparent quality at ultra-low bitrates (32-128 kbps). Python-based tool with A/B quality testing and built-in player.**

---

## 🎯 Features

- **🗜️ COMPRESS** - Batch neural audio compression (9-21 kbps for music, ultra-low bitrates)
- **📂 RESTORE** - Decompress `.ncmp` files to WAV/FLAC/MP3
- **🔍 A/B TEST** - Side-by-side quality comparison with synchronized playback
- **🎵 PLAYER** - Built-in music player with playlist support, shuffle, and loop modes
- **⚡ GPU Acceleration** - Fast processing with NVIDIA CUDA support
- **📦 Batch Processing** - Drag & drop multiple files, process entire folders
- **🎚️ Configurable Quality** - Choose codebooks (6-16) for size vs quality balance
- **🔊 HQ Resampling** - Automatic 44.1kHz resampling with high-quality filters

---

## 📸 Screenshots

### Main Interface - Compress Tab
The neural audio compressor with batch file processing and configurable quality settings.

### A/B Test Tab
Compare original vs compressed audio with synchronized dual-player interface.

### Built-in Player
Full-featured music player with waveform visualization and playlist management.

---

## 🚀 Quick Start

### Windows Installation

1. **Download** the repository
2. **Run** `DAC6_Setup.bat` (one-click installer)
3. Wait for dependencies to download (~1.1 GB)
4. The GUI will launch automatically

### Manual Installation

```bash
# Clone repository
git clone https://github.com/yourusername/dac6-audio-compressor.git
cd dac6-audio-compressor

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install descript-audio-codec audiotools customtkinter sounddevice

# Run GUI
python dac6_gui.py
```

---

## 💻 Usage

### GUI Mode (Recommended)

1. **Launch** the application via `DAC6_Setup.bat` or `python dac6_gui.py`
2. **Select** the COMPRESS tab
3. **Drag & drop** audio files (MP3, WAV, FLAC, AAC, OGG, M4A, Opus)
4. **Configure** settings:
   - **Codebooks**: 9 (default), 6 (smallest), 16 (highest quality)
   - **Chunk Size**: 60s (default), 120-300s (faster, more VRAM)
5. **Click** "PROCESS ALL"
6. **Test quality** in the A/B TEST tab
7. **Play** compressed files in the PLAYER tab

### Command Line Interface

```bash
# Compress audio file
python dac6.py encode input.mp3 --n-codebooks 9 --chunk-size 60

# Restore compressed file
python dac6.py decode input.dac9cb.ncmp

# Play compressed file
python dac6.py play input.dac9cb.ncmp

# Show file info
python dac6.py info input.dac9cb.ncmp
```

---

## ⚙️ Configuration

### Codebooks (Quality vs Size)

| Codebooks | Bitrate | Use Case |
|-----------|---------|----------|
| 6 | ~9 kbps | Minimum size, voice/podcasts |
| 9 | ~12 kbps | **Default**, excellent quality/size balance |
| 12 | ~16 kbps | High quality music |
| 16 | ~21 kbps | Maximum quality, near-transparent |

### Chunk Size (Speed vs VRAM)

| Chunk Size | VRAM Required | Processing Speed |
|------------|---------------|------------------|
| 30-60s | 4 GB | Standard |
| 120-180s | 6 GB | Fast |
| 250-300s | 8 GB+ | Maximum performance |

### Models

- **44.1 kHz** - Music, high-fidelity audio (default)
- **24 kHz** - Speech, podcasts
- **16 kHz** - Voice, low-bandwidth applications

---

## 🎛️ Advanced Features

### Batch Processing
- **Drag & drop** entire folders
- **Automatic queue** management
- **Progress tracking** per file
- **Error handling** with detailed logs

### Quality Testing
- **Synchronized playback** of original vs compressed
- **Waveform visualization** for both tracks
- **Independent volume** controls
- **Instant A/B switching**

### Music Player
- **Auto-decode** compressed files on demand
- **Playlist** with shuffle and loop modes
- **Waveform** with seek capability
- **Pre-decode** caching for instant playback

### Audio Processing
- **Automatic resampling** to target sample rate
- **500ms overlap** between chunks (eliminates artifacts)
- **Stereo processing** with independent channel encoding
- **HQ filters** (256-tap, 10 phase shifts)

---

## 📋 Requirements

### System Requirements
- **OS**: Windows 10/11, Linux, macOS
- **Python**: 3.11+
- **Disk Space**: 2-3 GB (models + dependencies)
- **RAM**: 4 GB minimum, 8 GB recommended
- **GPU**: NVIDIA GPU with CUDA support (optional, CPU fallback available)

### Dependencies
- PyTorch 2.0+
- descript-audio-codec
- audiotools
- customtkinter
- sounddevice
- ffmpeg (included in setup)

---

## 🔧 Troubleshooting

### Installation Issues

If setup fails, run the diagnostic tool:
```bash
Diagnostic_Check.bat
```

Check the output and review `DIAGNOSTIC_INFO.txt` for system compatibility.

### Common Problems

**"CUDA out of memory"**
- Reduce chunk size to 30-60s
- Close other GPU applications
- Use CPU mode (slower but works)

**"Module not found"**
- Ensure virtual environment is activated
- Re-run `DAC6_Setup.bat`

**"ffmpeg not found"**
- Run setup script to download ffmpeg
- Or manually place ffmpeg in `bin/` folder

### Logs

All operations are logged to `dac6.log` in the application directory.

---

## 🎓 How It Works

DAC6 uses the **Descript Audio Codec (DAC)**, a state-of-the-art neural audio compression model:

1. **Input**: Audio is resampled to 44.1 kHz (or 24/16 kHz)
2. **Encoding**: Neural network compresses audio to latent codes
3. **Quantization**: Codes are quantized using residual vector quantization (RVQ)
4. **Storage**: Compressed codes stored in `.ncmp` format
5. **Decoding**: Neural decoder reconstructs audio from codes

The codec achieves **perceptually transparent** quality at bitrates as low as 12 kbps by learning audio representations end-to-end.

---

## 📊 Benchmarks

### Compression Ratios

| Format | Bitrate | File Size (5 min) | Compression Ratio |
|--------|---------|-------------------|-------------------|
| WAV (uncompressed) | 1411 kbps | 52.9 MB | 1:1 |
| FLAC (lossless) | ~900 kbps | 33.8 MB | 1.6:1 |
| MP3 320 kbps | 320 kbps | 12.0 MB | 4.4:1 |
| MP3 128 kbps | 128 kbps | 4.8 MB | 11:1 |
| **DAC 16 codebooks** | **21 kbps** | **0.8 MB** | **66:1** |
| **DAC 9 codebooks** | **12 kbps** | **0.45 MB** | **118:1** |

### Processing Speed (NVIDIA RTX 3060)

- **Encoding**: ~60x realtime (9 codebooks, 60s chunks)
- **Decoding**: ~100x realtime
- **Batch**: 100 files (5 min each) in ~5 minutes

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

### Development Setup

```bash
git clone https://github.com/yourusername/dac6-audio-compressor.git
cd dac6-audio-compressor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## 🙏 Credits

- **DAC Neural Codec**: [Descript Inc.](https://github.com/descriptinc/descript-audio-codec)
- **PyTorch**: [Meta AI](https://pytorch.org/)
- **CustomTkinter**: [Tom Schimansky](https://github.com/TomSchimansky/CustomTkinter)
- **ffmpeg**: [FFmpeg Team](https://ffmpeg.org/)

---

## 📚 Related Projects

- [Descript Audio Codec](https://github.com/descriptinc/descript-audio-codec) - Official DAC implementation
- [EnCodec](https://github.com/facebookresearch/encodec) - Meta's neural audio codec
- [SoundStream](https://github.com/wesbz/SoundStream) - Google's neural audio codec

---

## 🔗 Links

- **Documentation**: [Wiki](https://github.com/yourusername/dac6-audio-compressor/wiki)
- **Issues**: [Bug Reports](https://github.com/yourusername/dac6-audio-compressor/issues)
- **Discussions**: [Community](https://github.com/yourusername/dac6-audio-compressor/discussions)

---

## ⭐ Star History

If you find this project useful, please consider giving it a star!

---

**Keywords**: neural audio compression, DAC codec, GPU audio processing, batch audio compressor, transparent compression, ultra-low bitrate, Python audio tools, music compression, speech compression, AI audio codec, perceptual audio coding
