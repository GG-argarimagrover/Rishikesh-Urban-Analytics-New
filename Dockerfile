FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 RUI_DATA_DIR=/data PORT=8000
WORKDIR /app

# manylinux wheels for geopandas / pyogrio / rasterio bundle GDAL, so no system GDAL is needed
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
COPY data/sample ./data/sample
RUN pip install .

RUN useradd -m app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz')"

# one worker (job state lives on disk, jobs run in a thread pool) + several threads for page requests.
# Landsat downloads can be slow → long timeout.
CMD ["sh", "-c", "gunicorn 'rishikesh_urban.app:get_app()' --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 300"]
