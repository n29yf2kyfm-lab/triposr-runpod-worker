"""Sub-pixel boundary tracing by 50%-of-step crossing on a column profile.
Edge definition: the y where the smoothed intensity crosses the midpoint between the
plateau mean above the step and the plateau mean below it, inside a stated window.
Returns None where the step is weaker than `minstep` (so contaminated columns drop out
instead of returning a wrong answer).
"""
import numpy as np, cv2
def crossing(g, x, y0, y1, minstep=25, want='falling'):
    c=g[y0:y1+1, x].astype(float)
    c=cv2.GaussianBlur(c.reshape(-1,1),(0,0),1.0).ravel()
    d=np.gradient(c)
    k=int(np.argmin(d)) if want=='falling' else int(np.argmax(d))
    if k<2 or k>len(c)-3: return None
    hi=c[:k-1].max() if want=='falling' else c[k+2:].max()
    lo=c[k+2:].min() if want=='falling' else c[:k-1].min()
    if hi-lo < minstep: return None
    mid=0.5*(hi+lo)
    # walk from k outward to find the bracketing pair
    for j in range(max(1,k-4), min(len(c)-1,k+5)):
        a,b=c[j],c[j+1]
        if (a-mid)*(b-mid)<=0 and a!=b:
            return y0 + j + (a-mid)/(a-b)
    return None
def brightest(g, x, y0, y1):
    c=g[y0:y1+1,x].astype(float)
    c=cv2.GaussianBlur(c.reshape(-1,1),(0,0),1.0).ravel()
    k=int(np.argmax(c))
    if k<1 or k>len(c)-2: return None
    a,b,d=c[k-1],c[k],c[k+1]; den=(a-2*b+d)
    off=0.0 if den==0 else 0.5*(a-d)/den
    return y0+k+off
def trace_curve(g, xs, guide, half, mode='falling', minstep=25):
    """guide: callable x->y."""
    out=[]
    for x in xs:
        y=guide(x)
        f = brightest(g,int(x),int(y-half),int(y+half)) if mode=='bright' else \
            crossing(g,int(x),int(y-half),int(y+half),minstep,mode)
        if f is not None: out.append((float(x),float(f)))
    return np.array(out)
