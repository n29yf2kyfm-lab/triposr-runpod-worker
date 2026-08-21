"""GATE3 v6 landmark measurement.  Rectifies both references through their own
number-plate homography and reports every landmark in PLATE-PLANE MILLIMETRES.

Plate frame (both images):  u = 0 at the plate corner on the CAR'S RIGHT, increasing
toward the CAR'S LEFT, 520 mm at the far corner.  v = 0 at the plate top edge,
increasing DOWNWARD, 111 mm (UK) / 110 mm (DE) at the bottom edge.
Working lateral axis s = u - 260  (mm, positive toward the car's LEFT, 0 at plate centre).
"""
import numpy as np, cv2, json, sys
sys.path.insert(0,'.')
from homog import build, to_plate
from trace_edges import trace_curve, crossing, brightest

R='/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/gates/g3v6/ref/'
IMG={'F':'REF_FRONT_golf_mk8_style_2020.jpg','P':'VW_PRESS_DB2019AU02064.jpg'}
GRAY={k:cv2.imread(R+v,0) for k,v in IMG.items()}
PLATE_H={'F':111.0,'P':110.0}
CORN={'F':np.load('plate_F_corners.npy'),'P':np.load('plate_P_corners.npy')}
H={k:build(CORN[k],520.0,PLATE_H[k]) for k in 'FP'}

def rect(k,pts):
    q=to_plate(H[k][1],pts)
    return np.c_[q[:,0]-260.0, q[:,1]]      # (s, v) mm

def robust_poly(A,deg,nsig=2.5,iters=4):
    x,y=A[:,0],A[:,1]; keep=np.ones(len(x),bool)
    for _ in range(iters):
        c=np.polyfit(x[keep],y[keep],deg); r=y-np.polyval(c,x)
        s=1.4826*np.median(np.abs(r[keep]-np.median(r[keep])))+1e-9
        keep=np.abs(r)<nsig*s
    return c,keep,float(np.sqrt((r[keep]**2).mean()))
