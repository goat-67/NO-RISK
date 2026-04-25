from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io

app = FastAPI()

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    filename = file.filename.lower()

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))

        elif filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(contents))

        else:
            return {"error": "Unsupported file type"}

        return {
            "filename": file.filename,
            "rows": df.head(10).to_dict(orient="records"),
            "total_rows": len(df)
        }

    except Exception as e:
        return {"error": str(e)}
