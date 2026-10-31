# `json-table` reads JSON and JSON Lines files into table sheets (json_table/Readme.md).
FROM docker.io/library/rust:1.91.0-trixie AS json-table
WORKDIR /src
COPY json_table/Cargo.toml json_table/Cargo.lock ./
COPY json_table/src ./src
RUN cargo build --release --locked

FROM python:3.13 AS image-preview-tools
# This release restores ordered path rules after the canonical-path policy regression.
RUN apt-get update -yy && apt-get install -yy --no-install-recommends \
    build-essential ca-certificates curl pkg-config libbz2-dev libdjvulibre-dev \
    libfftw3-dev libfontconfig1-dev libfreetype6-dev libheif-dev libjbig-dev \
    libjpeg62-turbo-dev liblcms2-dev liblqr-1-0-dev libltdl-dev liblzma-dev \
    libopenexr-dev libopenjp2-7-dev libpango1.0-dev libpng-dev libraw-dev \
    libtiff-dev libwebp-dev libwmf-dev libx11-dev libxml2-dev libxt-dev zlib1g-dev libzstd-dev
RUN curl -fsSL https://github.com/ImageMagick/ImageMagick/archive/refs/tags/7.1.2-34.tar.gz -o /tmp/imagemagick.tar.gz \
    && echo 'f5163a573a1c1bff16358d0a592b2fb168ad0fd3b9dc5ff57dc7820eebc5cf79  /tmp/imagemagick.tar.gz' | sha256sum -c - \
    && tar -xf /tmp/imagemagick.tar.gz -C /tmp \
    && cd /tmp/ImageMagick-7.1.2-34 \
    && ./configure --prefix=/opt/imagemagick --with-quantum-depth=16 --disable-hdri --with-modules --without-perl --disable-docs \
    && make -j4 && make install \
    && ln -sf /etc/ImageMagick-7/policy.xml /opt/imagemagick/etc/ImageMagick-7/policy.xml

FROM python:3.13
RUN pip install uv
# poppler-utils provides `pdftotext`, which parse_pdf.py has always shelled out to and
# which was never installed -- so PDF text extraction silently produced nothing for
# every PDF ever ingested (`_maybe_pdftotext` swallows FileNotFoundError and returns
# None). Extractous picked up some of it under its own label, which is why the gap
# looked like "PDFs have little text" rather than a missing binary.
#
# tesseract-ocr-eng is deliberately NOT installed. With the
# binary present, native Tika OCRs scanned PDFs implicitly and attributes the text to
# `extractous`, where no per-dataset language setting can reach it. OCR is an HTTP
# service (main_services/ocr_tesseract, ai_services/easyocr_server) and every OCR
# variant is attributed to the engine and languages that produced it.
RUN  apt-get update -yy && apt-get install -yy sed &&  sed -i 's/^Components: main$/& contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources && apt-get update -yy &&  apt-get install -yy 7zip 7zip-rar qpdf poppler-utils ffmpeg curl wget file build-essential pst-utils=0.6.76-1.2 libreoffice-writer-nogui openssl imagemagick librsvg2-bin
# imagemagick and librsvg2-bin (`rsvg-convert`) make the JPEG image previews.
# Keep dependencies outside the shared source mount so worker startup cannot replace another container's environment.
ENV UV_PROJECT_ENVIRONMENT=/opt/pysetup/.venv
WORKDIR /app
# The dependency layer stays separate from the source layer, so a source-only change
# rebuilds nothing above this line: `uv.lock` and `pyproject.toml` change far less often
# than the code, and `--no-install-project` installs every dependency without needing
# the source tree that names the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
# libreoffice-impress-nogui converts PowerPoint and OpenDocument presentations to PDF.
# This line stays above `ADD . .`, so a source change does not run it again.
RUN apt-get update -yy && apt-get install -yy libreoffice-impress-nogui
COPY --from=json-table /src/target/release/json-table /usr/local/bin/json-table
COPY --from=image-preview-tools /opt/imagemagick /opt/imagemagick
# Login shells reset PATH. Keep their converter selection consistent with the worker.
RUN ln -s /opt/imagemagick/bin/magick /usr/local/bin/magick
ENV PATH=/opt/imagemagick/bin:$PATH
ADD . .
RUN uv run main.py version
