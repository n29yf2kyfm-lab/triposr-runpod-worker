"""ffmpeg assembly: b-roll + cards + narration -> finished tutorial MP4.

Pure CPU, a few seconds of encode per video — the request path deliberately
contains nothing heavier than libx264. Every segment is encoded with
identical parameters so the final join is a copy-concat (no generation-loss
re-encode); the only full re-encode is the subtitle burn pass.

Layout of a video:
    [title card] [disclaimer card?] [tools card?]
    [step 1: b-roll + lower-third + narration] ... [step N]
    [outro card]
A step whose b-roll clip is missing falls back to a rendered text card so
the video always completes — serve generic now, queue the bespoke clip for
the nightly wan/ batch.
"""
import os
import subprocess

import cards

# Override for environments where ffmpeg isn't on PATH (e.g. pointing at
# imageio_ffmpeg.get_ffmpeg_exe() in dev). The Docker image uses system ffmpeg.
FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")

FORMATS = {"landscape": (1280, 720), "portrait": (1080, 1920)}
FPS = 30
INTRO_SECONDS = 2.8
DISCLAIMER_SECONDS = 4.0
TOOLS_SECONDS = 3.5
OUTRO_SECONDS = 2.5
OUTRO_TEXT = os.environ.get("OUTRO_TEXT", "ExpertCarCheck")

ENCODE = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
    "-pix_fmt", "yuv420p", "-r", str(FPS),
    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1",
]


def _run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {' '.join(cmd[:8])}...\n"
            f"{proc.stderr[-2000:]}"
        )


def _segment_card(image_path, seconds, size, out_path):
    w, h = size
    _run([
        FFMPEG, "-y",
        "-loop", "1", "-t", f"{seconds:.3f}", "-i", image_path,
        "-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=mono",
        "-vf", f"scale={w}:{h},setsar=1,fps={FPS}",
        "-t", f"{seconds:.3f}", *ENCODE, out_path,
    ])
    return out_path


def _segment_step(broll_path, overlay_path, audio_path, seconds, size, out_path):
    w, h = size
    _run([
        FFMPEG, "-y",
        "-stream_loop", "-1", "-i", broll_path,
        "-i", overlay_path,
        "-i", audio_path,
        "-filter_complex",
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,fps={FPS}[bg];[bg][1:v]overlay=0:0[v]",
        "-map", "[v]", "-map", "2:a",
        "-t", f"{seconds:.3f}", *ENCODE, out_path,
    ])
    return out_path


def _srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def _split_sentences(text):
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in ".!?" and len(buf.strip()) > 1:
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return parts or [text]


def build_srt(timed_steps, out_path):
    """timed_steps: [(start_seconds, duration, narration)]. Sentences within a
    step share its window proportionally to word count."""
    cues = []
    for start, duration, narration in timed_steps:
        sentences = _split_sentences(narration)
        total_words = sum(len(s.split()) for s in sentences) or 1
        t = start
        for s in sentences:
            share = duration * len(s.split()) / total_words
            cues.append((t, min(t + share, start + duration), s))
            t += share
    with open(out_path, "w") as f:
        for i, (a, b, text) in enumerate(cues, 1):
            f.write(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n\n")
    return out_path


def build_video(script, step_audio, broll_paths, workdir, out_path,
                fmt="landscape", subtitles=True):
    """Assemble one rendition.

    script:      output of script_gen.build_script (possibly polished)
    step_audio:  {step_id: (wav_path, duration_seconds)}
    broll_paths: {library_key: local mp4 path} — missing keys fall back to cards
    """
    size = FORMATS[fmt]
    seg_dir = os.path.join(workdir, f"segments_{fmt}")
    os.makedirs(seg_dir, exist_ok=True)
    segments, timed_steps, cursor = [], [], 0.0

    def add(path, seconds):
        nonlocal cursor
        segments.append(path)
        cursor += seconds

    img = os.path.join(seg_dir, "title.png")
    cards.title_card(img, size, script["title"], subtitle=OUTRO_TEXT)
    add(_segment_card(img, INTRO_SECONDS, size, os.path.join(seg_dir, "s_title.mp4")),
        INTRO_SECONDS)

    if script.get("safety_critical") and script.get("disclaimer"):
        img = os.path.join(seg_dir, "disclaimer.png")
        cards.text_card(img, size, "Before you start", [script["disclaimer"]], small=True)
        add(_segment_card(img, DISCLAIMER_SECONDS, size,
                          os.path.join(seg_dir, "s_disclaimer.mp4")), DISCLAIMER_SECONDS)

    if script.get("tools"):
        img = os.path.join(seg_dir, "tools.png")
        cards.text_card(img, size, "You'll need", script["tools"])
        add(_segment_card(img, TOOLS_SECONDS, size,
                          os.path.join(seg_dir, "s_tools.mp4")), TOOLS_SECONDS)

    for i, step in enumerate(script["steps"], 1):
        wav, seconds = step_audio[step["id"]]
        seg = os.path.join(seg_dir, f"s_step_{i:02d}.mp4")
        broll = broll_paths.get(step.get("broll", ""))
        timed_steps.append((cursor, seconds, step["narration"]))
        if broll:
            overlay = os.path.join(seg_dir, f"lower3_{i:02d}.png")
            cards.lower_third(overlay, size, i, step["title"])
            _segment_step(broll, overlay, wav, seconds, size, seg)
        else:
            # No clip in the library (yet): render the step as a card so the
            # video still ships; narration carries the content.
            img = os.path.join(seg_dir, f"card_{i:02d}.png")
            cards.text_card(img, size, f"{i:02d}  {step['title']}",
                            step.get("card") or [step["title"]])
            _run_card_with_audio(img, wav, seconds, size, seg)
        add(seg, seconds)

    img = os.path.join(seg_dir, "outro.png")
    cards.title_card(img, size, OUTRO_TEXT, subtitle=script["title"])
    add(_segment_card(img, OUTRO_SECONDS, size, os.path.join(seg_dir, "s_outro.mp4")),
        OUTRO_SECONDS)

    list_path = os.path.join(seg_dir, "concat.txt")
    with open(list_path, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")
    joined = os.path.join(seg_dir, "joined.mp4")
    _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
          "-c", "copy", joined])

    if subtitles and timed_steps:
        srt = build_srt(timed_steps, os.path.join(seg_dir, "subs.srt"))
        style = ("FontSize=%d,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101216,"
                 "Outline=1,MarginV=%d") % ((22, 40) if fmt == "landscape" else (16, 120))
        _run([FFMPEG, "-y", "-i", joined,
              "-vf", f"subtitles={srt}:force_style='{style}'",
              *ENCODE, out_path])
    else:
        os.replace(joined, out_path)
    return out_path, round(cursor, 1)


def _run_card_with_audio(image_path, audio_path, seconds, size, out_path):
    w, h = size
    _run([
        FFMPEG, "-y",
        "-loop", "1", "-t", f"{seconds:.3f}", "-i", image_path,
        "-i", audio_path,
        "-vf", f"scale={w}:{h},setsar=1,fps={FPS}",
        "-map", "0:v", "-map", "1:a",
        "-t", f"{seconds:.3f}", *ENCODE, out_path,
    ])
    return out_path
