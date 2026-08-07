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
import re
import sqlite3
from datetime import datetime, timedelta, timezone

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
    # Belge tarihinin YYYY-AA-GG hali. 'date' sutunu belgede nasil yaziyorsa
    # oyle korunuyor (30.01.2022 / 25/12/2018 / 2024-12-31) cunku kaynak
    # veriyi bozmadan saklamak istiyoruz; ama o bicimde tarih araligi
    # sorgulanamiyor. Bu sutun yalnizca filtreleme icin.
    ("date_iso", "TEXT"),
    # KDV tutari. Modelden istenmiyor, kural katmani cikariyor
    # (fiste acik etiketi var). Belgede nasil yaziyorsa oyle saklaniyor.
    ("kdv", "TEXT"),
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


_TARIH_DESENLERI = [
    # (desen, gun/ay/yil sirasi)
    (re.compile(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})$"), ("g", "a", "y")),
    (re.compile(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2})$"), ("g", "a", "y2")),
    (re.compile(r"^(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})$"), ("y", "a", "g")),
]


def tarihi_iso_yap(tarih: str | None):
    """
    Belgedeki tarihi YYYY-AA-GG bicimine cevirir; cozulemezse None.

    Gun-ay sirasi belirsiz durumlarda (05.08.2026) Turkce/Avrupa duzeni
    varsayiliyor: gun once. SROIE de ayni duzeni kullaniyor (25/12/2018),
    yani iki veri kaynagimiz da uyumlu.
    """
    if not tarih:
        return None
    t = str(tarih).strip()
    for desen, sira in _TARIH_DESENLERI:
        m = desen.match(t)
        if not m:
            continue
        parcalar = dict(zip(sira, m.groups()))
        try:
            yil = int(parcalar.get("y") or 0)
            if "y2" in parcalar:  # iki haneli yil -> 2000'li varsayiliyor
                yil = 2000 + int(parcalar["y2"])
            ay, gun = int(parcalar["a"]), int(parcalar["g"])
            if not (1 <= ay <= 12 and 1 <= gun <= 31 and 1900 <= yil <= 2100):
                return None
            return f"{yil:04d}-{ay:02d}-{gun:02d}"
        except (ValueError, KeyError):
            return None
    return None


def _donem_araligi(donem: str | None):
    """Donem adini (baslangic, bitis) ISO tarih ciftine cevirir."""
    if not donem or donem == "tumu":
        return None, None

    bugun = datetime.now().date()
    if donem == "bu_ay":
        bas = bugun.replace(day=1)
        return bas.isoformat(), bugun.isoformat()
    if donem == "gecen_ay":
        bu_ayin_basi = bugun.replace(day=1)
        gecen_ayin_sonu = bu_ayin_basi - timedelta(days=1)
        return gecen_ayin_sonu.replace(day=1).isoformat(), gecen_ayin_sonu.isoformat()
    if donem == "son_30_gun":
        return (bugun - timedelta(days=30)).isoformat(), bugun.isoformat()
    if donem == "bu_yil":
        return bugun.replace(month=1, day=1).isoformat(), bugun.isoformat()
    return None, None


def kategori_guncelle(kayit_id: int, kategori: str | None) -> bool:
    """Kaydin kategorisini degistirir. Kayit bulunduysa True doner."""
    with _baglan() as conn:
        return conn.execute(
            "UPDATE faturalar SET category = ? WHERE id = ?", (kategori, kayit_id)
        ).rowcount > 0


def kaydet(dosya_adi: str, veri: dict, raw_text: str, meta: dict,
           kategori: str | None = None) -> int:
    """Bir fatura sonucunu kaydeder ve olusan kaydin id'sini dondurur."""
    with _baglan() as conn:
        imlec = conn.execute(
            """INSERT INTO faturalar
               (olusturuldu, dosya_adi, company_name, date, address,
                total_amount, invoice_no, raw_text, ocr_saniye, llm_saniye,
                llm_kullanildi, category, date_iso, kdv)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                tarihi_iso_yap(veri.get("date")),
                veri.get("kdv"),
            ),
        )
        return imlec.lastrowid


def _donem_kosulu(donem: str | None):
    """
    Donem filtresi icin (SQL parcasi, parametreler) uretir.

    Belge tarihi cozulemeyen kayitlar (date_iso NULL) kayit zamanina gore
    degerlendiriliyor: filtre disinda birakmak, o faturayi kullanicidan
    tamamen gizlerdi.
    """
    bas, bit = _donem_araligi(donem)
    if not bas:
        return "", []
    return (
        " WHERE (date_iso BETWEEN ? AND ?)"
        "    OR (date_iso IS NULL AND substr(olusturuldu,1,10) BETWEEN ? AND ?)",
        [bas, bit, bas, bit],
    )


def listele(limit: int = 50, offset: int = 0, donem: str | None = None) -> list:
    """Kayitlari yeniden eskiye dogru dondurur. raw_text dahil edilmez."""
    kosul, parametreler = _donem_kosulu(donem)
    with _baglan() as conn:
        satirlar = conn.execute(
            """SELECT id, olusturuldu, dosya_adi, company_name, date, date_iso,
                      address, total_amount, kdv, invoice_no, category,
                      ocr_saniye, llm_saniye
               FROM faturalar""" + kosul +
            " ORDER BY id DESC LIMIT ? OFFSET ?",
            parametreler + [limit, offset],
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


def kategori_ozeti(donem: str | None = None) -> list:
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

    kosul, parametreler = _donem_kosulu(donem)
    with _baglan() as conn:
        satirlar = conn.execute(
            "SELECT category, total_amount FROM faturalar" + kosul, parametreler
        ).fetchall()

    gruplar = {}
    for s in satirlar:
        ad = s["category"] or "Sınıflandırılmadı"
        g = gruplar.setdefault(ad, {"kategori": ad, "adet": 0, "toplam": 0.0})
        g["adet"] += 1
        if s["total_amount"]:
            g["toplam"] += _tutari_sayiya_cevir(s["total_amount"])

    return sorted(gruplar.values(), key=lambda g: g["toplam"], reverse=True)


def disa_aktarim_satirlari(donem: str | None = None) -> list:
    """CSV icin kayitlari eskiden yeniye dogru dondurur (muhasebe sirasi)."""
    kosul, parametreler = _donem_kosulu(donem)
    with _baglan() as conn:
        satirlar = conn.execute(
            """SELECT id, date, date_iso, company_name, invoice_no, total_amount,
                      kdv, category, address, olusturuldu
               FROM faturalar""" + kosul + " ORDER BY COALESCE(date_iso, olusturuldu), id",
            parametreler,
        ).fetchall()
        return [dict(s) for s in satirlar]


def ozet(donem: str | None = None) -> dict:
    """Toplam kayit sayisi ve son kayit zamani."""
    kosul, parametreler = _donem_kosulu(donem)
    with _baglan() as conn:
        satir = conn.execute(
            "SELECT COUNT(*) AS adet, MAX(olusturuldu) AS son FROM faturalar" + kosul,
            parametreler,
        ).fetchone()
        return {"adet": satir["adet"], "son_kayit": satir["son"]}


if __name__ == "__main__":
    hazirla()
    print("veritabani:", yol())
    print("ozet      :", json.dumps(ozet(), ensure_ascii=False))
