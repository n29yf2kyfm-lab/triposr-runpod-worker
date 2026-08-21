"""Matched before/after sheet: same camera, same exposure, same rig config."""
import os,sys
from PIL import Image, ImageDraw
B,A,OUT=sys.argv[1],sys.argv[2],sys.argv[3]
views=sys.argv[4].split(",")
tiles=[]
for v in views:
    b=os.path.join(B,f"beauty_v0_{v}.png"); a=os.path.join(A,f"beauty_v3_{v}.png")
    if not(os.path.exists(b) and os.path.exists(a)): print("skip",v); continue
    tiles.append((v,Image.open(b).convert("RGB"),Image.open(a).convert("RGB")))
if not tiles: raise SystemExit("no matched pairs")
w,h=tiles[0][1].size; sc=0.62; w,h=int(w*sc),int(h*sc)
PAD=26
sheet=Image.new("RGB",(w*2+PAD*3, (h+34)*len(tiles)+PAD),(22,22,24))
d=ImageDraw.Draw(sheet)
for i,(v,b,a) in enumerate(tiles):
    y=PAD+i*(h+34)
    sheet.paste(b.resize((w,h),Image.LANCZOS),(PAD,y+28))
    sheet.paste(a.resize((w,h),Image.LANCZOS),(PAD*2+w,y+28))
    d.text((PAD,y+8),f"{v}   BEFORE  car_merged.glb (Interior skin behind the glass)",fill=(235,235,235))
    d.text((PAD*2+w,y+8),f"{v}   AFTER  car_cabin.glb (fragments removed, aperture opened, cabin built)",fill=(235,235,235))
sheet.save(OUT,quality=92)
print("wrote",OUT,sheet.size,"pairs:",len(tiles))
