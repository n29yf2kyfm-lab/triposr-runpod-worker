# Seedance 2.0 video worker — this is an API proxy to Replicate, NOT local model
# inference, so it needs NO GPU and no CUDA base image. A slim CPU image keeps the
# build tiny and lets it run on RunPod's cheapest serverless workers.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py /app/handler.py

CMD ["python3", "-u", "/app/handler.py"]
