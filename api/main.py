"""
FastAPI servisi - Fatura görseli alır, OCR ile ham metni çıkarır.
(LLM ile yapılandırma adımı henüz eklenmedi)
"""

import sys
import os
import shutil
import tempfile

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

# ocr_engine.py'yi import edebilmek için ocr klasörünü path'e ekliyoruz
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ocr"))
from ocr_engine import OCREngine

app = FastAPI(title="Invoice OCR Service")

# OCR motorunu uygulama başlarken bir kere yükle (her istekte yeniden yüklemeyelim)
ocr_engine = OCREngine(lang="en")


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Invoice OCR Service çalışıyor"}


@app.post("/analyze-invoice")
async def analyze_invoice(file: UploadFile = File(...)):
    # Yüklenen dosyayı geçici bir konuma kaydet
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        raw_text = ocr_engine.extract_text(tmp_path)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        os.remove(tmp_path)

    return {
        "filename": file.filename,
        "raw_text": raw_text,
    }