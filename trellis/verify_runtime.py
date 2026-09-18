"""Package/import gate. This is NOT a GPU inference test."""
import importlib, importlib.metadata as metadata, json, sys
sys.path.insert(0,"/app/TRELLIS")
DISTRIBUTIONS=("torch","torchvision","xformers","spconv-cu120","kaolin","diffoctreerast","diff-gaussian-rasterization","nvdiffrast","runpod","Pillow","urllib3","setuptools","wheel","ninja")
MODULES=("torch","torchvision","xformers.ops","spconv.pytorch","kaolin","diffoctreerast","diff_gaussian_rasterization","nvdiffrast.torch","runpod","PIL.Image","urllib3","trellis.pipelines","trellis.utils.postprocessing_utils")
def verify():
    installed={name:metadata.version(name) for name in DISTRIBUTIONS}
    if any(d.metadata.get("Name","").lower()=="unknown" for d in metadata.distributions()): raise RuntimeError("Found UNKNOWN package metadata.")
    for name in MODULES: importlib.import_module(name)
    import torch
    if torch.__version__!="2.4.0+cu121" or torch.version.cuda!="12.1": raise RuntimeError("Unexpected PyTorch/CUDA build.")
    print(json.dumps({"check":"package_and_import_only","packages":installed},sort_keys=True))
    return installed
if __name__=="__main__": verify()
