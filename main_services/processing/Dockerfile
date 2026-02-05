FROM python:3.13
RUN pip install uv
RUN  apt-get update -yy && apt-get install -yy sed &&  sed -i 's/^Components: main$/& contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources && apt-get update -yy &&  apt-get install -yy p7zip-full p7zip-rar qpdf ffmpeg tesseract-ocr-eng curl wget file build-essential
WORKDIR /app
ADD . .
RUN uv run main.py version
