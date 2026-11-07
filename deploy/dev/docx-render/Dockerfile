# Dev-only: LibreOffice headless để render .docx → PDF (rồi PNG) cho vòng
# "VLM preview" so layout Word với trang gốc. Không dùng ở prod.
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer \
      fonts-noto-cjk \
      fonts-dejavu-core \
      fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /data
ENTRYPOINT ["soffice", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", "/data"]
