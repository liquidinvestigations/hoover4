# The bootstrap needs a shell, curl and jq; the Garage image is FROM scratch and has
# none of them. The binary is a static-PIE ELF, so it runs unmodified on Alpine.
ARG GARAGE_IMAGE=dxflrs/garage:v2.3.0
FROM ${GARAGE_IMAGE} AS bin
FROM alpine:3.22
RUN apk add --no-cache curl jq
COPY --from=bin /garage /usr/local/bin/garage
COPY init.sh /usr/local/bin/init.sh
ENTRYPOINT ["/usr/local/bin/init.sh"]
