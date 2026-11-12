FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY photoslibrary_viewer ./photoslibrary_viewer
RUN pip install --no-cache-dir . && useradd --uid 1000 --create-home viewer

USER viewer
ENV PLV_HOST=0.0.0.0 PLV_PORT=8395 PLV_CACHE=/cache PLV_LIBRARY=/library
EXPOSE 8395
VOLUME ["/cache"]
CMD ["photoslibrary-viewer"]
