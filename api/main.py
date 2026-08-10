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

import csv
import io
import os
import shutil
import sys
import tempfile
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE_DIR)  # db.py bu klasorde
sys.path.append(os.path.join(_BASE_DIR, "..", "ocr"))
sys.path.append(os.path.join(_BASE_DIR, "..", "llm"))
sys.path.append(os.path.join(_BASE_DIR, "..", "llm", "inference"))

import db  # noqa: E402

WEB_DIZINI = os.path.join(_BASE_DIR, "web")
GORSEL_DIZINI = os.path.join(_BASE_DIR, "..", "data", "gorseller")

# .env, ocr_engine import edilmeden ONCE okunmali: paddlex cache yolunu
# (PADDLE_PDX_CACHE_HOME) import aninda bir kere okuyup sabitliyor.
load_dotenv()

from ocr_engine import OCREngine  # noqa: E402
from prompt import empty_result  # noqa: E402


def _bilinen_firmayla_tamamla(data: dict, raw_text: str) -> dict:
    """
    Daha once dogrulanmis bir firma bu fiste geciyorsa adini ve adresini kullanir.

    Firma adi ve adres, modelin en cok zorlandigi iki alan: belgede bunlari
    isaretleyen bir etiket yok, konumdan cikarim yapmak gerekiyor. Ama ayni
    isletmeden birden fazla fis geliyor (market, kafe, akaryakit) ve kullanici
    bir kez duzeltip onayladiysa o bilgi elimizde.

    Guvenlik icin iki kosul: ad ham metinde GERCEKTEN geciyor olmali (aksi
    halde alakasiz bir firmanin adini yapistirirdik) ve adres yalnizca model
    bos biraktiginda dolduruluyor (sube adresleri farkli olabilir).

    Bu, yeniden egitim beklemeden duzeltmelerin ise yaramasini sagliyor.
    """
    if not raw_text:
        return data

    from infer import _sadelestir

    metin = _sadelestir(raw_text)
    en_iyi = None
    for firma in db.bilinen_firmalar():
        sade = _sadelestir(firma["ad"])
        # Cok kisa adlar rastgele eslesir ("AS", "LTD"); en az 8 karakter
        if len(sade) >= 8 and sade in metin:
            if en_iyi is None or len(sade) > len(_sadelestir(en_iyi["ad"])):
                en_iyi = firma  # en uzun eslesme en belirleyici olan

    if en_iyi:
        data["company_name"] = en_iyi["ad"]
        if not data.get("address") and en_iyi["adres"]:
            data["address"] = en_iyi["adres"]
    return data


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _yerel_adresleri_yaz(port: int = 8000):
    """
    Servisin telefondan erisilebilecegi adresleri ekrana basar.

    Makinenin IP'si ag degistikce degisiyor (hotspot, ev wifi'si, kampus
    agi hepsi baska adres veriyor) ve her seferinde ipconfig'e bakmak
    gerekiyordu. Acilista yazdirmak bu adimi ortadan kaldiriyor.

    Sanal adaptorler (WSL, VirtualBox) eleniyor: onlar telefondan
    erisilemeyen ic aglar ve listeyi kalabaliklastiriyorlar.
    """
    import socket

    adresler = []
    try:
        for bilgi in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = bilgi[4][0]
            if ip.startswith(("127.", "169.254.")):
                continue
            # Yaygin sanal adaptor araliklari
            if ip.startswith(("172.25.", "192.168.56.", "172.17.", "172.18.")):
                continue
            if ip not in adresler:
                adresler.append(ip)
    except OSError:
        pass

    print(f"[AG] bilgisayardan : http://127.0.0.1:{port}")
    for ip in adresler:
        print(f"[AG] telefondan    : http://{ip}:{port}")
    if not adresler:
        print("[AG] telefondan erisilebilir bir adres bulunamadi "
              "(kablosuz baglanti kapali olabilir)")


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
    # Model adlari yalnizca ortam degiskeniyle acikca verilmisse geciliyor;
    # aksi halde OCREngine kendi varsayilanini (hizli mobile modeller) kullanir.
    ocr_ayar = {}
    if os.getenv("OCR_DET_MODEL"):
        ocr_ayar["det_model"] = os.getenv("OCR_DET_MODEL")
    if os.getenv("OCR_REC_MODEL"):
        ocr_ayar["rec_model"] = os.getenv("OCR_REC_MODEL")

    ocr_engine = OCREngine(
        lang=os.getenv("OCR_LANG", "en"),
        max_side=int(os.getenv("OCR_MAX_SIDE", "1600")),
        foto_modu=_flag("OCR_FOTO_MODU", "1"),
        **ocr_ayar,
    )
    print("[OCR] hazir")

    _load_llm()

    # Modelleri acilista bir kere calistir.
    #
    # Ilk gercek istek, CUDA cekirdeklerinin derlenmesi ve onbelleklerin
    # dolmasi yuzunden sonrakilerin birkac kati suruyor. Bunu kullaniciya
    # yasatmak yerine burada, servis henuz kimseye cevap vermiyorken
    # hallediyoruz. Demo/sunum sirasinda ilk istegin yavas gelmesi bu
    # yuzdendi.
    if extractor is not None:
        try:
            t0 = time.time()
            extractor.extract("ISITMA\nTOTAL: 1.00")
            print(f"[LLM] isitma tamam ({time.time() - t0:.1f} sn)")
        except Exception as e:
            print(f"[LLM] isitma atlandi -> {e}")

    _yerel_adresleri_yaz(int(os.getenv("PORT", "8000")))

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
def faturalari_listele(limit: int = 50, offset: int = 0, donem: str | None = None):
    """
    Kaydedilmis faturalari yeniden eskiye dogru dondurur.

    donem: tumu | bu_ay | gecen_ay | son_30_gun | bu_yil
    Filtre belge tarihine gore calisiyor (kayit zamanina degil): muhasebede
    onemli olan fisin uzerindeki tarih.
    """
    return {
        "toplam": db.ozet(donem)["adet"],
        "donem": donem or "tumu",
        "kayitlar": db.listele(limit, offset, donem),
    }


@app.get("/kategoriler")
def kategori_ozeti(donem: str | None = None):
    """Kategori basina kayit sayisi ve harcama toplami."""
    return {"donem": donem or "tumu", "kategoriler": db.kategori_ozeti(donem)}


@app.get("/disa-aktar")
def disa_aktar(donem: str | None = None):
    """
    Kayitlari CSV olarak dondurur (muhasebeciye gonderilecek dosya).

    Bicim kararlari, dosyanin Turkiye'de Excel ile acilacagi varsayimiyla:
      - Ayirac noktali virgul. Turkce Excel virgulu ONDALIK ayiraci sayiyor;
        virgulle ayrilmis bir dosyada "82,55" iki hucreye bolunurdu.
      - Dosya BOM ile basliyor. Onsuz Excel dosyayi UTF-8 saymiyor ve
        Turkce karakterler bozuk goruniyor.
      - Tutarlar belgede nasil yaziyorsa oyle yaziliyor; ayrica sayiya
        cevrilmis bir sutun da var ki Excel'de toplam alinabilsin.
    """
    satirlar = db.disa_aktarim_satirlari(donem)

    from infer import _tutari_sayiya_cevir

    tampon = io.StringIO()
    # csv.writer satir sonu olarak varsayilan \r\n kullaniyor; Excel bunu bekliyor.
    yazici = csv.writer(tampon, delimiter=";")
    yazici.writerow([
        "Kayit No", "Belge Tarihi", "Firma", "Belge No",
        "Tutar", "Tutar (sayi)", "KDV", "KDV (sayi)",
        "Kategori", "Adres", "Kayit Zamani",
    ])
    for k in satirlar:
        yazici.writerow([
            k["id"],
            k["date"] or "",
            k["company_name"] or "",
            k["invoice_no"] or "",
            k["total_amount"] or "",
            f"{_tutari_sayiya_cevir(k['total_amount']):.2f}".replace(".", ",") if k["total_amount"] else "",
            k["kdv"] or "",
            f"{_tutari_sayiya_cevir(k['kdv']):.2f}".replace(".", ",") if k["kdv"] else "",
            k["category"] or "",
            " ".join((k["address"] or "").split()),  # adres cok satirli olabilir
            (k["olusturuldu"] or "")[:10],
        ])

    ad = f"faturalar-{donem or 'tumu'}.csv"
    return Response(
        content="﻿" + tampon.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{ad}"'},
    )


@app.get("/kategori-listesi")
def kategori_listesi():
    """Arayuzun secim kutusunu doldurmasi icin gecerli kategoriler."""
    import kategori as kat

    return {"kategoriler": kat.KATEGORILER}


@app.patch("/faturalar/{kayit_id}")
def kaydi_duzelt(kayit_id: int, alanlar: dict = Body(...)):
    """
    Kaydin alanlarini elle duzeltir.

    Model her alani dogru getirmiyor; duzeltilen degerler hem kaydi
    duzeltiyor hem de ilerideki egitim icin etiketli veri birikiyor.
    Yalnizca db.DUZENLENEBILIR_ALANLAR guncellenebiliyor.
    """
    if not db.kaydi_guncelle(kayit_id, alanlar):
        raise HTTPException(
            status_code=404, detail="Kayit bulunamadi ya da gecerli alan verilmedi"
        )
    return db.getir(kayit_id)


@app.post("/faturalar/{kayit_id}/dogrula")
def kaydi_dogrula(kayit_id: int, dogrulandi: bool = Body(True, embed=True)):
    """
    Kaydi 'gozden gecirildi' olarak isaretler.

    Egitim verisi yalnizca isaretli kayitlardan uretiliyor. Isaretsiz kayit
    modelin kendi tahmini; onu egitime vermek modele kendi hatalarini dogru
    olarak ogretmek olurdu.
    """
    if not db.kaydi_guncelle(kayit_id, {"dogrulandi": dogrulandi}):
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    return db.getir(kayit_id)


@app.patch("/faturalar/{kayit_id}/kategori")
def kategori_degistir(kayit_id: int, kategori: str = Body(..., embed=True)):
    """
    Kaydin kategorisini elle degistirir.

    Yalnizca gecerli kategoriler kabul ediliyor: serbest metne izin vermek
    kategori dokumunu zamanla birbirinin ayni ama farkli yazilmis
    ("market", "Market ", "MARKET") kayitlarla doldururdu.
    """
    import kategori as kat

    if kategori not in kat.KATEGORILER:
        raise HTTPException(
            status_code=400,
            detail=f"Gecersiz kategori. Gecerliler: {', '.join(kat.KATEGORILER)}",
        )
    if not db.kategori_guncelle(kayit_id, kategori):
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    return {"id": kayit_id, "kategori": kategori}


@app.get("/faturalar/{kayit_id}")
def fatura_getir(kayit_id: int):
    """Tek kaydi ham OCR metniyle birlikte dondurur."""
    kayit = db.getir(kayit_id)
    if kayit is None:
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    return kayit


@app.get("/faturalar/{kayit_id}/gorsel")
def fatura_gorseli(kayit_id: int):
    """Kaydin kaynak gorselini dondurur."""
    kayit = db.getir(kayit_id)
    if not kayit or not kayit.get("gorsel"):
        raise HTTPException(status_code=404, detail="Gorsel yok")
    yol = os.path.join(GORSEL_DIZINI, kayit["gorsel"])
    if not os.path.exists(yol):
        raise HTTPException(status_code=404, detail="Gorsel dosyasi bulunamadi")
    return FileResponse(yol)


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
        os.remove(tmp_path)
        return JSONResponse(status_code=500, content={"error": f"OCR hatasi: {e}"})

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
            os.remove(tmp_path)
            return JSONResponse(
                status_code=500,
                content={"error": f"LLM hatasi: {e}", "raw_text": raw_text},
            )

    # Dogrulanmis firma hafizasi: tekrar eden isletmelerde kullanicinin
    # onayladigi ad/adres, modelin tahminine tercih ediliyor.
    try:
        data = _bilinen_firmayla_tamamla(data, raw_text)
    except Exception as e:
        print(f"[FIRMA] hafiza uygulanamadi -> {e}")

    meta = {
        "llm_used": extractor is not None,
        "llm_error": llm_error,
        "ocr_seconds": round(ocr_sure, 2),
        "llm_seconds": round(llm_sure, 2) if llm_sure is not None else None,
    }

    # Kategori ayri bir adim: ayiklama modelinin prompt'una dokunmuyoruz.
    # Taninan bir zincir varsa anahtar kelimeyle bulunuyor, yoksa kisa bir
    # LLM cagrisi yapiliyor. Basarisiz olursa analiz yine donuyor.
    kategori = None
    if extractor is not None:
        try:
            t0 = time.time()
            kategori = extractor.siniflandir(data.get("company_name"), raw_text)
            meta["kategori_seconds"] = round(time.time() - t0, 2)
        except Exception as e:
            print(f"[KATEGORI] siniflandirilamadi -> {e}")

    # Kayit basarisiz olsa bile sonucu dondurmeye devam ediyoruz: kullanicinin
    # elindeki analiz, veritabani hatasi yuzunden kaybolmasin.
    kayit_id, kayit_hatasi = None, None
    try:
        kayit_id = db.kaydet(file.filename or "", data, raw_text, meta, kategori)
    except Exception as e:
        kayit_hatasi = f"{type(e).__name__}: {e}"
        print(f"[DB] kaydedilemedi -> {kayit_hatasi}")

    # Gorseli sakla. Egitim icin gerekmiyor (model metinle calisiyor) ama
    # kaydi sonradan gozle dogrulamayi ve ileride daha iyi bir OCR ciktiginda
    # yeniden okutmayi mumkun kiliyor.
    gorsel_adi = None
    if kayit_id:
        try:
            os.makedirs(GORSEL_DIZINI, exist_ok=True)
            gorsel_adi = f"{kayit_id}{suffix or '.jpg'}"
            shutil.move(tmp_path, os.path.join(GORSEL_DIZINI, gorsel_adi))
            db.gorsel_ayarla(kayit_id, gorsel_adi)
        except Exception as e:
            gorsel_adi = None
            print(f"[GORSEL] saklanamadi -> {e}")

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    return {
        "id": kayit_id,
        "filename": file.filename,
        "data": data,
        "category": kategori,
        "gorsel": gorsel_adi,
        "raw_text": raw_text,  # Hata ayiklama icin: LLM mi yanlis anladi, OCR mi kotu okudu?
        "meta": {**meta, "kayit_hatasi": kayit_hatasi},
    }
