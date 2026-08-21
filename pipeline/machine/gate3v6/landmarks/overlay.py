import sys, numpy as np, cv2; sys.path.insert(0,'.')
from measure import *
R='/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/gates/g3v6/ref/'
IM={'F':'REF_FRONT_golf_mk8_style_2020.jpg','P':'VW_PRESS_DB2019AU02064.jpg'}
CROP={'F':(200,1150,2600,2400),'P':(600,400,1340,830)}
CURVCOL={'bartop':(60,255,60),'chrome':(0,220,255),'barbot':(60,255,60),
         'grillebot':(255,150,60),'bumperbot':(255,90,200)}
PTCOL=(255,60,255)
def panel(k,W=2100):
    img=cv2.imread(R+IM[k]); x0,y0,x1,y1=CROP[k]
    sub=img[y0:y1,x0:x1].copy(); h,w=sub.shape[:2]; sc=W/w
    sub=cv2.resize(sub,(W,int(round(h*sc))),interpolation=cv2.INTER_CUBIC)
    def T(p): return (int(round((p[0]-x0)*sc)),int(round((p[1]-y0)*sc)))
    ov=sub.copy()
    # plate quad
    C=CORN[k]; cv2.polylines(ov,[np.array([T(p) for p in C],np.int32)],True,(0,255,255),3)
    cv2.putText(ov,'PLATE 520 x %d mm  (metric anchor)'%PLATE_H[k],T(C[3]+[0,26]),0,0.75*sc/1.0 if sc<1 else 0.9,(0,255,255),2)
    # curves
    for nm,col in CURVCOL.items():
        try: A=np.load('%s_%s.npy'%(k,nm))
        except Exception: continue
        pts=np.array([T(p) for p in A],np.int32)
        cv2.polylines(ov,[pts],False,col,3)
        cv2.putText(ov,nm,tuple(pts[len(pts)//2]+[6,-8]),0,0.8,col,2)
    # points
    import json
    raw=json.load(open('raw_measures.json'))
    for n,pv in raw['per_image'][k]['points'].items():
        p=T(pv['px']); cv2.drawMarker(ov,p,PTCOL,cv2.MARKER_CROSS,26,3)
        cv2.putText(ov,n,(p[0]+10,p[1]-10),0,0.75,PTCOL,2)
    out=cv2.addWeighted(ov,0.85,sub,0.15,0)
    lbl={'F':'REF_FRONT  2020 VW Golf Style 1.5 (UK, BF70 ENV) - Wikimedia/Vauxford CC BY-SA 4.0 - front-LEFT 3/4',
         'P':'REF_PRESS  VW Newsroom DB2019AU02064, Golf Mk8 Style (EU/LHD) - front-RIGHT 3/4'}[k]
    bar=np.zeros((70,W,3),np.uint8)
    cv2.putText(bar,lbl,(14,44),0,0.85,(255,255,255),2)
    return np.vstack([bar,out])
A=panel('F'); B=panel('P')
foot=np.zeros((150,A.shape[1],3),np.uint8)
for i,t in enumerate([
 'GATE3 v6 LANDMARK OVERLAY - every number in LANDMARK_SPEC.json is derived from these fitted curves and marked points.',
 'Metric anchor = the number plate only.  Vertical stack cross-validates between the two references to 1.5-5 mm.',
 'LATERAL positions further than ~300 mm from the plate are UNRELIABLE - the two references disagree by up to 20%.']):
    cv2.putText(foot,t,(14,40+i*40),0,0.78,(180,220,255),2)
cv2.imwrite('LANDMARK_OVERLAY.png',np.vstack([A,B,foot]))
print('written', cv2.imread('LANDMARK_OVERLAY.png').shape)
