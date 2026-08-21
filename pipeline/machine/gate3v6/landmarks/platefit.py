"""Fit the four edges of a number plate sub-pixel by line-fitting its bright mask contour.
Method: HSV threshold for bright low-sat pixels -> largest component -> contour ->
assign contour points to 4 sides by angle -> total-least-squares line fit per side ->
intersect adjacent lines for corners. Reports RMS residual per side (the quality check).
"""
import numpy as np, cv2, json, sys

def fit(img, box, vmin=185, smax=70, dbg=None):
    x0,y0,x1,y1 = box
    sub = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    m = ((hsv[:,:,2] >= vmin) & (hsv[:,:,1] <= smax)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5,5),np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5,5),np.uint8))
    n,lab,stats,cent = cv2.connectedComponentsWithStats(m, 8)
    if n<2: raise SystemExit('no component')
    i = 1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))
    comp = (lab==i).astype(np.uint8)
    cnts,_ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea).reshape(-1,2).astype(np.float64)
    area = stats[i,cv2.CC_STAT_AREA]
    # rough quad from minAreaRect to define the 4 side directions
    rect = cv2.minAreaRect(c.astype(np.float32))
    quad = cv2.boxPoints(rect).astype(np.float64)   # 4 corners, order arbitrary
    # order: top-left, top-right, bottom-right, bottom-left
    s = quad.sum(1); d = np.diff(quad,axis=1).ravel()
    tl = quad[np.argmin(s)]; br = quad[np.argmax(s)]
    tr = quad[np.argmin(d)]; bl = quad[np.argmax(d)]
    Q = np.array([tl,tr,br,bl])
    sides = [(0,1,'top'),(1,2,'right'),(2,3,'bottom'),(3,0,'left')]
    lines=[]; info=[]
    for a,b,name in sides:
        A,B = Q[a],Q[b]
        v = B-A; L=np.linalg.norm(v); v=v/L
        nvec = np.array([-v[1],v[0]])
        # signed distance of every contour pt to this side line
        dist = (c-A)@nvec
        t = (c-A)@v
        # keep points near this side and away from the rounded corners
        cornergap = 0.13*L
        sel = (np.abs(dist) < 0.06*L) & (t> cornergap) & (t < L-cornergap)
        pts = c[sel]
        if len(pts)<20: raise SystemExit('too few pts for side '+name)
        # TLS fit
        mu = pts.mean(0); X = pts-mu
        _,_,Vt = np.linalg.svd(X, full_matrices=False)
        dirv = Vt[0]; nrm = np.array([-dirv[1],dirv[0]])
        res = X@nrm
        lines.append((mu,nrm))
        info.append(dict(side=name, n=int(len(pts)), rms=float(np.sqrt((res**2).mean())),
                         maxabs=float(np.abs(res).max())))
    corners=[]
    for k in range(4):
        (m1,n1)=lines[k]; (m2,n2)=lines[(k+1)%4]
        A=np.array([n1,n2]); bb=np.array([n1@m1, n2@m2])
        p=np.linalg.solve(A,bb); corners.append(p)
    # corners[0]=top^right, [1]=right^bottom, [2]=bottom^left, [3]=left^top
    TR,BR,BL,TL = corners
    out = dict(TL=(TL+[x0,y0]).tolist(), TR=(TR+[x0,y0]).tolist(),
               BR=(BR+[x0,y0]).tolist(), BL=(BL+[x0,y0]).tolist(),
               sides=info, mask_area=int(area))
    if dbg:
        vis = sub.copy()
        P=np.array([out['TL'],out['TR'],out['BR'],out['BL']])-[x0,y0]
        cv2.polylines(vis,[P.astype(np.int32)],True,(0,0,255),2)
        for p,l in zip(P,['TL','TR','BR','BL']):
            cv2.circle(vis,tuple(p.astype(int)),5,(255,0,255),-1)
            cv2.putText(vis,l,tuple((p+[6,-6]).astype(int)),0,0.8,(255,0,255),2)
        sc=1400/max(vis.shape[1],1); vis=cv2.resize(vis,None,fx=sc,fy=sc)
        cv2.imwrite(dbg,vis)
    return out

if __name__=='__main__':
    R='/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/gates/g3v6/ref/'
    which=sys.argv[1]
    f = 'REF_FRONT_golf_mk8_style_2020.jpg' if which=='F' else 'VW_PRESS_DB2019AU02064.jpg'
    img = cv2.imread(R+f)
    box = tuple(int(v) for v in sys.argv[2:6])
    kw={}
    if len(sys.argv)>6: kw['vmin']=int(sys.argv[6])
    if len(sys.argv)>7: kw['smax']=int(sys.argv[7])
    o = fit(img, box, dbg='dbg_plate_%s.png'%which, **kw)
    print(json.dumps(o, indent=1))
