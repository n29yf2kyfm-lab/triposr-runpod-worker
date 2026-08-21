import cv2, numpy as np, sys
R='/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/gates/g3v6/ref/'
F={'F':'REF_FRONT_golf_mk8_style_2020.jpg','P':'VW_PRESS_DB2019AU02064.jpg'}
def load(w,s=0.8):
    g=cv2.imread(R+F[w],0).astype(np.float64); return cv2.GaussianBlur(g,(0,0),s)
def hscan(g,x0,x1,step,y0,y1,mode='grad'):
    out=[]
    for x in range(x0,x1+1,step):
        c=g[y0:y1,x]
        if mode=='grad': d=np.abs(np.gradient(c)); k=int(np.argmax(d)); v=d[k]
        elif mode=='bright': k=int(np.argmax(c)); v=c[k]
        else: k=int(np.argmin(c)); v=c[k]
        out.append((x,y0+k,v))
    return out
def vscan(g,y0,y1,step,x0,x1,mode='grad'):
    out=[]
    for y in range(y0,y1+1,step):
        c=g[y,x0:x1]
        if mode=='grad': d=np.abs(np.gradient(c)); k=int(np.argmax(d)); v=d[k]
        elif mode=='bright': k=int(np.argmax(c)); v=c[k]
        else: k=int(np.argmin(c)); v=c[k]
        out.append((y,x0+k,v))
    return out
