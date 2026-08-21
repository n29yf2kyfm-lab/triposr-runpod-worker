"""Robust 3-orthogonal-vanishing-point estimation from LSD line segments.
RANSAC over segment pairs -> candidate VP -> score by angular consistency.
Then f from pairs of orthogonal VPs with pp at image centre.
NOTE: this is a CHECK on the EXIF focal length, not a substitute for it.
"""
import numpy as np, cv2, sys, json

def segments(img, minlen=120):
    g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    lsd=cv2.createLineSegmentDetector(cv2.LSD_REFINE_ADV)
    L=lsd.detect(g)[0]
    if L is None: return np.zeros((0,4))
    L=L.reshape(-1,4)
    d=np.hypot(L[:,2]-L[:,0],L[:,3]-L[:,1])
    return L[d>=minlen]

def homog_lines(S):
    p1=np.c_[S[:,0],S[:,1],np.ones(len(S))]; p2=np.c_[S[:,2],S[:,3],np.ones(len(S))]
    l=np.cross(p1,p2); return l/np.linalg.norm(l[:,:2],axis=1,keepdims=True)

def consistency(S, v):
    """angle (rad) between each segment direction and the direction to v from its midpoint"""
    mid=np.c_[(S[:,0]+S[:,2])/2,(S[:,1]+S[:,3])/2]
    d=np.c_[S[:,2]-S[:,0],S[:,3]-S[:,1]]; d=d/np.linalg.norm(d,axis=1,keepdims=True)
    if abs(v[2])<1e-12:
        dv=np.tile(v[:2]/np.linalg.norm(v[:2]),(len(S),1))
    else:
        dv=v[:2]/v[2]-mid; dv=dv/np.linalg.norm(dv,axis=1,keepdims=True)
    c=np.abs((d*dv).sum(1)).clip(0,1)
    return np.arccos(c)

def ransac_vp(S, iters=8000, tol_deg=0.6, rng=None, exclude=None):
    rng=rng or np.random.default_rng(0)
    L=homog_lines(S); tol=np.radians(tol_deg)
    best=(0,None,None)
    n=len(S)
    for _ in range(iters):
        i,j=rng.integers(0,n,2)
        if i==j: continue
        v=np.cross(L[i],L[j])
        if np.linalg.norm(v)<1e-9: continue
        a=consistency(S,v)
        inl=a<tol
        if exclude is not None: inl &= ~exclude
        w=(np.hypot(S[:,2]-S[:,0],S[:,3]-S[:,1])*inl).sum()
        if w>best[0]: best=(w,v,inl)
    return best

def refine(S, inl):
    """least-squares VP: minimise sum of squared distances from VP to each line (weighted by length)"""
    L=homog_lines(S[inl]); w=np.hypot(S[inl,2]-S[inl,0],S[inl,3]-S[inl,1])
    A=L*w[:,None]
    _,_,Vt=np.linalg.svd(A)
    return Vt[-1]
