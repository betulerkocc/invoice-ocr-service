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
    """Tablo yoksa olusturur. Servis acilisinda bir kere cagrilir."""
    with _baglan() as conn:
        conn.executescript(SEMA)


def kaydet(dosya_adi: str, veri: dict, raw_text: str, meta: dict) -> int:
    """Bir fatura sonucunu kaydeder ve olusan kaydin id'sini dondurur."""
    with _baglan() as conn:
        imlec = conn.execute(
            """INSERT INTO faturalar
               (olusturuldu, dosya_adi, company_name, date, address,
                total_amount, invoice_no, raw_text, ocr_saniye, llm_saniye,
                llm_kullanildi)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
            ),
        )
        return imlec.lastrowid


def listele(limit: int = 50, offset: int = 0) -> list:
    """Kayitlari yeniden eskiye dogru dondurur. raw_text dahil edilmez."""
    with _baglan() as conn:
        satirlar = conn.execute(
            """SELECT id, olusturuldu, dosya_adi, company_name, date, address,
                      total_amount, invoice_no, ocr_saniye, llm_saniye
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
