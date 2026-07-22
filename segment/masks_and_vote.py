"""Step 2 — 2D masks per view + multi-view vote fusion -> per-face labels.

This is the swappable masker stage. Right now it uses a classical HSV masker
that works BECAUSE we render under controlled light (glass reads dark+grey,
body reads saturated), unlike the baked atlas where glass mirrors the paint.
The Grounded-SAM GPU worker will replace `mask_view()` with learned masks;
everything downstream (voting + geometry fusion) is unchanged.

Fusion rule: a face's 2D votes are combined with a geometry prior so grille /
headlights (dark in 2D but low on the car) never become glass, and body-coloured
pillars inside the greenhouse (bright in 2D) never get carved out.

Usage: python3 seg_step2_vote.py <work_dir>   ->  writes labels.npy
"""
import sys, os, numpy as np, cv2, base64, io, json, time, urllib.request

WORK = sys.argv[1]
# Grounded-SAM endpoint: set GSAM_EP=<runpod endpoint id> to use learned masks
# instead of the classical HSV masker. Everything downstream is identical.
GSAM_EP = os.environ.get("GSAM_EP", "").strip()
RP_KEY = os.environ.get("RUNPOD_KEY", "").strip()

def gsam_masks(paths):
    """Send rendered views to the Grounded-SAM worker; return list of class maps
    (0 bg/body, 2 glass, 3 wheel, 4 light). Falls back to None on any failure so
    the caller can use the classical masker."""
    try:
        imgs = [base64.b64encode(open(p, "rb").read()).decode() for p in paths]
        body = json.dumps({"input": {"images_b64": imgs}}).encode()
        req = urllib.request.Request(f"https://api.runpod.ai/v2/{GSAM_EP}/run",
            data=body, method="POST",
            headers={"Authorization": "Bearer "+RP_KEY, "Content-Type": "application/json"})
        jid = json.loads(urllib.request.urlopen(req, timeout=120).read())["id"]
        for _ in range(260):
            st = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"https://api.runpod.ai/v2/{GSAM_EP}/status/{jid}",
                headers={"Authorization": "Bearer "+RP_KEY}), timeout=60).read())
            if st.get("status") == "COMPLETED":
                out = st["output"]["masks_b64"]
                return [cv2.imdecode(np.frombuffer(base64.b64decode(b), np.uint8),
                                     cv2.IMREAD_GRAYSCALE) for b in out]
            if st.get("status") not in ("IN_QUEUE", "IN_PROGRESS"):
                print("GSAM failed:", st.get("status")); return None
            time.sleep(4)
    except Exception as e:
        print("GSAM error, using classical masker:", e)
    return None
pz = np.load(f"{WORK}/proj.npz"); PX, PY, VIS = pz["px"], pz["py"], pz["vis"]
NV = int(pz["nviews"]); Wp, Hp = int(pz["W"]), int(pz["H"])
gz = np.load(f"{WORK}/geom.npz"); zc, lc = gz["zc"], gz["lc"]
N = PX.shape[1]

def mask_view(path):
    """Return a per-pixel class image: 0 bg, 1 body, 2 glass, 3 wheel."""
    bgr = cv2.imread(path); hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1]/255.0, hsv[..., 2]/255.0
    cls = np.ones((bgr.shape[0], bgr.shape[1]), np.uint8)      # default body
    # background = flat grey matching the corner, low saturation + mid value
    corner = V[:6, :6].mean()
    bg = (np.abs(V-corner) < 0.06) & (S < 0.12)
    # morph the bg from the border so interior grey (glass) isn't killed
    ff = bg.astype(np.uint8)
    cls[(S >= 0.30) & (~bg)] = 1                               # saturated -> body
    cls[(S < 0.34) & (V < 0.55) & (~bg)] = 2                   # grey/dark -> glass-like
    cls[(V < 0.13) & (~bg)] = 3                                # near-black -> wheel-like
    cls[bg] = 0
    return cls

# masks: Grounded-SAM if an endpoint is configured, else classical HSV.
# Cache SAM masks to disk so fusion can be re-tuned without another GPU call.
paths = [f"{WORK}/view_{vi:02d}.png" for vi in range(NV)]
cached = all(os.path.exists(f"{WORK}/gmask_{vi:02d}.png") for vi in range(NV))
gmasks = None
if GSAM_EP and cached and not os.environ.get("FORCE_GSAM"):
    gmasks = [cv2.imread(f"{WORK}/gmask_{vi:02d}.png", cv2.IMREAD_GRAYSCALE) for vi in range(NV)]
    print("masker: grounded-sam (cached)")
elif GSAM_EP:
    gmasks = gsam_masks(paths)
    if gmasks:
        for vi, m in enumerate(gmasks): cv2.imwrite(f"{WORK}/gmask_{vi:02d}.png", m)
print("masker:", "grounded-sam" if gmasks else "classical-hsv")
nup = gz["nup"] if "nup" in gz else np.zeros(N)

# accumulate votes
vg = np.zeros(N, np.int32); vw = np.zeros(N, np.int32); vb = np.zeros(N, np.int32); vseen = np.zeros(N, np.int32)
for vi in range(NV):
    if gmasks:
        cls = gmasks[vi].astype(np.uint8)
        cls[(cls != 2) & (cls != 3) & (cls != 4)] = 1   # everything else -> body
    else:
        cls = mask_view(f"{WORK}/view_{vi:02d}.png")
    vis = VIS[vi]; idx = np.where(vis)[0]
    ys = np.clip(PY[vi, idx], 0, Hp-1); xs = np.clip(PX[vi, idx], 0, Wp-1)
    c = cls[ys, xs]
    vseen[idx] += (c != 0)
    vg[idx[c == 2]] += 1; vw[idx[c == 3]] += 1; vb[idx[c == 1]] += 1

# ---- fuse 2D votes with geometry prior ----
lab = np.ones(N, np.int8)                                      # body default
seen = vseen > 0
gl_frac = np.where(seen, vg/np.maximum(vseen, 1), 0)
wh_frac = np.where(seen, vw/np.maximum(vseen, 1), 0)

# GLASS: 2D says glass in most views it's seen AND it sits in the cabin band
glass = (gl_frac > 0.5) & (zc > 0.45) & (zc < 0.92)
# faces never seen but geometrically deep in the greenhouse -> glass (fills the
# far side of windows the cameras couldn't reach)
glass |= (~seen) & (zc > 0.55) & (zc < 0.85)
# WINDSHIELD assist: the raked front/rear screens are seen mostly at grazing
# angles, so SAM votes there are ~50/50 and the pane comes out speckled. Recover
# raked high faces (not vertical side glass, not flat roof) with even partial
# glass support -> solid screens.
windshield = (gl_frac > 0.28) & (zc > 0.5) & (nup > 0.28) & (nup < 0.85)
glass |= windshield
# WHEEL: 2D near-black OR geometric wheel zone (low + at the two ends), but only
# where 2D does NOT read the face as saturated body (protects bumper corners).
at_end = (lc < 0.31) | (lc > 0.69)
dom2d = np.argmax(np.stack([vb, vg, vw], 1), 1)             # 0 body 1 glass 2 wheel
not_body2d = (dom2d != 0) | (~seen)                         # unseen inner-arch faces count
wheel = ((wh_frac > 0.4) & (zc < 0.42)) | ((zc < 0.34) & at_end & not_body2d)

lab[glass] = 2
lab[wheel & (lab != 2)] = 3
# INTERIOR: faces never seen from any exterior view are the cabin (dashboard,
# seats, headliner). They must NOT be body-painted — otherwise the see-through
# glass reveals a red interior (the real cause of the "windshield speckle").
# Keep their baked texture (trim) so the cabin reads neutral behind the glass.
lab[(~seen) & (lab == 1)] = 0
np.save(f"{WORK}/labels.npy", lab)
print("STEP2_DONE seen=%.2f body=%d glass=%d wheel=%d" % (seen.mean(), (lab == 1).sum(), (lab == 2).sum(), (lab == 3).sum()))
