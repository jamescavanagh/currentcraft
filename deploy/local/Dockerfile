FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/datamesh
# Explicit copies: private references and local credentials never enter image layers.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[postgres,nats,api]' && useradd --uid 10001 --create-home datamesh
COPY deploy/local/runtime.py ./runtime.py
USER 10001:10001
ENTRYPOINT ["python", "/opt/datamesh/runtime.py"]
