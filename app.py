#################################################################
#
# Dots.OCR preprocessor and load balancer
#
# Luke Sheneman
# Research Computing and Data Services (RCDS)
# Institute for Interdisciplnary Data Sciences
# University of Idaho
#
# sheneman@uidaho.edu
#
##################################################################

import io
import os
import re
import time
import json
import base64
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
import requests
from PIL import Image
from flask import Flask, request, Response, jsonify
from dotenv import load_dotenv

# Load variables from .env file if it exists
load_dotenv()

# ============================================================
# CONFIG
# ============================================================
BACKEND_ENDPOINT = os.getenv(
    "BACKEND_ENDPOINT",
#    "http://aspen1.hpc.uidaho.edu:80"
    "https://mindrouter.nkn.uidaho.edu"
)

MODEL_NAME = os.getenv(
    "BACKEND_MODEL",
    "dots.OCR"
)

# Added API Token retrieval
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY", "")

DEFAULT_DPI = int(os.getenv("OCR_DPI", "200"))
DEFAULT_TIMEOUT = int(os.getenv("OCR_TIMEOUT", "900"))
DEFAULT_PAGE_WORKERS = int(os.getenv("OCR_PAGE_WORKERS", "8"))

MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "100"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "500"))

GLOBAL_API_LIMIT = threading.Semaphore(8)

app = Flask(__name__, static_folder=None)




# ============================================================
# LOGGING
# ============================================================
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def dbg(msg):
    log(f"[DEBUG] {msg}")



# ============================================================
# TEXT HELPERS
# ============================================================
def detect_repetition(text):
    if not text:
        return False

    t = text.strip()
    lower = t.lower()

    lines = [l.strip() for l in lower.splitlines() if l.strip()]
    if len(lines) >= 4:
        unique = set(lines)
        if max(lines.count(l) for l in unique) / len(lines) > 0.6:
            return True

    sentences = re.split(r"[.!?\n]+", lower)
    sentences = [s.strip() for s in sentences if len(s) > 8]
    if len(sentences) >= 4:
        unique = set(sentences)
        if max(sentences.count(s) for s in unique) / len(sentences) > 0.5:
            return True

    if re.search(r"(.)\1{25,}", t):
        return True

    words = re.findall(r"\b[a-z0-9]+\b", lower)
    if len(words) >= 30 and len(set(words)) / len(words) < 0.25:
        return True

    return False



def strip_html_tables(text):
    if not text:
        return text

    lower = text.lower()
    if "<table" not in lower:
        return text

    text = re.sub(r"</?(html|body).*?>", "", text, flags=re.I)
    text = re.sub(r"</?table.*?>", "\n", text, flags=re.I)
    text = re.sub(r"</?tr.*?>", "\n", text, flags=re.I)
    text = re.sub(r"</?td.*?>", " | ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)

    text = re.sub(r"\|\s*\|", "|", text)
    text = re.sub(r"\s*\|\s*", " | ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

    return text.strip()



def replace_bbox_json_with_text(text):
    if not text:
        return text

    def repl(match):
        blob = match.group(0)
        try:
            data = json.loads(blob)
            if isinstance(data, list):
                parts = []
                for item in data:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(item["text"].strip())
                return "\n".join(parts)
        except Exception:
            pass

        # If parsing fails, fall back to removing the block
        return ""

    # Replace JSON arrays that look like bbox outputs
    pattern = r"\[\s*\{.*?\"bbox\".*?\}\s*\]"
    return re.sub(pattern, repl, text, flags=re.S)


#PRIMARY_OCR_PROMPT = (
#    "Extract all readable text from the image.\n"
#    "Preserve line breaks and reading order.\n"
#    "If the image contains tables, output rows as plain text.\n"
#    "Do not include HTML.\n"
#    "Output Markdown-compatible plain text."
#)


PRIMARY_OCR_PROMPT = (
    "You are an OCR system.\n"
    "Your output must be human-readable Markdown only.\n"
    "Never return JSON or structured objects.\n\n"
    "Extract all readable text from the image.\n"
    "Preserve natural reading order and line breaks.\n"
    "If the image contains tables, render them as Markdown tables.\n"
    "Return ONLY Markdown."
)







# ============================================================
# BACKEND OCR CALL
# ============================================================
def run_inference(img, session, timeout, params):
    with GLOBAL_API_LIMIT:
        dbg("Encoding image to PNG/base64")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        payload = {
            "model": MODEL_NAME,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": params["prompt"]},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}"
                        }
                    }
                ]
            }],
            "temperature": params["temp"],
            "top_p": params["top_p"],
            "max_completion_tokens": 8192
        }


        # Add Authorization header if key is provided
        headers = {}
        if BACKEND_API_KEY:
            headers["Authorization"] = f"Bearer {BACKEND_API_KEY}"

        dbg(
            f"POST → {BACKEND_ENDPOINT}/v1/chat/completions "
            f"(img={len(img_b64)//1024} KB, timeout={timeout}s)"
        )

        start = time.time()
        r = session.post(
            f"{BACKEND_ENDPOINT}/v1/chat/completions",
            json=payload,
            timeout=timeout
        )

        dbg(f"Aspen HTTP {r.status_code}")
        r.raise_for_status()

        text = r.json()["choices"][0]["message"]["content"]
        duration = time.time() - start

        dbg(f"Aspen returned {len(text)} chars in {duration:.2f}s")

        #return strip_html_tables(text), duration
        cleaned = replace_bbox_json_with_text(strip_html_tables(text))
        return cleaned, duration


# ============================================================
# PAGE OCR
# ============================================================
def ocr_page(page_num, img, session, timeout):
    configs = [
        {"temp": 0.0, "top_p": 1.0, "prompt": PRIMARY_OCR_PROMPT},
        {"temp": 0.4, "top_p": 0.95, "prompt": PRIMARY_OCR_PROMPT},
        {"temp": 0.8, "top_p": 0.9, "prompt": PRIMARY_OCR_PROMPT},
    ]

    last_error = "Unknown"
    for i, cfg in enumerate(configs):
        try:
            dbg(f"Page {page_num}: attempt {i + 1}")
            text, duration = run_inference(img, session, timeout, cfg)

            if len(text) < 50:
                last_error = "Too short"
                continue

            if detect_repetition(text):
                last_error = "Repetitive output"
                continue

            log(f"[OK] Page {page_num} (attempt {i + 1}, {duration:.2f}s)")
            return page_num, text

        except Exception as e:
            last_error = str(e)
            wait = 2 * (2 ** i)
            log(
                f"[RETRY] Page {page_num} failed "
                f"({last_error}), sleeping {wait}s"
            )
            time.sleep(wait)

    log(f"[FAILED] Page {page_num}: {last_error}")
    return page_num, ""



# ============================================================
# PDF → MARKDOWN
# ============================================================
def pdf_bytes_to_markdown(pdf_bytes, dpi, timeout, workers):
    dbg("Opening PDF from bytes")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    dbg(f"PDF opened, pages={doc.page_count}")

    if doc.page_count > MAX_PAGES:
        raise ValueError(
            f"PDF has {doc.page_count} pages (max {MAX_PAGES})"
        )

    pages = []
    for i in range(doc.page_count):
        dbg(f"Rendering page {i + 1}")
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(
            io.BytesIO(pix.tobytes("png"))
        ).convert("RGB")
        pages.append((i + 1, img))

    dbg(f"Rendered {len(pages)} pages")
    session = requests.Session()
    results = []

    dbg(f"Starting ThreadPoolExecutor workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for pnum, img in pages:
            dbg(f"Submitting page {pnum}")
            futures.append(
                ex.submit(ocr_page, pnum, img, session, timeout)
            )

        dbg("Waiting for OCR results")
        for f in as_completed(futures):
            pnum, txt = f.result()
            dbg(f"Page {pnum} finished")
            results.append((pnum, txt))

    dbg("All pages complete, assembling markdown")
    results.sort(key=lambda x: x[0])

    out = []
    for _, txt in results:
        if txt:
            out.append(txt.strip())

    return "\n\n".join(out).strip() + "\n"



# ============================================================
# FLASK ROUTES
# ============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        ok=True,
        endpoint=BACKEND_ENDPOINT,
        model=MODEL_NAME,
        dpi=DEFAULT_DPI,
        timeout=DEFAULT_TIMEOUT,
        workers=DEFAULT_PAGE_WORKERS
    )



@app.route("/dotsocr", methods=["POST"])
def pdf_to_md():
    dpi = int(request.args.get("dpi", DEFAULT_DPI))
    timeout = int(request.args.get("timeout", DEFAULT_TIMEOUT))
    workers = int(request.args.get("workers", DEFAULT_PAGE_WORKERS))

    if "file" in request.files:
        pdf_bytes = request.files["file"].read()
    else:
        pdf_bytes = request.get_data()

    if not pdf_bytes:
        return jsonify(error="No PDF provided"), 400

    size_mb = len(pdf_bytes) / (1024 * 1024)
    if size_mb > MAX_PDF_MB:
        return jsonify(error="PDF too large"), 413

    try:
        log(
            f"[START] PDF received ({size_mb:.2f} MB) "
            f"dpi={dpi} workers={workers} timeout={timeout}"
        )
        md = pdf_bytes_to_markdown(
            pdf_bytes, dpi, timeout, workers
        )
        log("[DONE] PDF OCR complete")
        return Response(
            md,
            mimetype="text/markdown; charset=utf-8"
        )
    except Exception as e:
        log(f"[ERROR] {e}")
        return jsonify(error=str(e)), 500

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=False)

