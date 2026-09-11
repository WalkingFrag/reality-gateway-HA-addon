FROM ghcr.io/home-assistant/base:latest

ARG BUILD_ARCH=amd64
ENV SING_BOX_VERSION=1.14.0

RUN apk add --no-cache \
        wireguard-tools \
        iptables \
        iproute2 \
        curl \
    && case "${BUILD_ARCH}" in \
        amd64)  SING_BOX_ARCH="amd64" ;; \
        aarch64) SING_BOX_ARCH="arm64" ;; \
        armv7)  SING_BOX_ARCH="armv7" ;; \
        *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/sing-box.tar.gz \
        "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}-musl.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && mv "/tmp/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}-musl/sing-box" /usr/local/bin/sing-box \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box.tar.gz "/tmp/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}-musl"

COPY rootfs /
RUN chmod +x /etc/cont-init.d/10-setup.sh \
    /etc/services.d/singbox/run \
    /etc/services.d/routing/run
