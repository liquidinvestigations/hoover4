FROM pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-alpine-3.12.0-x86_64

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN apk add --update --no-cache python3 && ln -sf python3 /usr/bin/python
RUN python3 -m ensurepip
RUN pip3 install --no-cache --upgrade pip setuptools beautifulsoup4
RUN apk update \
  && ( apk search font-adobe | rev | cut -d- -f3- | rev | xargs apk add ) \
  && ( apk search font-noto | rev | cut -d- -f3- | rev | xargs apk add ) \
  && (  apk search font- | grep '^font-' | rev | cut -d- -f3- | rev | xargs apk add )

# The compose service mounts this directory over /app and overrides the entrypoint
# below, so the published image needs its own copy of the code and its own entrypoint,
# baked in rather than arriving from the host at container start.
WORKDIR /app
COPY pdf2html_server.py /app/pdf2html_server.py
ENTRYPOINT ["/usr/bin/python", "/app/pdf2html_server.py"]