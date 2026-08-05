"""
FastAPI servisi.

Fatura gorseli alir -> PaddleOCR ile ham metne cevirir -> LLM ile yapilandirilmis
JSON'a ayiklar.

Ayarlar ortam degiskenleri (ya da .env dosyasi) ile verilir:
    ENABLE_LLM    = 1 | 0                       (varsayilan 1)
    MODEL_NAME    = Qwen/Qwen2.5-0.5B-Instruct
    ADAPTER_PATH  = models/qwen-invoice-lora    (fine-tune sonrasi; bos = base model)
    LOAD_IN_4BIT  = 1 | 0                       (varsayilan 0, GPU gerekir)
    OCR_LANG      = en
"""

import os
import shutil
import sys
import tempfile
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE_DIR)  # db.py bu klasorde
sys.path.append(os.path.join(_BASE_DIR, "..", "ocr"))
sys.path.append(os.path.join(_BASE_DIR, "..", "llm"))
sys.path.append(os.path.join(_BASE_DIR, "..", "llm", "inference"))

import db  # noqa: E402

WEB_DIZINI = os.path.join(_BASE_DIR, "web")

# .env, ocr_engine import edilmeden ONCE okunmali: paddlex cache yolunu
# (PADDLE_PDX_CACHE_HOME) import aninda bir kere okuyup sabitliyor.
load_dotenv()

from ocr_engine import OCREngine  # noqa: E402
from prompt import empty_result  # noqa: E402


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Uygulama boyunca tek kopya tutulan agir nesneler
ocr_engine: OCREngine | None = None
extractor = None
llm_error: str | None = None


def _load_llm():
    """
    LLM'i yukler. Basarisiz olursa servisi dusurmez, sebebini kaydeder.

    Neden: torch/transformers agir bagimliliklar ve yerel makinede kurulu
    olmayabiliyor. LLM olmasa bile OCR katmani calisir durumda kalsin ki
    servis test edilebilsin.
    """
    global extractor, llm_error

    if not _flag("ENABLE_LLM", "1"):
        llm_error = "ENABLE_LLM=0 ile kapatildi"
        return

    try:
        from infer import InvoiceExtractor

        adapter = os.getenv("ADAPTER_PATH") or None
        extractor = InvoiceExtractor(
            model_name=os.getenv("MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct"),
            adapter_path=adapter,
            load_in_4bit=_flag("LOAD_IN_4BIT"),
        )
        print(f"[LLM] hazir | cihaz: {extractor.model.device} | adaptor: {adapter or 'yok (base model)'}")
    except Exception as e:
        llm_error = f"{type(e).__name__}: {e}"
        print(f"[LLM] yuklenemedi -> {llm_error}")
        print("[LLM] servis yalnizca OCR ile calisacak (data alani null donecek)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Agir modelleri istek aninda degil, servis acilirken bir kere yukle.
    Aksi halde ilk istek 10+ saniye bekler ve zaman asimina ugrayabilir.
    """
    global ocr_engine

    if os.getenv("DB_PATH"):
        db.yol_ayarla(os.getenv("DB_PATH"))
    db.hazirla()
    print(f"[DB] hazir -> {db.yol()}  ({db.ozet()['adet']} kayit)")

    print("[OCR] yukleniyor...")
    ocr_engine = OCREngine(lang=os.getenv("OCR_LANG", "en"))
    print("[OCR] hazir")

    _load_llm()
    yield


app = FastAPI(title="Invoice OCR Service", version="0.2.0", lifespan=lifespan)


@app.get("/")
def arayuz():
    """Mobil web arayuzu. Telefon tarayicisindan acilir."""
    return FileResponse(os.path.join(WEB_DIZINI, "index.html"))


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "ocr_ready": ocr_engine is not None,
        "llm_ready": extractor is not None,
        "llm_error": llm_error,
        "adapter": os.getenv("ADAPTER_PATH") or None,
        "kayit_sayisi": db.ozet()["adet"],
    }


@app.get("/faturalar")
def faturalari_listele(limit: int = 50, offset: int = 0):
    """Kaydedilmis faturalari yeniden eskiye dogru dondurur."""
    return {"toplam": db.ozet()["adet"], "kayitlar": db.listele(limit, offset)}


@app.get("/faturalar/{kayit_id}")
def fatura_getir(kayit_id: int):
    """Tek kaydi ham OCR metniyle birlikte dondurur."""
    kayit = db.getir(kayit_id)
    if kayit is None:
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    return kayit


@app.delete("/faturalar/{kayit_id}")
def fatura_sil(kayit_id: int):
    if not db.sil(kayit_id):
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    return {"silindi": kayit_id}


@app.post("/analyze-invoice")
async def analyze_invoice(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        t0 = time.time()
        raw_text = ocr_engine.extract_text(tmp_path)
        ocr_sure = time.time() - t0
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"OCR hatasi: {e}"})
    finally:
        os.remove(tmp_path)

    llm_sure = None
    if extractor is None:
        # LLM yok: bos sonuc don ama ham metni ver, servis yine de ise yarasin
        data = empty_result()
    else:
        try:
            t0 = time.time()
            data = extractor.extract(raw_text)
            llm_sure = time.time() - t0
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"LLM hatasi: {e}", "raw_text": raw_text},
            )

    meta = {
        "llm_used": extractor is not None,
        "llm_error": llm_error,
        "ocr_seconds": round(ocr_sure, 2),
        "llm_seconds": round(llm_sure, 2) if llm_sure is not None else None,
    }

    # Kayit basarisiz olsa bile sonucu dondurmeye devam ediyoruz: kullanicinin
    # elindeki analiz, veritabani hatasi yuzunden kaybolmasin.
    kayit_id, kayit_hatasi = None, None
    try:
        kayit_id = db.kaydet(file.filename or "", data, raw_text, meta)
    except Exception as e:
        kayit_hatasi = f"{type(e).__name__}: {e}"
        print(f"[DB] kaydedilemedi -> {kayit_hatasi}")

    return {
        "id": kayit_id,
        "filename": file.filename,
        "data": data,
        "raw_text": raw_text,  # Hata ayiklama icin: LLM mi yanlis anladi, OCR mi kotu okudu?
        "meta": {**meta, "kayit_hatasi": kayit_hatasi},
    }
