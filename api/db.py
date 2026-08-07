"""
Ayiklanan faturalarin kaydedildigi veritabani katmani.

SQLite secildi: tek dosya, sunucu kurulumu yok, Python'un icinde geliyor.
Demo ve tek kullanicili calisma icin fazlasiyla yeterli. Cok kullanicili
bir servise donusurse PostgreSQL'e gecilir; asagidaki fonksiyon imzalari
ayni kaldigi surece cagiran kod degismez.

Her islem icin yeni baglanti aciliyor. Sebep: FastAPI senkron endpoint'leri
ayri thread'lerde calistiriyor, sqlite3 baglantilari ise varsayilan olarak
thread'ler arasi paylasilamiyor. SQLite'ta baglanti acmak cok ucuz oldugu
icin bu pratikte sorun degil.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

VARSAYILAN_YOL = os.path.join(os.path.dirname(__file__), "..", "data", "faturalar.db")

# Fatura alanlari ayri sutunlarda: SQL ile "bu firmanin faturalari",
# "toplami 100'un ustundekiler" gibi sorgular yazilabilsin diye.
# Tek bir JSON sutununa tikmak kaydi kolaylastirirdi ama sorgulamayi
# imkansiz hale getirirdi.
SEMA = """
CREATE TABLE IF NOT EXISTS faturalar (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    olusturuldu   TEXT    NOT NULL,
    dosya_adi     TEXT,
    company_name  TEXT,
    date          TEXT,
    address       TEXT,
    total_amount  TEXT,
    invoice_no    TEXT,
    raw_text      TEXT,
    ocr_saniye    REAL,
    llm_saniye    REAL,
    llm_kullanildi INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_faturalar_olusturuldu ON faturalar(olusturuldu DESC);
"""

# Sema ilk surumden sonra buyudugu icin, var olan veritabanlarina
# eklenmesi gereken sutunlar. hazirla() bunlari eksikse ekliyor.
SONRADAN_EKLENEN_SUTUNLAR = [
    ("category", "TEXT"),
]

_db_yolu = os.path.abspath(VARSAYILAN_YOL)


def yol_ayarla(yol: str):
    """Veritabani dosyasinin yerini degistirir (testlerde kullanisli)."""
    global _db_yolu
    _db_yolu = os.path.abspath(yol)


def yol() -> str:
    return _db_yolu


def _baglan() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_yolu), exist_ok=True)
    conn = sqlite3.connect(_db_yolu)
    conn.row_factory = sqlite3.Row  # satirlara sutun adiyla erisebilmek icin
    return conn


def hazirla():
    """
    Tablo yoksa olusturur, eksik sutunlari ekler.

    Sutun ekleme neden burada: sema buyudukce mevcut veritabani dosyasi
    geride kaliyor. Dosyayi silip yeniden olusturmak kayitli faturalari
    da silerdi; ALTER TABLE ile eski kayitlar korunuyor, yeni sutun
    onlarda bos kaliyor.
    """
    with _baglan() as conn:
        conn.executescript(SEMA)

        mevcut = {s["name"] for s in conn.execute("PRAGMA table_info(faturalar)")}
        for sutun, tanim in SONRADAN_EKLENEN_SUTUNLAR:
            if sutun not in mevcut:
                conn.execute(f"ALTER TABLE faturalar ADD COLUMN {sutun} {tanim}")
                print(f"[DB] sutun eklendi: {sutun}")


def kaydet(dosya_adi: str, veri: dict, raw_text: str, meta: dict,
           kategori: str | None = None) -> int:
    """Bir fatura sonucunu kaydeder ve olusan kaydin id'sini dondurur."""
    with _baglan() as conn:
        imlec = conn.execute(
            """INSERT INTO faturalar
               (olusturuldu, dosya_adi, company_name, date, address,
                total_amount, invoice_no, raw_text, ocr_saniye, llm_saniye,
                llm_kullanildi, category)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                dosya_adi,
                veri.get("company_name"),
                veri.get("date"),
                veri.get("address"),
                veri.get("total_amount"),
                veri.get("invoice_no"),
                raw_text,
                meta.get("ocr_seconds"),
                meta.get("llm_seconds"),
                1 if meta.get("llm_used") else 0,
                kategori,
            ),
        )
        return imlec.lastrowid


def listele(limit: int = 50, offset: int = 0) -> list:
    """Kayitlari yeniden eskiye dogru dondurur. raw_text dahil edilmez."""
    with _baglan() as conn:
        satirlar = conn.execute(
            """SELECT id, olusturuldu, dosya_adi, company_name, date, address,
                      total_amount, invoice_no, category, ocr_saniye, llm_saniye
               FROM faturalar ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [dict(s) for s in satirlar]


def getir(kayit_id: int):
    """Tek kaydi ham metniyle birlikte dondurur; yoksa None."""
    with _baglan() as conn:
        satir = conn.execute(
            "SELECT * FROM faturalar WHERE id = ?", (kayit_id,)
        ).fetchone()
        return dict(satir) if satir else None


def sil(kayit_id: int) -> bool:
    """Kaydi siler. Silinecek kayit bulunduysa True doner."""
    with _baglan() as conn:
        return conn.execute(
            "DELETE FROM faturalar WHERE id = ?", (kayit_id,)
        ).rowcount > 0


def kategori_ozeti() -> list:
    """
    Kategori basina kayit sayisi ve harcama toplami.

    Tutarlar metin olarak saklaniyor ("10.250 TL", "82,55") cunku belgede
    nasil yaziyorsa oyle korumak istiyoruz - kaynak veriyi bozmadan saklamak,
    sonradan yanlis yorumlanirsa geri donebilmeyi sagliyor. Toplama islemi
    bu yuzden SQL'de degil Python'da yapiliyor: hangi ayiracin binlik
    hangisinin ondalik oldugu desene bakilarak ayirt ediliyor.
    """
    import sys

    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "llm", "inference"))
    from infer import _tutari_sayiya_cevir

    with _baglan() as conn:
        satirlar = conn.execute(
            "SELECT category, total_amount FROM faturalar"
        ).fetchall()

    gruplar = {}
    for s in satirlar:
        ad = s["category"] or "Sınıflandırılmadı"
        g = gruplar.setdefault(ad, {"kategori": ad, "adet": 0, "toplam": 0.0})
        g["adet"] += 1
        if s["total_amount"]:
            g["toplam"] += _tutari_sayiya_cevir(s["total_amount"])

    return sorted(gruplar.values(), key=lambda g: g["toplam"], reverse=True)


def ozet() -> dict:
    """Toplam kayit sayisi ve son kayit zamani."""
    with _baglan() as conn:
        satir = conn.execute(
            "SELECT COUNT(*) AS adet, MAX(olusturuldu) AS son FROM faturalar"
        ).fetchone()
        return {"adet": satir["adet"], "son_kayit": satir["son"]}


if __name__ == "__main__":
    hazirla()
    print("veritabani:", yol())
    print("ozet      :", json.dumps(ozet(), ensure_ascii=False))
