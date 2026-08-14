"""Automotive shot presets for the Wan 2.2 I2V worker.

A preset is a reusable camera/motion recipe: the caller sends a car image plus
a preset name and gets a predictable cinematic move without prompt
engineering. Presets are also the vocabulary of the shared b-roll library —
the tutorials/ assembler references shots as "<preset>/<variant>" keys, so
preset names are a public contract; renaming one breaks library lookups.

Prompts follow Wan 2.2's preferred structure: subject, then camera motion,
then lighting/mood. Negative prompt guards against the failure modes seen in
car footage from video diffusion (warped wheels, melting badges, extra cars).
"""

NEGATIVE_PROMPT = (
    "warped wheels, deformed rims, bending panels, melting, morphing car body, "
    "extra cars, duplicate vehicle, text, watermark, logo distortion, "
    "cartoon, low quality, jitter, flicker, disfigured, extra wheels"
)

# Every preset animates ONE static car image. Keep motion moderate: Wan holds
# fidelity best when the subject stays put and the camera does the work.
PRESETS = {
    "orbit": (
        "The car stands perfectly still on the ground. The camera orbits slowly "
        "around the car in a smooth cinematic arc, revealing its bodywork from "
        "front to side. Soft studio lighting, gentle reflections gliding across "
        "the paint. Professional automotive commercial."
    ),
    "orbit_reverse": (
        "The car stands perfectly still. The camera orbits slowly around the "
        "rear of the car in a smooth cinematic arc. Soft studio lighting, "
        "reflections gliding across the paint. Professional automotive commercial."
    ),
    "headlights": (
        "The parked car's headlights switch on and glow brightly, light "
        "blooming softly. The camera pushes in slowly toward the front of the "
        "car. Dusk lighting, cinematic atmosphere."
    ),
    "damage_pan": (
        "The camera pans slowly and steadily across the side of the parked "
        "car, close to the bodywork, inspecting the panels in detail. Neutral "
        "daylight, documentary style, sharp focus on the panel surfaces."
    ),
    "scanner_sweep": (
        "A thin horizontal beam of blue light sweeps slowly across the parked "
        "car from front to back, illuminating the bodywork as it passes, like "
        "a high-tech vehicle scanner. Dark studio, futuristic technical "
        "atmosphere."
    ),
    "interior_sweep": (
        "Slow smooth camera movement across the car interior, gliding over "
        "the dashboard and steering wheel toward the center console. Soft "
        "natural light through the windows. Calm, premium feel."
    ),
    "push_in": (
        "The car stands still. The camera pushes in slowly toward the front "
        "grille and badge, shallow depth of field. Cinematic lighting."
    ),
    "wheel_detail": (
        "The camera moves slowly toward the front wheel of the parked car, "
        "framing the alloy rim and brake caliper in close-up. Sharp detail, "
        "neutral workshop lighting."
    ),
}

# Shots the tutorials/ assembler expects in the shared b-roll library, keyed
# by library id. Generated ONCE in batch and reused across every tutorial
# video (this reuse is what holds per-video cost at pennies — see
# tutorials/README.md).
#
# Tutorial visuals are ANIMATED ACTION SHOTS: a consistent stylized mechanic
# character performing each step, not photoreal atmosphere. Consistency comes
# from three levers used together on every batch:
#   1. CHARACTER + ANIM_STYLE below appear verbatim in every prompt;
#   2. the same source image seeds every shot (render ONE reference frame of
#      the character in the workshop — T2I or a simple Blender render — and
#      pass it as the batch's source_image);
#   3. a fixed seed per shot (re-runs reproduce instead of drifting).
# Because these clips DEMONSTRATE procedure steps, a human must review each
# one for mechanical correctness before it enters the live library — batch
# into `prefix: "broll_pending"` and promote after review (see README).
CHARACTER = (
    "a friendly mechanic character in navy blue overalls and orange work "
    "gloves"
)
ANIM_STYLE = (
    "High-quality stylized 3D animation, animated tutorial style, clean "
    "modern workshop, soft even lighting, smooth confident motion, "
    "consistent character design, no text"
)


def _anim(action):
    return f"{ANIM_STYLE}. {CHARACTER} {action}"


BROLL_LIBRARY = {
    # --- animated action shots: the mechanic performs each step ---
    "anim/loosen_bolts": _anim(
        "kneels beside the front wheel of a car on the ground and loosens a "
        "wheel bolt with a wheel brace, turning it half a turn."
    ),
    "anim/jack_up": _anim(
        "positions a trolley jack under the side of the car and raises it, "
        "then places an axle stand under the sill."
    ),
    "anim/wheel_off": _anim(
        "lifts the unbolted front wheel away from the hub of the raised "
        "car, revealing the brake disc and caliper behind it."
    ),
    "anim/undo_caliper": _anim(
        "uses a socket wrench to undo the caliper slider bolts, then lifts "
        "the brake caliper off the disc and rests it on the suspension, "
        "close-up on the brake assembly."
    ),
    "anim/press_piston": _anim(
        "slowly winds the brake caliper piston back with a piston tool, "
        "close-up on the caliper in his hands."
    ),
    "anim/fit_pads": _anim(
        "slides new brake pads into the caliper carrier, close-up on the "
        "brake assembly with the new pads going in."
    ),
    "anim/torque_wheel": _anim(
        "tightens the wheel bolts of the refitted wheel with a torque "
        "wrench, working around the wheel in a star pattern, the car back "
        "on the ground."
    ),
    "anim/pump_pedal": _anim(
        "sits in the driver's seat and presses the brake pedal several "
        "times, interior view of the footwell and pedal."
    ),
    # --- generic workshop atmosphere (intro/outro/filler) ---
    "workshop/ramp_up": _anim(
        "stands beside a car rising slowly on a two-post workshop lift, "
        "wide shot of the workshop."
    ),
    "workshop/tools_bench": (
        f"{ANIM_STYLE}. Slow pan across a workbench with a torque wrench, "
        "socket set and orange work gloves laid out."
    ),
    "workshop/caliper_closeup": (
        f"{ANIM_STYLE}. Close-up of a brake caliper and disc behind an "
        "alloy wheel, camera slowly pushing in, sharp mechanical detail."
    ),
    "workshop/jack_points": (
        f"{ANIM_STYLE}. The camera tilts down slowly along the sill of a "
        "parked car toward the jacking point, close to the bodywork."
    ),
    "workshop/bonnet_open": (
        f"{ANIM_STYLE}. The bonnet of a parked car is open, camera glides "
        "slowly over the engine bay."
    ),
}


def resolve_prompt(job_input):
    """Return (prompt, negative_prompt) from preset and/or free-form fields.

    Precedence: explicit `prompt` wins; else `preset` must name a known
    preset. A custom `negative_prompt` extends (not replaces) the guard list.
    """
    prompt = (job_input.get("prompt") or "").strip()
    preset = (job_input.get("preset") or "").strip()
    if not prompt:
        if not preset:
            raise ValueError("Provide 'prompt' or 'preset'")
        if preset not in PRESETS:
            raise ValueError(
                f"Unknown preset '{preset}'. Available: {sorted(PRESETS)}"
            )
        prompt = PRESETS[preset]
    extra_neg = (job_input.get("negative_prompt") or "").strip()
    negative = f"{NEGATIVE_PROMPT}, {extra_neg}" if extra_neg else NEGATIVE_PROMPT
    return prompt, negative
