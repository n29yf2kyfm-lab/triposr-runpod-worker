# The GLB machine as one image. Build from the repository root:
#
#   docker build -f pipeline/realcar/Dockerfile -t glbmachine .
#   docker run -p 8080:8080 -v glbdata:/data -e GLBMACHINE_KEYS=your-key glbmachine
#   docker run --rm -v glbdata:/data glbmachine make "Ford Fiesta 2015 blue"
#
# No Blender: Python (numpy, scipy, Pillow), Node (gltf-transform, draco,
# meshoptimizer, the Khronos validator) and Chromium for the check sheets.
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm

# Node 22 from the official image (Debian's own is 18, past its end of life,
# and its npm cannot read the package.json override)
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends chromium fonts-dejavu-core ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pipeline/realcar/requirements.txt pipeline/realcar/requirements.txt
RUN pip install --no-cache-dir -r pipeline/realcar/requirements.txt

COPY pipeline/realcar/package.json pipeline/realcar/package-lock.json pipeline/realcar/
COPY pipeline/realcar/vendor pipeline/realcar/vendor
RUN cd pipeline/realcar && npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

COPY pipeline/template/gltf.py pipeline/template/gltf.py
COPY platform/catalogue/catalogue.v2.json platform/catalogue/catalogue.v2.json
COPY platform/catalogue/uk_targets/targets.csv platform/catalogue/uk_targets/top2000_cars.csv platform/catalogue/uk_targets/
COPY pipeline/realcar pipeline/realcar

ENV GLBMACHINE_HOME=/data CHROME_PATH=/usr/bin/chromium PORT=8080 PYTHONUNBUFFERED=1
RUN useradd -m -u 1000 glb && mkdir -p /data && chown -R glb /data /app/pipeline/realcar
USER glb
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["python3", "pipeline/realcar/glbmachine.py"]
CMD ["serve"]
