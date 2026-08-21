"""Plate-plane homography + camera recovery + parallax sensitivity.

Frame convention (metric, mm), plate plane:
  U = to the CAR'S RIGHT is NEGATIVE ... we store raw plate coords first
  plate TL=(0,0) TR=(520,0) BR=(520,H) BL=(0,H) with H=plate height mm.
Image->plate:  Hinv.  Plate->image: Hf.
Camera recovery (Zhang, single homography, square pixels, principal point at
image centre): f solved from the two orthonormality constraints on r1,r2.
"""
import numpy as np, cv2

def build(corners_img, W=520.0, H=111.0):
    src=np.array(corners_img,np.float64)              # TL,TR,BR,BL in pixels
    dst=np.array([[0,0],[W,0],[W,H],[0,H]],np.float64)
    Hf,_=cv2.findHomography(dst,src,0)                # plate mm -> image px
    Hi=np.linalg.inv(Hf)
    return Hf,Hi

def to_plate(Hi,pts):
    p=np.array(pts,np.float64).reshape(-1,2)
    q=np.c_[p,np.ones(len(p))]@Hi.T
    return q[:,:2]/q[:,2:3]

def to_image(Hf,pts):
    p=np.array(pts,np.float64).reshape(-1,2)
    q=np.c_[p,np.ones(len(p))]@Hf.T
    return q[:,:2]/q[:,2:3]

def focal_from_H(Hf, cx, cy):
    """Solve f from h1.K^-T K^-1 h2 = 0 and h1'..h1 = h2'..h2 (pp fixed at cx,cy)."""
    T=np.array([[1,0,-cx],[0,1,-cy],[0,0,1]],float)
    Hn=T@Hf
    h1,h2=Hn[:,0],Hn[:,1]
    # constraint A: h1x h2x + h1y h2y + f^2 * ... -> with K=diag(f,f,1)
    # K^-T K^-1 = diag(1/f^2, 1/f^2, 1)
    # C1: (h1x h2x + h1y h2y)/f^2 + h1z h2z = 0  -> f^2 = -(h1x h2x + h1y h2y)/(h1z h2z)
    num=-(h1[0]*h2[0]+h1[1]*h2[1]); den=h1[2]*h2[2]
    f2a = num/den if den!=0 else np.nan
    # C2: (h1x^2+h1y^2)/f^2 + h1z^2 = (h2x^2+h2y^2)/f^2 + h2z^2
    numb=(h1[0]**2+h1[1]**2)-(h2[0]**2+h2[1]**2); denb=h2[2]**2-h1[2]**2
    f2b = numb/denb if denb!=0 else np.nan
    return (np.sqrt(f2a) if f2a and f2a>0 else np.nan,
            np.sqrt(f2b) if f2b and f2b>0 else np.nan)

def pose_from_H(Hf,K):
    Ki=np.linalg.inv(K); M=Ki@Hf
    l=1.0/np.linalg.norm(M[:,0])
    r1=M[:,0]*l; r2=M[:,1]*l; t=M[:,2]*l
    r3=np.cross(r1,r2)
    R=np.c_[r1,r2,r3]
    U,_,Vt=np.linalg.svd(R); R=U@Vt
    if t[2]<0: R=-R; t=-t
    return R,t
