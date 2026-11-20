FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    FIELDBENCH_DATA=/data

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml README.md ./
COPY fieldbench ./fieldbench
# Editable install: the spec, samples and procedures next to the package are found at runtime.
RUN pip install --no-cache-dir -e .

COPY spec ./spec
COPY samples ./samples
COPY procedures ./procedures

RUN useradd --create-home bench && mkdir /data && chown bench /data
USER bench

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health')"
CMD ["sh", "-c", "uvicorn fieldbench.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
