import sys, numpy as np, json; sys.path.insert(0,'.')
from measure import *

PICK={
 'F':{'lampL_inner':(1469,1458),'lampR_inner':(417.6,1368.0),'lampL_outer':(2402,1315),
      'badge_L':(762.6,1498.6),'badge_R':(937.4,1498.6),'badge_T':(850.0,1399.1),'badge_B':(850.0,1598.1)},
 'P':{'lampR_inner':(904.6,568.9),'lampL_inner':(1318.8,564.7),'lampR_outer':(663.2,534.2),
      'badge_L':(1091.3,584.6),'badge_R':(1156.8,584.6),'badge_T':(1124.0,553.1),'badge_B':(1124.0,616.0),
      'intake_top_R':(824.0,670.0),'towcover':(912.4,658.5),'sensor_lowR':(810.7,687.8),
      'lampR_lowest':(787.0,611.0),'bodyedge_far':(1428.0,600.0)},
}
CURVE=['bartop','chrome','barbot','grillebot','bumperbot']

def curve_v(k,nm,s):
    A=np.load('%s_%s.npy'%(k,nm)); S=rect(k,A); o=np.argsort(S[:,0])
    if s<S[o,0].min() or s>S[o,0].max(): return None
    return float(np.interp(s,S[o,0],S[o,1]))

def run():
    out={'per_image':{}}
    for k in 'FP':
        d={'curves':{},'points':{}}
        for nm in CURVE:
            try: np.load('%s_%s.npy'%(k,nm))
            except Exception: continue
            d['curves'][nm]={'v_at_s':{str(s):curve_v(k,nm,s) for s in (-300,-150,0,150,300)}}
        for n,p in PICK[k].items():
            s,v=rect(k,[p])[0]; d['points'][n]={'s':float(s),'v':float(v),'px':list(p)}
        out['per_image'][k]=d
    return out
if __name__=='__main__':
    o=run()
    for k in 'FP':
        print('==== ',k)
        b0=o['per_image'][k]['curves']['bartop']['v_at_s']['0']
        print('   datum: bonnet leading edge at s=0  ->  v = %.1f (plate frame)'%b0)
        for nm,c in o['per_image'][k]['curves'].items():
            v=c['v_at_s']['0']
            if v is not None: print('   %-10s  below datum: %7.1f mm'%(nm,v-b0))
        print('   plate top   below datum: %7.1f ; plate bottom: %7.1f'%(-b0, PLATE_H[k]-b0))
        for n,pv in o['per_image'][k]['points'].items():
            print('   %-13s s=%8.1f  below datum=%7.1f'%(n,pv['s'],pv['v']-b0))
    json.dump(o,open('raw_measures.json','w'),indent=1)
