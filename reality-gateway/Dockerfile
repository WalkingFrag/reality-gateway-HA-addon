FROM golang:1.25-alpine AS awggo

RUN apk add --no-cache git make \
    && git clone https://github.com/amnezia-vpn/amneziawg-go.git /src/amneziawg-go \
    && cd /src/amneziawg-go \
    && git checkout b5928efb6ca19f0153958460c3d141f04abc5c2e \
    && make

FROM alpine:3.22 AS awgtools

RUN apk add --no-cache git make gcc musl-dev linux-headers \
    && git clone https://github.com/amnezia-vpn/amneziawg-tools.git /src/amneziawg-tools \
    && cd /src/amneziawg-tools \
    && git checkout ee0f0a9aa34ff0a0da4b3433b9512781cfe02843 \
    && make -C src

FROM ghcr.io/home-assistant/base:latest

ARG BUILD_ARCH=amd64
ENV SING_BOX_VERSION=1.14.0

RUN apk add --no-cache \
        wireguard-tools \
        iptables \
        iproute2 \
        curl \
        python3 \
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

COPY --from=awggo /src/amneziawg-go/amneziawg-go /usr/local/bin/amneziawg-go
COPY --from=awgtools /src/amneziawg-tools/src/wg /usr/local/bin/awg

COPY rootfs /
RUN chmod +x /etc/cont-init.d/10-setup.sh \
    /etc/services.d/singbox/run \
    /etc/services.d/routing/run
