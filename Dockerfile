# Build image for the Trafilatura-Local extraction service.
#
#   docker build -t trafilatura-local:0.3.0 .
#   docker run --rm -p 8990:8990 -e HOST=0.0.0.0 trafilatura-local:0.3.0
#
# The image carries the pinned dependency tree (requirements.lock) and the
# service code, so a pod starts serving immediately: no `pip install` on the
# serving path, and no dependency on the cluster's internal registry for the
# dependency tree.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8990

WORKDIR /app

# Dependencies first: they change far less often than the code, so they stay
# cached across code-only rebuilds.
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --target /deps -r /app/requirements.lock

COPY server.py extraction.py /app/

ENV PYTHONPATH=/deps

# Run as a non-root user, matching the pod securityContext.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin trafilatura \
    && chown -R 10001:10001 /app
USER 10001

EXPOSE 8990

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8990/health').status==200 else 1)"

CMD ["python", "server.py"]
