"""Bounded image decoding and allowlisted HTTPS fetching."""
from __future__ import annotations
import base64, binascii, ipaddress, os, re, socket, ssl, warnings
from io import BytesIO
from urllib.parse import urlsplit
import urllib3
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES=10*1024*1024
MAX_PIXELS=16_777_216
MAX_SIDE=8192
MAX_URL_LENGTH=8192
ALLOWED_FORMATS={"PNG","JPEG","WEBP"}
HOST_PATTERN=re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}\Z")
class InputError(ValueError): pass

def validate_job(job):
    if not isinstance(job,dict) or not isinstance(job.get("input"),dict):
        raise InputError("Job and input must be JSON objects.")
    data=job["input"]
    for key in ("prompt","image_url","image_b64"):
        if key in data and not isinstance(data[key],str): raise InputError(f"{key} must be a string.")
    supplied=[k for k in ("prompt","image_url","image_b64") if data.get(k,"").strip()]
    if len(supplied)!=1: raise InputError("Provide exactly one of prompt, image_url or image_b64.")
    if len(data.get("prompt",""))>4000: raise InputError("prompt exceeds 4000 characters.")
    if len(data.get("image_url",""))>MAX_URL_LENGTH: raise InputError("Image URL is too long.")
    if len(data.get("image_b64",""))>4*((MAX_IMAGE_BYTES+2)//3): raise InputError("Encoded image exceeds 10 MiB.")
    seed=data.get("seed",1)
    if type(seed) is not int or not 0<=seed<=2**32-1: raise InputError("seed must be an integer between 0 and 4294967295.")
    return data, "text" if supplied[0]=="prompt" else "image"

def decode_image(payload):
    if not payload or len(payload)>MAX_IMAGE_BYTES: raise InputError("Image must contain between 1 byte and 10 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error",Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as image:
                if image.format not in ALLOWED_FORMATS: raise InputError("Only PNG, JPEG and WebP images are supported.")
                w,h=image.size
                if not (0<w<=MAX_SIDE and 0<h<=MAX_SIDE) or w*h>MAX_PIXELS: raise InputError("Image dimensions exceed limits.")
                if getattr(image,"n_frames",1)!=1: raise InputError("Animated images are not supported.")
                image.load()
                fixed=ImageOps.exif_transpose(image)
                return fixed.convert("RGBA" if "A" in fixed.getbands() or "transparency" in fixed.info else "RGB")
    except InputError: raise
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise InputError("Image data is invalid or unsafe to decode.") from exc

def decode_base64(value):
    if len(value)>4*((MAX_IMAGE_BYTES+2)//3): raise InputError("Encoded image exceeds 10 MiB.")
    try: payload=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error) as exc: raise InputError("image_b64 must be valid raw base64.") from exc
    return decode_image(payload)

def _destination(url):
    if not isinstance(url,str) or len(url)>MAX_URL_LENGTH or any(ord(c)<=32 or ord(c)>=127 for c in url) or "\\" in url:
        raise InputError("Image URL must be an ASCII HTTPS URL without whitespace.")
    try:
        p=urlsplit(url); host=(p.hostname or "").lower()
        if p.scheme!="https" or p.username is not None or p.password is not None or p.port not in (None,443) or p.fragment or not HOST_PATTERN.fullmatch(host):
            raise InputError("Image URL must use an approved HTTPS hostname.")
    except ValueError as exc: raise InputError("Image URL is invalid.") from exc
    allowed={h.strip().lower() for h in os.getenv("TRELLIS_IMAGE_HOSTS","").split(",") if h.strip()}
    if not allowed or any(not HOST_PATTERN.fullmatch(h) for h in allowed): raise InputError("URL input requires TRELLIS_IMAGE_HOSTS; image_b64 also works.")
    if host not in allowed: raise InputError("Image hostname is not approved.")
    try:
        answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        addresses=list(dict.fromkeys(a[4][0] for a in answers))
        if not addresses: raise OSError("No addresses")
        for address in addresses:
            ip=ipaddress.ip_address(address); effective=getattr(ip,"ipv4_mapped",None) or ip
            if not effective.is_global or effective.is_multicast or effective.is_reserved or effective.is_loopback or effective.is_link_local or "%" in address:
                raise InputError("Image hostname does not resolve exclusively to public addresses.")
    except InputError: raise
    except (OSError,ValueError) as exc: raise InputError("Image hostname could not be resolved safely.") from exc
    target=p.path or "/"
    if p.query: target+="?"+p.query
    return host,addresses[0],target

def fetch_image(url):
    host,address,target=_destination(url)
    pool=urllib3.HTTPSConnectionPool(address,port=443,server_hostname=host,assert_hostname=host,ssl_context=ssl.create_default_context(),maxsize=1)
    response=None
    try:
        response=pool.request("GET",target,headers={"Host":host,"Accept":"image/png,image/jpeg,image/webp","Accept-Encoding":"identity","User-Agent":"TRELLIS-Worker/2"},
            timeout=urllib3.Timeout(connect=5,read=5),retries=False,redirect=False,preload_content=False,assert_same_host=False)
        if response.status!=200: raise InputError("Image server did not return HTTP 200; redirects are not followed.")
        if response.headers.get("Content-Encoding","identity").lower()!="identity": raise InputError("Compressed HTTP image responses are not accepted.")
        length=response.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length)>MAX_IMAGE_BYTES): raise InputError("Image response exceeds the download limit.")
        payload=response.read(MAX_IMAGE_BYTES+1,decode_content=False)
        if len(payload)>MAX_IMAGE_BYTES: raise InputError("Image download exceeds 10 MiB.")
        return decode_image(payload)
    except InputError: raise
    except (urllib3.exceptions.HTTPError,OSError,ValueError) as exc: raise InputError("Image could not be downloaded securely.") from exc
    finally:
        if response is not None: response.close()
        pool.close()
