import glbcore as G, holes as H, json, time, sys
out={}
t0=time.time()
out['control']=H.hole_test(G.Glb('src/car_merged.glb'), G.Glb('nc/NC7_holed.glb'), n=32)
out['control_secs']=time.time()-t0
t0=time.time()
out['null']=H.hole_test(G.Glb('src/car_merged.glb'), G.Glb('src/car_merged.glb'), n=32)
out['null_secs']=time.time()-t0
json.dump(out,open('meta/hole_selftest.json','w'),indent=1)
open('meta/HOLE_SELFTEST_DONE','w').write('ok\n')
print("HOLE_SELFTEST_EXIT=0")
