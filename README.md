# dots_ocr_api
This is a gateway for the dots.OCR model.  Preprocesses PDFs into images and submits to backend dots.OCR endpoint in a concurrent and resilient way

Here’s a **ready-to-use README** **customized for your actual repo at** [https://github.com/ui-insight/dots_ocr_api](https://github.com/ui-insight/dots_ocr_api): ([GitHub][1])

---

# dots_ocr_api

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

A lightweight, resilient **API gateway for the dots.OCR model**. It preprocesses PDFs into images, performs concurrent OCR requests against a backend service, and returns Markdown text.

This project is intended as a scalable microservice wrapper around a vision-capable LLM OCR backend such as a self-hosted dots.ocr inference server. ([GitHub][1])

---

## 🚀 Features

* **PDF → Markdown OCR API**

  * Convert whole PDF documents to clean Markdown text.
* **Concurrent page processing**

  * Processes multiple pages in parallel for throughput.
* **Resilient inference**

  * Retries OCR on problematic pages with multiple sampling strategies.
* **No disk I/O**

  * All uploads and intermediate data stay in memory.
* **Stateless**

  * Easy to deploy in containers, HPC nodes, or serverless contexts.

---

## 📦 Installation

### 1. Clone the repository

```bash
git clone https://github.com/ui-insight/dots_ocr_api.git
cd dots_ocr_api
```

### 2. Create a virtual environment (optional but recommended)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

This service uses environment variables to configure backend connectivity and processing behavior.

### Required

* `BACKEND_ENDPOINT`
  URL of your OCR backend (e.g., a vision LLM inference server).

* `BACKEND_MODEL`
  The model identifier to send with each OCR request.

Example:

```bash
export BACKEND_ENDPOINT="http://my-llm-backend:8000"
export BACKEND_MODEL="DotsOCR"
```

### Optional (with sensible defaults)

| Variable           | Default | Description                   |
| ------------------ | ------- | ----------------------------- |
| `OCR_DPI`          | `100`   | DPI for PDF rendering         |
| `OCR_TIMEOUT`      | `900`   | Timeout (s) per page OCR call |
| `OCR_PAGE_WORKERS` | `8`     | Parallel worker count         |
| `MAX_PDF_MB`       | `100`   | Max upload size (MB)          |
| `MAX_PAGES`        | `500`   | Max pages allowed             |

---

## 🚩 API Endpoints

### **GET /health**

Returns basic service configuration and status.

```bash
curl http://localhost:5010/health
```

**Sample JSON**

```json
{
  "ok": true,
  "endpoint": "http://my-llm-backend:8000",
  "model": "DotsOCR",
  "dpi": 100,
  "timeout": 900,
  "workers": 8
}
```

---

### **POST /dotsocr**

OCR a PDF and return Markdown.

#### Request

Send a PDF as either:

* **Multipart form upload** (`file=@document.pdf`)
* **Raw PDF bytes** in body

Example:

```bash
curl -X POST http://localhost:5010/dotsocr \
     -F "file=@document.pdf" \
     -H "Accept: text/markdown"
```

#### Optional query parameters

| Param     | Default | Description                |
| --------- | ------- | -------------------------- |
| `dpi`     | 100     | Rendering DPI              |
| `timeout` | 900     | Inference timeout per page |
| `workers` | 8       | Parallelism level          |

The response is returned as `text/markdown` with extracted text merged from all pages. ([GitHub][1])

---

## 🧠 Behavior & Reliability

* Pages processed in parallel using threads.
* If a page OCR attempt returns **very short or repetitive output**, it’s retried with different sampling configs.
* Pages that continue to fail are **omitted**, but the rest of the document still returns valid text.

This prioritizes **usable text** over strict completion. (e.g., if one page fails, the rest still succeed)

---

## 🛠️ Running Locally

```bash
python app.py
```

By default it listens on:

```
http://0.0.0.0:5010
```

Deploy behind a reverse proxy or container orchestrator as needed.

---

## 🐳 Docker (optional)

You can containerize this service by writing a simple Dockerfile:

```Dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5010
CMD ["python", "app.py"]
```

Build and run:

```bash
docker build -t dotsocr-api .
docker run -e BACKEND_ENDPOINT="http://..." -e BACKEND_MODEL="DotsOCR" -p 5010:5010 dotsocr-api
```

---

## 📦 Example Client (Python)

```python
import requests

url = "http://localhost:5010/dotsocr"
with open("document.pdf","rb") as f:
    r = requests.post(url, files={"file": f})
print(r.text)
```

---

## 📄 License

This project is licensed under **Apache-2.0**. ([GitHub][1])

---

## ❤️ Contributing

Contributions welcome! Please open issues or pull requests to:

* Improve reliability
* Add auth / rate limit support
* Add tests and CI workflows

---

## 📫 Maintainer

Luke Sheneman, sheneman@uidaho.edu


[1]: https://github.com/ui-insight/dots_ocr_api "GitHub - ui-insight/dots_ocr_api: This is a gateway for the dots.OCR model.  Preprocesses PDFs into images and submits to backend dots.OCR endpoint in a concurrent and resilient way"
