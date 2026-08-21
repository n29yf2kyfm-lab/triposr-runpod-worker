import sys
from PIL import Image
R='/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/gates/g3v6/ref/'
FILES={'F':'REF_FRONT_golf_mk8_style_2020.jpg','P':'VW_PRESS_DB2019AU02064.jpg'}
def go(which,x0,y0,x1,y1,out,target=1400,grid=0):
    im=Image.open(R+FILES[which]).convert('RGB')
    c=im.crop((x0,y0,x1,y1))
    w,h=c.size
    s=target/max(w,h)
    c=c.resize((max(1,int(round(w*s))),max(1,int(round(h*s)))),Image.LANCZOS)
    if grid:
        from PIL import ImageDraw
        d=ImageDraw.Draw(c)
        step=grid  # in ORIGINAL px
        gx=x0 - (x0 % step) + step
        while gx<x1:
            px=(gx-x0)*s
            d.line([(px,0),(px,c.size[1])],fill=(255,0,255),width=1)
            d.text((px+2,2),str(gx),fill=(255,0,255))
            gx+=step
        gy=y0-(y0%step)+step
        while gy<y1:
            py=(gy-y0)*s
            d.line([(0,py),(c.size[0],py)],fill=(0,255,255),width=1)
            d.text((2,py+2),str(gy),fill=(0,255,255))
            gy+=step
    c.save(out)
    print(out,c.size,'scale=%.4f'%s,'origin',(x0,y0))
if __name__=='__main__':
    a=sys.argv[1:]
    go(a[0],int(a[1]),int(a[2]),int(a[3]),int(a[4]),a[5],int(a[6]) if len(a)>6 else 1400, int(a[7]) if len(a)>7 else 0)
