FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl make \
    && command -v make \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --requirement /tmp/requirements.lock.txt \
    && python -m pip check \
    && test "$(python -c 'import sys; print(sys.version.split()[0])')" = "3.12.13" \
    && test "$(python -c "import importlib.metadata as m; print(m.version('retracesoftware'))")" = "0.2.29" \
    && test "$(python -c "import importlib.metadata as m; print(m.version('retracesoftware-dap'))")" = "0.2.29"

COPY . /app
WORKDIR /app
CMD ["python", "-m", "agent.main"]
