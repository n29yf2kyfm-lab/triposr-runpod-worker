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
# by library id. `prompt` is used with a generic workshop/car source image;
# these are procedure-agnostic atmosphere shots generated ONCE in batch and
# reused across every tutorial video (this reuse is what holds per-video cost
# at pennies — see tutorials/README.md).
BROLL_LIBRARY = {
    "workshop/ramp_up": (
        "A car rises slowly on a two-post workshop lift, mechanic's workshop "
        "background, neutral daylight, documentary style."
    ),
    "workshop/wheel_off": (
        "A mechanic's gloved hands lift a wheel away from the hub of a car "
        "raised on a lift. Steady camera, workshop lighting, sharp focus."
    ),
    "workshop/tools_bench": (
        "Slow pan across a workbench with a torque wrench, socket set and "
        "gloves laid out. Shallow depth of field, workshop lighting."
    ),
    "workshop/caliper_closeup": (
        "Close-up of a brake caliper and disc behind an alloy wheel, camera "
        "slowly pushing in. Neutral workshop lighting, sharp mechanical detail."
    ),
    "workshop/jack_points": (
        "The camera tilts down slowly along the sill of a parked car toward "
        "the jacking point, close to the bodywork. Documentary style."
    ),
    "workshop/bonnet_open": (
        "The bonnet of a parked car is open, camera glides slowly over the "
        "engine bay. Even workshop lighting, sharp detail."
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
