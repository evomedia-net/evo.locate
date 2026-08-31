# Evomedia.net evo.locate — https://github.com/evomedia-net/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

FROM python:3.13-slim AS base

# Databases live on a volume, not in the image: they are ~124 MB and are
# republished monthly, so baking them in would make the image stale by design.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EVO_LOCATE_DATA_DIR=/data

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The build stamp travels into the image, so /health reports the version that
# was actually deployed. It is also what makes a version bump change the image:
# without it the layers hash identically, compose sees no reason to recreate the
# container, and the old build keeps serving while the deploy reports success.
COPY build-version.json ./build-version.json

# Unprivileged, and owning /data so the first-boot download can write there.
RUN useradd --system --uid 10001 --no-create-home evolocate \
 && mkdir -p /data \
 && chown -R evolocate:evolocate /data
USER evolocate

VOLUME ["/data"]
EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9100/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9100"]