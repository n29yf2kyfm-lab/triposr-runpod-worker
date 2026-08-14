"""Tutorial assembler — the CPU request path.

Request -> cached MP4 URL if it exists, else: template -> script (optional
LLM polish) -> Kokoro TTS -> ffmpeg assembly (b-roll library + cards +
subtitles) -> upload -> URL. Marginal cost per video is a few pence; there
is deliberately NO diffusion call anywhere in this worker (see README).

Runs as a RunPod serverless handler by default; `python handler.py --local
'<json>'` runs one job without RunPod for development.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import assemble
import cache
import publish
import script_gen
import tts

DEFAULT_FORMATS = ("landscape", "portrait")


def render_tutorial(job_input):
    procedure_id = job_input.get("procedure", "")
    vehicle = (job_input.get("vehicle") or "").strip()
    voice = job_input.get("voice") or ""
    formats = job_input.get("formats") or list(DEFAULT_FORMATS)
    force = bool(job_input.get("force"))
    do_publish = bool(job_input.get("publish"))

    bad = [f for f in formats if f not in assemble.FORMATS]
    if bad:
        return {"error": f"unknown formats {bad}; valid: {sorted(assemble.FORMATS)}"}

    proc_path = script_gen.PROCEDURES_DIR / f"{procedure_id}.yaml"
    script = script_gen.build_script(procedure_id, vehicle=vehicle or None,
                                     overrides=job_input.get("variables"))

    # Cache first: the whole point is that repeat requests cost nothing.
    outputs, to_render = {}, []
    for fmt in formats:
        key = cache.video_key(proc_path, vehicle, voice or tts.VOICE, fmt)
        object_name = f"tutorials/{procedure_id}/{key}_{fmt}.mp4"
        if not force and cache.exists(object_name):
            outputs[fmt] = {"video_url": cache.public_url(object_name), "cached": True}
        else:
            to_render.append((fmt, object_name))

    timings = {}
    if to_render:
        t0 = time.time()
        script = script_gen.polish_narration(script)
        timings["script_s"] = round(time.time() - t0, 2)

        with tempfile.TemporaryDirectory() as workdir:
            t0 = time.time()
            step_audio = {}
            for step in script["steps"]:
                wav = os.path.join(workdir, f"narr_{step['id']}.wav")
                seconds = tts.synthesize(step["narration"], wav, voice=voice or None,
                                         est_seconds=step["est_seconds"])
                step_audio[step["id"]] = (wav, seconds)
            timings["tts_s"] = round(time.time() - t0, 2)

            t0 = time.time()
            broll_paths = {}
            for step in script["steps"]:
                key = step.get("broll")
                if key and key not in broll_paths:
                    path = cache.fetch_broll(key)
                    if path:
                        broll_paths[key] = path
            timings["broll_fetch_s"] = round(time.time() - t0, 2)
            missing = sorted({s["broll"] for s in script["steps"]
                             if s.get("broll") and s["broll"] not in broll_paths})

            t0 = time.time()
            for fmt, object_name in to_render:
                out_path = os.path.join(workdir, f"final_{fmt}.mp4")
                _, duration = assemble.build_video(
                    script, step_audio, broll_paths, workdir, out_path, fmt=fmt,
                    subtitles=job_input.get("subtitles", True),
                )
                url = cache.upload(out_path, object_name)
                outputs[fmt] = {
                    "video_url": url, "cached": False,
                    "duration_s": duration,
                    "size_bytes": os.path.getsize(out_path),
                }
                if url is None:
                    outputs[fmt]["warning"] = "Supabase not configured; video not persisted"
            timings["assemble_s"] = round(time.time() - t0, 2)
            if missing:
                # Not an error: cards covered these steps. Surface the list so
                # the caller can queue a wan/ b-roll batch for next time.
                timings["missing_broll"] = missing

            if do_publish and "landscape" in outputs and not outputs["landscape"].get("cached"):
                desc = script["disclaimer"] + "\n\nSteps:\n" + "\n".join(
                    f"{i}. {s['title']}" for i, s in enumerate(script["steps"], 1))
                outputs["youtube"] = publish.upload_youtube(
                    os.path.join(workdir, "final_landscape.mp4"),
                    script["title"], desc)
                if "portrait" in outputs and not outputs["portrait"].get("cached"):
                    outputs["tiktok"] = publish.upload_tiktok(
                        os.path.join(workdir, "final_portrait.mp4"), script["title"])

    return {
        "status": "success",
        "procedure": procedure_id,
        "title": script["title"],
        "vehicle": vehicle or None,
        "outputs": outputs,
        "timings": timings,
    }


def handler(job):
    job_input = job.get("input", {})
    try:
        if job_input.get("mode") == "list":
            return {"procedures": script_gen.list_procedures()}
        return render_tutorial(job_input)
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--local":
        import json
        print(json.dumps(handler({"input": json.loads(sys.argv[2])}), indent=2))
    else:
        import runpod
        runpod.serverless.start({"handler": handler})
