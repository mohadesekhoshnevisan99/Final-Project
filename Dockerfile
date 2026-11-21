FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=90
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY research_similarity ./research_similarity

FROM runtime AS api
CMD ["uvicorn", "research_similarity.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
ARG APP_INSTALL_MODEL=true
COPY requirements-model.txt ./
RUN if [ "$APP_INSTALL_MODEL" = "true" ]; then \
      pip install --no-cache-dir 'pip==25.3' && \
      pip install --no-cache-dir 'torch==2.7.1+cpu' --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir -r requirements-model.txt; \
    fi
ENV HF_HOME=/models
CMD ["python", "-m", "research_similarity.worker"]

FROM runtime AS test
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY scripts ./scripts
CMD ["python", "-m", "pytest", "-q"]
