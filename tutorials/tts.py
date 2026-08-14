"""Voiceover via Kokoro (open-weights TTS, runs fine on CPU via ONNX).

Cost is the whole point: self-hosted Kokoro is effectively free per video,
where a hosted voice API would eat most of the per-video budget on its own.

The model/voices files are baked into the Docker image (see Dockerfile).
ALLOW_SILENT=1 substitutes silence at the estimated duration when Kokoro
isn't installed — that keeps local tests and dev runs working without the
model, but production should never set it: a silent tutorial is a bug, so
by default a missing model fails loudly.
"""
import os
import wave

KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "/app/models/kokoro-v1.0.onnx")
KOKORO_VOICES = os.environ.get("KOKORO_VOICES", "/app/models/voices-v1.0.bin")
VOICE = os.environ.get("TTS_VOICE", "bf_emma")  # British female
SPEED = float(os.environ.get("TTS_SPEED", "1.0"))
SAMPLE_RATE = 24_000

_kokoro = None


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
    return _kokoro


def _write_wav(path, samples, sample_rate):
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


def _write_silence(path, seconds):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * int(SAMPLE_RATE * seconds))


def synthesize(text, out_path, voice=None, est_seconds=5.0):
    """Render narration to a mono WAV; returns its duration in seconds."""
    try:
        kokoro = _get_kokoro()
    except Exception as e:
        if os.environ.get("ALLOW_SILENT") == "1":
            print(f"TTS unavailable ({type(e).__name__}: {e}); writing silence")
            _write_silence(out_path, est_seconds)
            return est_seconds
        raise
    samples, sample_rate = kokoro.create(text, voice=voice or VOICE, speed=SPEED)
    _write_wav(out_path, samples, sample_rate)
    return len(samples) / sample_rate
