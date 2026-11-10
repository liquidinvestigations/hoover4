# In-document PDF search with the native PDFium library. The pypdfium2 wheel contains
# PDFium, so the image needs no system packages.
#
# pypdfium2 5.5.0 (PDFium 147.0.7690) is pinned. Its text has the same spaces between
# small OCR words as the PDFium build that the PDF viewer uses. The 4.x releases and the
# other 5.x releases up to 5.15.2 leave out some of these spaces, and a whole-word search
# then misses a word such as "the" in "theear".
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir "pypdfium2==5.5.0" "pytest>=8.3"

COPY search.py server.py /app/
COPY tests /app/tests

EXPOSE 13500

CMD ["python", "-u", "/app/server.py"]
