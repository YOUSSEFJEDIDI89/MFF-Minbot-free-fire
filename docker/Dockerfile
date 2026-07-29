# Multi-stage Dockerfile for VortexVPN.
# Stage 1: build the C++ accelerator.
# Stage 2: runtime image with Python, Java, and built artifacts.

FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential python3-dev pybind11-dev libssl-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY cpp_module/ ./cpp_module/
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip wheel setuptools \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pybind11 \
    && cd cpp_module && make

# ------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless socat curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --shell /usr/sbin/nologin vortex

WORKDIR /opt/vortexvpn
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/cpp_module/vortex_accel*.so /usr/local/lib/python3.11/site-packages/
COPY vortexvpn/        ./vortexvpn/
COPY java_monitor/     ./java_monitor/
COPY scripts/          ./scripts/
COPY configs/          ./configs/

RUN cd java_monitor && javac VortexMonitor.java -d /opt/vortexvpn/java_monitor/build \
    && mkdir -p /var/log/vortexvpn /var/run/vortexvpn /etc/vortexvpn \
    && chown -R vortex:vortex /opt/vortexvpn /var/log/vortexvpn /var/run/vortexvpn /etc/vortexvpn \
    && chmod +x scripts/*.sh java_monitor/run.sh

USER vortex
ENV PYTHONPATH=/opt/vortexvpn \
    VORTEX_LOG_LEVEL=INFO \
    VORTEX_TUNNEL_PORT=4433

EXPOSE 8080 4433 9101
VOLUME ["/etc/vortexvpn", "/var/log/vortexvpn"]

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "vortexvpn.web"]
