"""Validate and atomically persist generated GLB files."""
from __future__ import annotations
import fcntl,json,os,shutil,stat,struct,tempfile,uuid
from contextlib import contextmanager
from pathlib import Path
MAX_GLB_BYTES=64*1024*1024
DEFAULT_BUDGET=20*1024**3
MIN_FREE_BYTES=512*1024**2

def validate_glb(data):
    if not isinstance(data,bytes) or not 20<=len(data)<=MAX_GLB_BYTES: raise ValueError("GLB size is invalid.")
    magic,version,length=struct.unpack_from("<4sII",data)
    if magic!=b"glTF" or version!=2 or length!=len(data): raise ValueError("Invalid GLB header.")
    chunks=[]; offset=12
    while offset<length:
        if offset+8>length: raise ValueError("Truncated GLB chunk header.")
        size,kind=struct.unpack_from("<I4s",data,offset); offset+=8
        if size%4 or offset+size>length: raise ValueError("Invalid GLB chunk length.")
        chunks.append((kind,data[offset:offset+size])); offset+=size
    if [k for k,_ in chunks] != [b"JSON",b"BIN\x00"]: raise ValueError("Expected embedded JSON/BIN GLB.")
    document=json.loads(chunks[0][1])
    if document.get("asset",{}).get("version")!="2.0": raise ValueError("Invalid glTF metadata.")
    buffers=document.get("buffers",[])
    if len(buffers)!=1 or "uri" in buffers[0]: raise ValueError("GLB must use one embedded buffer.")
    bl=buffers[0].get("byteLength")
    if type(bl) is not int or not 0<bl<=len(chunks[1][1]) or len(chunks[1][1])-bl>3: raise ValueError("GLB buffer length is inconsistent.")
    accessors=document.get("accessors",[])
    primitives=[p for m in document.get("meshes",[]) for p in m.get("primitives",[])]
    if not primitives: raise ValueError("GLB has no mesh primitives.")
    for p in primitives:
        i=p.get("attributes",{}).get("POSITION")
        if type(i) is not int or not 0<=i<len(accessors) or accessors[i].get("type")!="VEC3" or accessors[i].get("count",0)<3:
            raise ValueError("GLB has no usable vertex data.")
    return document

@contextmanager
def output_lock(directory):
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/".trellis-output.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)

def owned_outputs(directory):
    for path in directory.glob("trellis-*.glb"):
        try: info=path.lstat()
        except FileNotFoundError: continue
        if stat.S_ISREG(info.st_mode): yield path,info

def persist_glb(data,directory):
    validate_glb(data)
    budget=int(os.getenv("TRELLIS_OUTPUT_BUDGET_BYTES",str(DEFAULT_BUDGET)))
    if budget<=0: raise ValueError("TRELLIS_OUTPUT_BUDGET_BYTES must be positive.")
    with output_lock(directory):
        if sum(i.st_size for _,i in owned_outputs(directory))+len(data)>budget: raise OSError("TRELLIS output budget reached.")
        if shutil.disk_usage(directory).free<MIN_FREE_BYTES+len(data): raise OSError("Insufficient free space.")
        destination=directory/f"trellis-{uuid.uuid4().hex}.glb"; temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=directory,prefix=".trellis-",suffix=".tmp",delete=False) as f:
                temporary=Path(f.name); f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(temporary,destination)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
        return destination
