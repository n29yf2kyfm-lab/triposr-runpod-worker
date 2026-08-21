"""Sub-pixel straight-edge fitter.
For a side defined by two rough endpoints, scan perpendicular profiles, locate the
sub-pixel maximum of |dI/ds| (parabolic interpolation on the smoothed gradient),
robustly fit a line (Huber/IRLS), and report residual RMS + inlier count.
Edge definition used throughout: point of steepest intensity change.
"""
import numpy as np, cv2

def trace(gray, p0, p1, halfwin=14, nsamp=200, trim=0.10, sigma=1.2, minmag=6.0):
    p0=np.array(p0,float); p1=np.array(p1,float)
    v=p1-p0; L=np.linalg.norm(v); u=v/L; n=np.array([-u[1],u[0]])
    ts=np.linspace(trim*L,(1-trim)*L,nsamp)
    pts=[]; mags=[]
    ss=np.arange(-halfwin,halfwin+1,0.25)
    for t in ts:
        base=p0+u*t
        coords=base[None,:]+ss[:,None]*n[None,:]
        # bilinear sample
        val=cv2.remap(gray, coords[:,0].astype(np.float32).reshape(-1,1),
                            coords[:,1].astype(np.float32).reshape(-1,1),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).ravel()
        val=cv2.GaussianBlur(val.reshape(-1,1),(0,0),sigma).ravel()
        d=np.abs(np.gradient(val))
        k=int(np.argmax(d))
        if k<=0 or k>=len(d)-1: continue
        if d[k]<minmag: continue
        a,b,c=d[k-1],d[k],d[k+1]
        den=(a-2*b+c)
        off=0.0 if den==0 else 0.5*(a-c)/den
        s=ss[k]+off*0.25
        pts.append(base+s*n); mags.append(d[k])
    P=np.array(pts)
    if len(P)<20: raise RuntimeError('too few edge samples (%d)'%len(P))
    # IRLS line fit (TLS with Huber weights)
    w=np.ones(len(P))
    for _ in range(12):
        mu=(P*w[:,None]).sum(0)/w.sum()
        X=(P-mu)*np.sqrt(w)[:,None]
        _,_,Vt=np.linalg.svd(X,full_matrices=False)
        dirv=Vt[0]; nv=np.array([-dirv[1],dirv[0]])
        r=(P-mu)@nv
        s=1.4826*np.median(np.abs(r-np.median(r)))+1e-9
        k=1.5*s
        w=np.where(np.abs(r)<=k,1.0,k/np.abs(r))
    r=(P-mu)@nv
    inl=np.abs(r)<3*s
    return dict(mu=mu, n=nv, dir=dirv, rms=float(np.sqrt((r[inl]**2).mean())),
                n_samples=int(len(P)), inliers=int(inl.sum()),
                maxres=float(np.abs(r[inl]).max()), pts=P)

def intersect(l1,l2):
    A=np.array([l1['n'],l2['n']]); b=np.array([l1['n']@l1['mu'], l2['n']@l2['mu']])
    return np.linalg.solve(A,b)
