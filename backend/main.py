from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import pandas as pd
import io
import os
import signal
import hmac
import logging

# =========================
# APP INIT
# =========================
app = FastAPI()

# =========================
# 🔐 ENV VARIABLES (REQUIRED)
# =========================
API_KEY = os.getenv("API_KEY")
SECRET_HEADER = os.getenv("SECRET_HEADER")

if not API_KEY or not SECRET_HEADER:
    raise RuntimeError("Missing required environment variables")

# =========================
# 🔒 CORS LOCKDOWN
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://goat-67.github.io"],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["*"],
)

# =========================
# 🔒 LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logging.info(f"{request.client.host} {request.method} {request.url.path} {response.status_code}")
    return response

# =========================
# 🔒 RATE LIMITING
# =========================
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc):
    return JSONResponse(
        status_code=429,
        content={"error": "Too many requests"}
    )

# =========================
# 🔒 LIMITS
# =========================
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_ROWS = 10000
MAX_COLUMNS = 50
MAX_CELL_LENGTH = 200

# =========================
# 🔒 TIMEOUT PROTECTION
# =========================
def timeout_handler(signum, frame):
    raise TimeoutError("Processing timeout")

signal.signal(signal.SIGALRM, timeout_handler)

# =========================
# 🔐 CONSTANT-TIME AUTH
# =========================
def verify(value: str, expected: str):
    return hmac.compare_digest(value or "", expected)

# =========================
# ROUTES
# =========================
@app.get("/")
def home():
    return {"status": "ok"}

@app.post("/upload")
@limiter.limit("3/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    x_api_key: str = Header(None),
    x_internal_secret: str = Header(None)
):
    # 🔐 DOUBLE AUTH CHECK
    if not verify(x_api_key, API_KEY) or not verify(x_internal_secret, SECRET_HEADER):
        raise HTTPException(status_code=403, detail="Unauthorized")

    try:
        contents = await file.read()

        # 🔒 FILE SIZE CHECK
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large")

        filename = (file.filename or "").lower()

        # 🔒 FILENAME SAFETY
        if any(x in filename for x in ["..", "/", "\\"]):
            raise HTTPException(status_code=400, detail="Invalid filename")

        # 🔒 EXTENSION CHECK
        if not filename.endswith((".csv", ".xlsx")):
            raise HTTPException(status_code=400, detail="Invalid file type")

        # 🔒 MIME CHECK
        allowed_types = {
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail="Invalid file type")

        # 🔒 TIMEOUT START
        signal.alarm(5)

        try:
            # 🔒 SAFE PARSING
            if filename.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(contents), dtype=str)
            else:
                df = pd.read_excel(io.BytesIO(contents), dtype=str, engine="openpyxl")

        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted file")

        finally:
            signal.alarm(0)

        # 🔒 LIMIT DATA SIZE
        if df.shape[0] > MAX_ROWS:
            raise HTTPException(status_code=400, detail="Too many rows")

        if df.shape[1] > MAX_COLUMNS:
            raise HTTPException(status_code=400, detail="Too many columns")

        # 🔒 CLEAN DATA
        df.columns = [str(col).strip()[:50] for col in df.columns]
        df = df.fillna("").astype(str)
        df = df.map(lambda x: x[:MAX_CELL_LENGTH])

        preview = df.head(10).to_dict(orient="records")

        return {
            "filename": file.filename,
            "preview": preview,
            "total_rows": int(df.shape[0])
        }

    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=408, detail="Processing timeout")

    except Exception:
        raise HTTPException(status_code=500, detail="Server error")
