#!/usr/bin/env python3
"""
Standalone DAC 6 kbps-ish audio compressor.

Default mode uses DAC 44 kHz with 6 codebooks per channel for stereo tracks.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch


MAGIC = b"NCMP"
VERSION = 3
DEFAULT_CODEBOOKS = 6
DEFAULT_MODEL = "44khz"


def _lazy_import_dac():
    try:
        import dac
        from audiotools import AudioSignal
    except ImportError as exc:
        raise SystemExit(
            "Missing DAC dependencies. Install with:\n"
            "  pip install -r requirements.txt\n"
            "or:\n"
            "  pip install descript-audio-codec audiotools"
        ) from exc
    return dac, AudioSignal


def choose_device(requested: str) -> torch.device:
    if requested == "cpu":
        return torch.device("cpu")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise SystemExit("CUDA requested but torch.cuda.is_available() is false")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_model(model_type: str, device: torch.device):
    dac, _ = _lazy_import_dac()
    model_path = dac.utils.download(model_type=model_type)
    model = dac.DAC.load(model_path).to(device)
    model.eval()
    return model


def save_bin(path: Path, codes_flat: np.ndarray, meta: dict) -> int:
    header = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    payload = gzip.compress(codes_flat.astype(np.uint16).tobytes(), compresslevel=9)
    with path.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<H", VERSION))
        f.write(struct.pack("<I", len(header)))
        f.write(header)
        f.write(payload)
    return path.stat().st_size


def load_bin(path: Path) -> tuple[dict, np.ndarray]:
    with path.open("rb") as f:
        if f.read(4) != MAGIC:
            raise SystemExit(f"{path} is not an NCMP/DAC6 file")
        _version = struct.unpack("<H", f.read(2))[0]
        header_len = struct.unpack("<I", f.read(4))[0]
        meta = json.loads(f.read(header_len).decode("utf-8"))
        payload = f.read()

    rows = int(meta["channels"]) * int(meta["n_codebooks"])
    frames = int(meta["n_frames"])
    codes = np.frombuffer(gzip.decompress(payload), dtype=np.uint16).reshape(rows, frames).copy()
    return meta, codes


def encode_channel(model, audio_data: torch.Tensor, sample_rate: int, n_quantizers: int, chunk_s: int) -> np.ndarray:
    chunk_samples = int(chunk_s * model.sample_rate)
    overlap_s = 0.5  # 500ms overlap at start/end of each chunk
    overlap_samples = int(overlap_s * model.sample_rate)
    audio_t = model.preprocess(audio_data, sample_rate)
    total_samples = audio_t.shape[-1]
    n_chunks = max(1, (total_samples + chunk_samples - 1) // chunk_samples)
    all_codes = []
    
    with torch.no_grad():
        for i in range(n_chunks):
            # Calculate chunk boundaries with overlap
            chunk_start = i * chunk_samples
            chunk_end = min((i + 1) * chunk_samples, total_samples)
            
            # Add overlap padding (except at very start/end of audio)
            pad_start = max(0, chunk_start - overlap_samples)
            pad_end = min(total_samples, chunk_end + overlap_samples)
            
            # Extract chunk with overlap
            chunk = audio_t[..., pad_start:pad_end]
            _, codes, _, _, _ = model.encode(chunk, n_quantizers=n_quantizers)
            
            # Calculate frames to trim (overlap in code space)
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


def encode_file(args: argparse.Namespace) -> Path:
    _, AudioSignal = _lazy_import_dac()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = choose_device(args.device)
    chunk_s = args.chunk_seconds

    t_load = time.time()
    model = load_model(args.model, device)
    load_s = time.time() - t_load
    n_q = min(int(args.n_codebooks), int(model.n_codebooks))

    sig = AudioSignal(str(input_path))
    # DAC model requires audio at its native sample rate
    if sig.sample_rate != model.sample_rate:
        import subprocess as sp
        import tempfile
        print(f"Resampling:  {sig.sample_rate} Hz \u2192 {model.sample_rate} Hz")
        try:
            # Use ffmpeg to resample to a temp WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            res = sp.run([
                "ffmpeg", "-nostdin", "-y", "-i", str(input_path),
                "-ar", str(model.sample_rate), "-ac", "2",
                tmp_path
            ], capture_output=True, text=True)
            if res.returncode != 0:
                os.unlink(tmp_path)
                raise SystemExit(f"ffmpeg resample failed: {res.stderr[:200]}")
            sig = AudioSignal(tmp_path)
            os.unlink(tmp_path)
        except Exception as exc:
            raise SystemExit(
                f"Resample failed ({sig.sample_rate} Hz \u2192 {model.sample_rate} Hz): {exc}."
            ) from exc
    sig_dev = sig.to(str(device))
    duration_s = float(sig.duration)
    channels = int(sig.audio_data.shape[1])

    print(f"Input:       {input_path}")
    print(f"Audio:       {duration_s:.2f}s | {sig.sample_rate} Hz | {channels} channel(s)")
    print(f"Model:       DAC {args.model} | {n_q} codebooks/channel | device={device}")
    print(f"Model load:  {load_s:.2f}s")
    print(f"Chunks:      {chunk_s}s")

    t0 = time.time()
    if channels == 2:
        left = encode_channel(model, sig_dev.audio_data[:, 0:1, :], sig.sample_rate, n_q, chunk_s)
        right = encode_channel(model, sig_dev.audio_data[:, 1:2, :], sig.sample_rate, n_q, chunk_s)
        codes = np.stack([left, right], axis=0)
    else:
        mono = encode_channel(model, sig_dev.audio_data[:, 0:1, :], sig.sample_rate, n_q, chunk_s)
        codes = mono[np.newaxis, ...]
    encode_s = time.time() - t0

    meta = {
        "codec": "dac",
        "container": "ncmp",
        "container_version": VERSION,
        "model": args.model,
        "channels": channels,
        "n_codebooks": int(codes.shape[1]),
        "n_frames": int(codes.shape[2]),
        "sample_rate": int(model.sample_rate),
        "hop_length": int(model.hop_length),
        "duration_s": round(duration_s, 6),
        "source_name": input_path.name,
    }

    out_path = out_dir / f"{input_path.stem}.dac{n_q}cb.ncmp"
    size_bytes = save_bin(out_path, codes.reshape(-1, codes.shape[2]), meta)
    source_bytes = input_path.stat().st_size
    kbps = size_bytes * 8.0 / max(duration_s, 1e-9) / 1000.0

    print(f"Encode:      {encode_s:.2f}s ({duration_s / max(encode_s, 1e-9):.1f}x real-time)")
    print(f"Compressed:  {out_path}")
    print(f"Size:        {size_bytes / 1024:.1f} KB | {kbps:.2f} kbps | ratio vs source {source_bytes / size_bytes:.1f}x")
    return out_path


def decode_channel(model, codes_t: torch.Tensor, n_frames: int, chunk_t: int) -> np.ndarray:
    overlap_s = 0.5  # 500ms overlap
    hop_length = int(model.hop_length)
    sample_rate = int(model.sample_rate)
    overlap_frames = int((overlap_s * sample_rate) / hop_length)
    
    n_chunks = max(1, (n_frames + chunk_t - 1) // chunk_t)
    chunks = []
    
    with torch.no_grad():
        for i in range(n_chunks):
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
            trim_start_samples = 0 if i == 0 else overlap_samples
            trim_end_samples = y.shape[-1] if i == n_chunks - 1 else -overlap_samples if overlap_samples > 0 else y.shape[-1]
            
            # Trim overlap from decoded audio
            if trim_end_samples < 0:
                y_trimmed = y[..., trim_start_samples:trim_end_samples]
            else:
                y_trimmed = y[..., trim_start_samples:]
            
            chunks.append(y_trimmed.cpu())
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    return torch.cat(chunks, dim=-1).squeeze(0).squeeze(0).numpy()


def decode_to_array(path: Path, device_arg: str, chunk_t: int = 10000) -> tuple[np.ndarray, int, dict]:
    meta, codes_flat = load_bin(path)
    device = choose_device(device_arg)
    model = load_model(meta.get("model", DEFAULT_MODEL), device)

    channels = int(meta["channels"])
    n_codebooks = int(meta["n_codebooks"])
    n_frames = int(meta["n_frames"])
    codes = codes_flat.reshape(channels, n_codebooks, n_frames)

    out_channels = []
    for ch in range(channels):
        codes_t = torch.from_numpy(codes[ch]).long().unsqueeze(0).to(device)
        out_channels.append(decode_channel(model, codes_t, n_frames, chunk_t))

    if channels == 2:
        n = min(len(out_channels[0]), len(out_channels[1]))
        audio = np.stack([out_channels[0][:n], out_channels[1][:n]], axis=1)
    else:
        audio = out_channels[0]
    return audio, int(meta["sample_rate"]), meta


def decode_file(args: argparse.Namespace) -> Path:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit("Missing soundfile. Install with: pip install soundfile") from exc

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    audio, sample_rate, meta = decode_to_array(input_path, args.device)
    decode_s = time.time() - t0

    suffix = f"dac{meta['n_codebooks']}cb"
    stem = input_path.stem
    if stem.endswith(f".{suffix}"):
        stem = stem[: -len(f".{suffix}")]
    wav_path = out_dir / f"{stem}_{suffix}_reconstructed.wav"
    sf.write(wav_path, np.clip(audio, -1.0, 1.0), sample_rate)
    print(f"Decoded:     {wav_path}")
    print(f"Decode:      {decode_s:.2f}s ({float(meta['duration_s']) / max(decode_s, 1e-9):.1f}x real-time)")

    if args.mp3:
        mp3_path = wav_path.with_suffix(".mp3")
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-i", str(wav_path), "-b:a", f"{args.mp3_bitrate}k", str(mp3_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            print("MP3 export failed. Is ffmpeg installed?", file=sys.stderr)
        else:
            print(f"MP3:         {mp3_path}")
    return wav_path


def play_file(args: argparse.Namespace) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise SystemExit("Missing sounddevice. Install with: pip install sounddevice") from exc

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    if input_path.suffix.lower() in {".ncmp", ".bin"}:
        audio, sample_rate, meta = decode_to_array(input_path, args.device)
        print(f"Playing decoded DAC file: {input_path.name} ({meta['duration_s']:.1f}s)")
    else:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise SystemExit("Missing soundfile. Install with: pip install soundfile") from exc
        audio, sample_rate = sf.read(input_path, dtype="float32", always_2d=False)
        print(f"Playing audio file: {input_path.name}")

    sd.play(np.clip(audio, -1.0, 1.0), sample_rate)
    sd.wait()


def info_file(args: argparse.Namespace) -> None:
    path = Path(args.input)
    meta, _ = load_bin(path)
    size_bytes = path.stat().st_size
    duration_s = float(meta["duration_s"])
    kbps = size_bytes * 8.0 / max(duration_s, 1e-9) / 1000.0
    print(json.dumps(meta, indent=2))
    print(f"file_size_kb: {size_bytes / 1024:.2f}")
    print(f"actual_kbps:  {kbps:.2f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dac6",
        description="Standalone DAC compressor/player. Default encode mode is ~6 kbps stereo.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encode", help="Compress mp3/wav/flac/etc to .ncmp")
    enc.add_argument("input")
    enc.add_argument("--out-dir", default="out")
    enc.add_argument("--n-codebooks", type=int, default=DEFAULT_CODEBOOKS)
    enc.add_argument("--model", default=DEFAULT_MODEL, choices=["44khz", "24khz", "16khz"])
    enc.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    enc.add_argument("--chunk-seconds", type=int, default=60)
    enc.set_defaults(func=encode_file)

    dec = sub.add_parser("decode", help="Reconstruct .ncmp to WAV")
    dec.add_argument("input")
    dec.add_argument("--out-dir", default="out")
    dec.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    dec.add_argument("--mp3", action="store_true")
    dec.add_argument("--mp3-bitrate", type=int, default=192)
    dec.set_defaults(func=decode_file)

    play = sub.add_parser("play", help="Decode/play .ncmp, or play a WAV directly")
    play.add_argument("input")
    play.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    play.set_defaults(func=play_file)

    inf = sub.add_parser("info", help="Show .ncmp metadata")
    inf.add_argument("input")
    inf.set_defaults(func=info_file)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
