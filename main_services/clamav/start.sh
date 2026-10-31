#!/bin/sh
# Start clamd with the configured thread count, then the HTTP front in the foreground.
set -e
# Two threads above the scan slots answer VERSION and the health check while every slot scans.
threads=$(( ${CLAMAV_CONCURRENCY:-4} + 2 ))
sed -i "s/^#\?MaxThreads .*/MaxThreads ${threads}/" /etc/clamav/clamd.conf
grep -q "^MaxThreads ${threads}" /etc/clamav/clamd.conf || echo "MaxThreads ${threads}" >> /etc/clamav/clamd.conf
mkdir -p /run/clamav && chown clamav:clamav /run/clamav /var/lib/clamav
if [ "${CLAMAV_UPDATE_SIGNATURES:-false}" = "true" ]; then
  # An update failure keeps the signatures of the image.
  freshclam --daemon --checks=12 --stdout || echo "freshclam did not start; the image signatures stay in use"
fi
clamd --config-file=/etc/clamav/clamd.conf
exec python3 /app/scan_http.py
