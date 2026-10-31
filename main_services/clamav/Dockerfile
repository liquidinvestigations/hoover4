# ClamAV with a small HTTP front (scan_http.py). The signature database of the build
# time is part of the image, so a scan works without network access. freshclam updates
# it at run time only when CLAMAV_UPDATE_SIGNATURES is true.
FROM docker.io/clamav/clamav:1.4.3
RUN apk add --no-cache python3 \
 && freshclam --stdout --no-warnings \
 && sed -i \
      -e 's/^#\?StreamMaxLength .*/StreamMaxLength 501M/' \
      -e 's/^#\?MaxFileSize .*/MaxFileSize 501M/' \
      -e 's/^#\?MaxScanSize .*/MaxScanSize 2000M/' \
      -e 's/^#\?AlertExceedsMax .*/AlertExceedsMax yes/' \
      -e 's/^#\?Foreground .*/Foreground no/' \
      /etc/clamav/clamd.conf \
 && grep -q '^StreamMaxLength 501M' /etc/clamav/clamd.conf \
 && grep -q '^AlertExceedsMax yes' /etc/clamav/clamd.conf
COPY scan_http.py start.sh /app/
ENTRYPOINT ["/bin/sh", "/app/start.sh"]
