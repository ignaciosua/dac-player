#!/usr/bin/env python3
"""
Worker subprocess: runs DAC encode/decode, prints JSON lines to stdout.

Protocol lines:
  {"type": "info",     "duration": float, "channels": int, "sample_rate": int, "n_codebooks": int}
  {"type": "progress", "value": int}          # 0-100
  {"type": "status",   "message": str}
  {"type": "done",     "path": str, ...}
  {"type": "error",    "message": str}
"""
from __future__ import annotations
import argparse
import gzip
import json
import os
import shutil
import struct
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Ensure local bin/ (ffmpeg) is in PATH — needed for MP3/AAC/M4A/Opus support
_BIN_DIR = Path(__file__).parent / "bin"
if _BIN_DIR.is_dir():
    os.environ["PATH"] = str(_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

# Log file — GUI reads non-JSON lines from stdout and appends to this file,
# but the worker also writes its own diagnostics to stderr which the GUI captures.
_LOG = Path(__file__).parent / "dac6.log"


def _check_ffmpeg() -> bool:
    """Return True if ffmpeg is reachable on PATH."""
    return shutil.which("ffmpeg") is not None


_NEEDS_FFMPEG = {".mp3", ".aac", ".m4a", ".opus", ".ogg", ".wma"}

MAGIC   = b"NCMP"
VERSION = 3


def emit(obj: dict):
    print(json.dumps(obj), flush=True)


def emit_progress(value: int):
    emit({"type": "progress", "value": int(value)})


def emit_status(msg: str):
    emit({"type": "status", "message": msg})


# ── encode ────────────────────────────────────────────────────────────────────

def run_encode(args):
    import numpy as np
    import torch

    try:
        import dac
        from audiotools import AudioSignal
    except ImportError as e:
        emit({"type": "error", "message": f"Missing dependency: {e}"})
        return

    input_path = Path(args.input)
    if not input_path.exists():
        emit({"type": "error", "message": f"File not found: {input_path}"})
        return

    # Check ffmpeg availability before attempting to read audio that needs it
    if input_path.suffix.lower() in _NEEDS_FFMPEG and not _check_ffmpeg():
        emit({"type": "error", "message": (
            f"ffmpeg is required to read {input_path.suffix.upper()} files but was not found. "
            f"PATH searched: {os.environ.get('PATH', '(empty)')}. "
            "Run DAC6_Setup.bat again — it will install ffmpeg automatically."
        )})
        return

    print(f"[worker] ffmpeg={'found' if _check_ffmpeg() else 'NOT FOUND'}  "
          f"PATH={os.environ.get('PATH','')[:200]}", file=sys.stderr, flush=True)

    def choose_device(req):
        if req == "cpu":   return torch.device("cpu")
        if req == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but not available")
            return torch.device("cuda")
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")

    emit_status("Loading DAC model...")
    emit_progress(5)
    device = choose_device(args.device)
    model_path = dac.utils.download(model_type=args.model)
    model = dac.DAC.load(model_path).to(device).eval()
    n_q = min(int(args.n_codebooks), int(model.n_codebooks))

    emit_status("Reading audio...")
    emit_progress(12)
    try:
        sig = AudioSignal(str(input_path))
    except Exception as exc:
        emit({"type": "error", "message": (
            f"Could not read audio file '{input_path.name}': {exc}. "
            + ("ffmpeg is required for this format — run DAC6_Setup.bat to install it."
               if input_path.suffix.lower() in _NEEDS_FFMPEG else "")
        )})
        return
    # DAC model requires audio at its native sample rate
    if sig.sample_rate != model.sample_rate:
        import subprocess as sp
        import tempfile
        import soundfile as sf
        import numpy as np
        emit_status(f"Resampling {sig.sample_rate}\u202fHz \u2192 {model.sample_rate}\u202fHz...")
        try:
            # Use ffmpeg to resample to a temp WAV file for best quality and reliability
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            # ffmpeg: read input, resample to model SR with high-quality settings
            res = sp.run([
                "ffmpeg", "-nostdin", "-y", "-i", str(input_path),
                "-af", f"aresample=resampler=swr:filter_size=256:phase_shift=10",
                "-ar", str(model.sample_rate), "-ac", "2",  # stereo, model SR
                tmp_path
            ], capture_output=True, text=True)
            if res.returncode != 0:
                os.unlink(tmp_path)
                emit({"type": "error", "message": (
                    f"ffmpeg resample failed: {res.stderr[:200]}"
                )})
                return
            # Reload using soundfile instead of AudioSignal to avoid native codec crashes
            audio_np, sr = sf.read(tmp_path, always_2d=True)
            os.unlink(tmp_path)
            # Build new AudioSignal from numpy array
            sig = AudioSignal(audio_np.T, sample_rate=sr)
        except Exception as exc:
            emit({"type": "error", "message": (
                f"Resample failed ({sig.sample_rate}\u202fHz \u2192 {model.sample_rate}\u202fHz): {exc}."
            )})
            return
    # Move to GPU only after resample
    sig_dev = sig.to(str(device))
    duration_s  = float(sig.duration)
    channels    = int(sig_dev.audio_data.shape[1])
    sample_rate = int(sig.sample_rate)

    emit({"type": "info", "duration": duration_s, "channels": channels,
          "sample_rate": sample_rate, "n_codebooks": n_q})

    chunk_s = args.chunk_seconds
    overlap_s = 0.5  # 500ms overlap at start/end of each chunk

    def encode_ch(audio_data, ch_label: str, p_start: int, p_end: int) -> "np.ndarray":
        chunk_samples = int(chunk_s * model.sample_rate)
        overlap_samples = int(overlap_s * model.sample_rate)
        audio_t = model.preprocess(audio_data, sample_rate)
        total_samples = audio_t.shape[-1]
        n_chunks = max(1, (total_samples + chunk_samples - 1) // chunk_samples)
        all_codes = []
        
        with torch.no_grad():
            for i in range(n_chunks):
                pct = p_start + int((i / n_chunks) * (p_end - p_start))
                emit_progress(pct)
                emit_status(f"Encoding {ch_label} — chunk {i+1}/{n_chunks}")
                
                # Calculate chunk boundaries with overlap
                chunk_start = i * chunk_samples
                chunk_end = min((i + 1) * chunk_samples, total_samples)
                
                # Add overlap padding (except at very start/end of audio)
                pad_start = max(0, chunk_start - overlap_samples)
                pad_end = min(total_samples, chunk_end + overlap_samples)
                
                # Extract chunk with overlap
                chunk = audio_t[..., pad_start:pad_end]
                _, codes, _, _, _ = model.encode(chunk, n_quantizers=n_q)
                
                # Calculate frames to trim (overlap in code space)
                # hop_length converts samples to frames
                overlap_frames = overlap_samples // int(model.hop_length)
                
                # Trim overlap from codes
                trim_start = 0 if i == 0 else overlap_frames
                trim_end = codes.shape[-1] if i == n_chunks - 1 else -overlap_frames if overlap_frames > 0 else codes.shape[-1]
                
                if trim_end < 0:
                    codes_trimmed = codes[..., trim_start:trim_end]
                else:
                    codes_trimmed = codes[..., trim_start:]
                
                all_codes.append(codes_trimmed.cpu())
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        return torch.cat(all_codes, dim=-1).squeeze(0).numpy()

    t0 = time.time()
    if channels == 2:
        left  = encode_ch(sig_dev.audio_data[:, 0:1, :], "L", 15, 52)
        right = encode_ch(sig_dev.audio_data[:, 1:2, :], "R", 52, 85)
        codes = np.stack([left, right], axis=0)
    else:
        mono  = encode_ch(sig_dev.audio_data[:, 0:1, :], "mono", 15, 85)
        codes = mono[np.newaxis, ...]
    encode_s = time.time() - t0

    emit_status("Compressing...")
    emit_progress(90)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "codec": "dac", "container": "ncmp", "container_version": VERSION,
        "model": args.model, "channels": channels,
        "n_codebooks": int(codes.shape[1]), "n_frames": int(codes.shape[2]),
        "sample_rate": int(model.sample_rate), "hop_length": int(model.hop_length),
        "duration_s": round(duration_s, 6), "source_name": input_path.name,
    }
    header  = json.dumps(meta, separators=(",", ":")).encode()
    payload = gzip.compress(
        codes.reshape(-1, codes.shape[2]).astype(np.uint16).tobytes(), compresslevel=9
    )

    out_path = out_dir / f"{input_path.stem}.dac{n_q}cb.ncmp"
    with out_path.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<H", VERSION))
        f.write(struct.pack("<I", len(header)))
        f.write(header)
        f.write(payload)

    size_bytes   = out_path.stat().st_size
    source_bytes = input_path.stat().st_size
    kbps = size_bytes * 8.0 / max(duration_s, 1e-9) / 1000.0

    emit_progress(100)
    emit({"type": "done", "path": str(out_path),
          "size_kb": size_bytes / 1024, "kbps": kbps,
          "encode_s": encode_s, "ratio": source_bytes / max(size_bytes, 1)})


# ── decode ────────────────────────────────────────────────────────────────────

def run_decode(args):
    import numpy as np
    import torch

    try:
        import dac
        import soundfile as sf
    except ImportError as e:
        emit({"type": "error", "message": f"Missing dependency: {e}"})
        return

    input_path = Path(args.input)
    if not input_path.exists():
        emit({"type": "error", "message": f"File not found: {input_path}"})
        return

    emit_status("Reading .ncmp file...")
    emit_progress(5)

    with input_path.open("rb") as f:
        if f.read(4) != MAGIC:
            emit({"type": "error", "message": "Not a valid NCMP file"}); return
        struct.unpack("<H", f.read(2))
        hlen = struct.unpack("<I", f.read(4))[0]
        meta = json.loads(f.read(hlen).decode())
        payload = f.read()

    channels    = int(meta["channels"])
    n_codebooks = int(meta["n_codebooks"])
    n_frames    = int(meta["n_frames"])
    duration_s  = float(meta["duration_s"])

    emit({"type": "info", "duration": duration_s, "channels": channels,
          "sample_rate": int(meta["sample_rate"]), "n_codebooks": n_codebooks})

    codes = (np.frombuffer(gzip.decompress(payload), dtype=np.uint16)
               .reshape(channels, n_codebooks, n_frames).copy())

    def choose_device(req):
        if req == "cpu":   return torch.device("cpu")
        if req == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but not available")
            return torch.device("cuda")
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")

    emit_status("Loading DAC model...")
    emit_progress(12)
    device = choose_device(args.device)
    model_path = dac.utils.download(model_type=meta.get("model", "44khz"))
    model = dac.DAC.load(model_path).to(device).eval()

    chunk_t = args.chunk_frames
    overlap_s = 0.5  # 500ms overlap
    hop_length = int(model.hop_length)
    sample_rate = int(meta["sample_rate"])
    overlap_frames = int((overlap_s * sample_rate) / hop_length)

    # Support partial decoding for streaming
    start_chunk_idx = args.start_chunk if args.start_chunk is not None else 0
    num_chunks_to_decode = args.num_chunks if args.num_chunks is not None else None
    
    t0 = time.time()
    out_channels = []
    for ch in range(channels):
        ch_label = ["L", "R"][ch] if channels == 2 else "mono"
        p_start  = 20 + ch * (60 // channels)
        p_end    = 20 + (ch + 1) * (60 // channels)
        codes_t  = torch.from_numpy(codes[ch]).long().unsqueeze(0).to(device)
        n_chunks = max(1, (n_frames + chunk_t - 1) // chunk_t)
        
        # Calculate actual chunk range to decode
        end_chunk_idx = min(start_chunk_idx + num_chunks_to_decode, n_chunks) if num_chunks_to_decode else n_chunks
        chunks_to_decode = end_chunk_idx - start_chunk_idx
        
        chunks   = []
        
        with torch.no_grad():
            for idx, i in enumerate(range(start_chunk_idx, end_chunk_idx)):
                pct = p_start + int((idx / chunks_to_decode) * (p_end - p_start))
                emit_progress(pct)
                emit_status(f"Decoding {ch_label} — chunk {i+1}/{n_chunks}")
                
                # Calculate chunk boundaries with overlap
                chunk_start = i * chunk_t
                chunk_end = min((i + 1) * chunk_t, n_frames)
                
                # Add overlap padding (except at very start/end)
                pad_start = max(0, chunk_start - overlap_frames)
                pad_end = min(n_frames, chunk_end + overlap_frames)
                
                # Extract codes chunk with overlap
                chunk = codes_t[:, :, pad_start:pad_end]
                z = model.quantizer.from_codes(chunk)[0]
                y = model.decode(z)
                
                # Calculate samples to trim (overlap in audio space)
                overlap_samples = overlap_frames * hop_length
                # Trim overlap only at boundaries of the FULL file, not partial decode
                is_first_chunk_global = (i == 0)
                is_last_chunk_global = (i == n_chunks - 1)
                trim_start_samples = 0 if is_first_chunk_global else overlap_samples
                trim_end_samples = y.shape[-1] if is_last_chunk_global else -overlap_samples if overlap_samples > 0 else y.shape[-1]
                
                # Trim overlap from decoded audio
                if trim_end_samples < 0:
                    y_trimmed = y[..., trim_start_samples:trim_end_samples]
                else:
                    y_trimmed = y[..., trim_start_samples:]
                
                chunks.append(y_trimmed.cpu())
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        out_channels.append(torch.cat(chunks, dim=-1).squeeze(0).squeeze(0).numpy())
    decode_s = time.time() - t0

    emit_status("Saving WAV...")
    emit_progress(85)

    if channels == 2:
        n     = min(len(out_channels[0]), len(out_channels[1]))
        audio = np.stack([out_channels[0][:n], out_channels[1][:n]], axis=1)
    else:
        audio = out_channels[0]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"dac{n_codebooks}cb"
    stem   = input_path.stem
    if stem.endswith(f".{suffix}"):
        stem = stem[: -len(f".{suffix}")]
    wav_path = out_dir / f"{stem}_{suffix}_reconstructed.wav"
    sf.write(wav_path, np.clip(audio, -1.0, 1.0), int(meta["sample_rate"]))

    if args.mp3:
        import subprocess as sp
        mp3_path = wav_path.with_suffix(".mp3")
        emit_status("Converting to MP3...")
        emit_progress(95)
        res = sp.run(
            ["ffmpeg", "-nostdin", "-y", "-i", str(wav_path),
             "-b:a", f"{args.mp3_bitrate}k", str(mp3_path)],
            capture_output=True,
        )
        if res.returncode == 0:
            emit_progress(100)
            emit({"type": "done", "path": str(mp3_path),
                  "wav_path": str(wav_path), "decode_s": decode_s, "has_mp3": True})
            return

    emit_progress(100)
    emit({"type": "done", "path": str(wav_path), "decode_s": decode_s, "has_mp3": False})


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encode")
    enc.add_argument("input")
    enc.add_argument("--out-dir",       default="out")
    enc.add_argument("--n-codebooks",   type=int, default=6)
    enc.add_argument("--model",         default="44khz")
    enc.add_argument("--device",        default="auto")
    enc.add_argument("--chunk-seconds", type=int, default=60)

    dec = sub.add_parser("decode")
    dec.add_argument("input")
    dec.add_argument("--out-dir",       default="recovered")
    dec.add_argument("--device",        default="auto")
    dec.add_argument("--chunk-frames",  type=int, default=10000)
    dec.add_argument("--mp3",           action="store_true")
    dec.add_argument("--mp3-bitrate",   type=int, default=192)
    dec.add_argument("--start-chunk",   type=int, help="Start chunk index for partial decode")
    dec.add_argument("--num-chunks",    type=int, help="Number of chunks to decode")

    args = parser.parse_args()
    try:
        if args.cmd == "encode":
            run_encode(args)
        else:
            run_decode(args)
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        msg = str(e) if str(e) else type(e).__name__
        emit({"type": "error", "message": msg})
        sys.exit(1)


if __name__ == "__main__":
    main()
