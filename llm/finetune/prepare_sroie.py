"""
SROIE v2 veri setini fine-tune icin JSONL formatina cevirir.

Kaynak yapisi (Kaggle: 'sroie-datasetv2'):
    SROIE2019/
        train/
            box/       -> X.txt : "x1,y1,...,x8,metin" satirlari (OCR ciktisi)
            entities/  -> X.txt : {"company":..., "date":..., "address":..., "total":...}
        test/
            ...

Uretilen JSONL (satir basina bir ornek):
    {"raw_text": "...", "target": {"company_name":..., ..., "invoice_no":...}}

Kullanim:
    python llm/finetune/prepare_sroie.py
    python llm/finetune/prepare_sroie.py --data-dir /kaggle/input/sroie-datasetv2/SROIE2019
    python llm/finetune/prepare_sroie.py --limit 20      # hizli deneme
"""

import argparse
import json
import os
import re
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, ".."))

from prompt import FIELDS  # noqa: E402

# SROIE'nin etiket adlari -> bizim alan adlarimiz
ALAN_ESLESMESI = {
    "company": "company_name",
    "date": "date",
    "address": "address",
    "total": "total_amount",
}

# --- invoice_no cikarimi -----------------------------------------------------
#
# SROIE bu alani etiketlemiyor (sadece yukaridaki 4 alani veriyor). Egitim
# verisinde invoice_no her ornekte null kalirsa model "bu alan hep bos" diye
# ogrenir ve su an calisan bir yetenegi kaybederiz. Bu yuzden ham metinden
# temkinli bir regex ile cikariyoruz.
#
# "Temkinli" olmasi kasitli: acik bir etiket kelimesi (INVOICE NO, BILL NO...)
# gormeden hicbir sey yakalamiyor. Fislerin bir kisminda fatura numarasi
# gercekten yoktur; orada null DOGRU etikettir, eksik etiket degil.

_FATURA_NO_DESENI = re.compile(
    r"""(?:TAX\s+)?(?:INVOICE|RECEIPT|BILL|DOCUMENT|DOC|INV|SLIP)\s*
        (?:NO|NUMBER|NUM|\#)\s*[.:\#\-]?\s*
        ([A-Z0-9][A-Z0-9\-/]{2,29})""",
    re.IGNORECASE | re.VERBOSE,
)

_TARIH_GORUNUMLU = re.compile(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}$")
_TUTAR_GORUNUMLU = re.compile(r"^\d+[.,]\d{1,2}$")


def _gecerli_fatura_no(aday: str) -> bool:
    """Regex'in yakaladigi seyin gercekten bir numara olup olmadigini eler."""
    aday = aday.strip(" .:-/")
    if not (3 <= len(aday) <= 30):
        return False
    if not any(k.isdigit() for k in aday):
        return False  # icinde hic rakam yoksa numara degil
    if _TARIH_GORUNUMLU.match(aday):
        return False  # tarih alanini fatura no sanmayalim
    if _TUTAR_GORUNUMLU.match(aday):
        return False  # tutari fatura no sanmayalim
    return True


def fatura_no_bul(raw_text: str):
    """Ham metinden fatura numarasi cikarir; bulamazsa None doner."""
    for eslesme in _FATURA_NO_DESENI.finditer(raw_text):
        aday = eslesme.group(1).strip(" .:-/")
        if _gecerli_fatura_no(aday):
            return aday
    return None


# --- veri seti okuma ---------------------------------------------------------


def veri_dizini_bul(verilen: str | None) -> str:
    """
    Veri setinin kok dizinini bulur. Kaggle'da dataset ismi surume gore
    degistigi icin elle yol vermek yerine 'box' + 'entities' iceren bir
    klasor ariyoruz.
    """
    if verilen:
        if not os.path.isdir(verilen):
            sys.exit(f"HATA: dizin yok -> {verilen}")
        return verilen

    for kok in ("/kaggle/input", "data"):
        if not os.path.isdir(kok):
            continue
        for dizin, alt_dizinler, _ in os.walk(kok):
            if "box" in alt_dizinler and "entities" in alt_dizinler:
                # train/test'in bir ust seviyesini dondur
                return os.path.dirname(dizin)

    sys.exit(
        "HATA: SROIE veri seti bulunamadi.\n"
        "  Kaggle'da: sag panel -> Add Input -> 'SROIE' aratip veri setini ekleyin\n"
        "  Ya da elle: --data-dir /kaggle/input/<dataset-adi>/SROIE2019"
    )


def _box_dosyasindan_metin(yol: str) -> str:
    """
    box/X.txt satirlari: "x1,y1,x2,y2,x3,y3,x4,y4,metin"
    Metin alani virgul icerebilir, bu yuzden en fazla 8 kez boluyoruz.
    """
    satirlar = []
    with open(yol, encoding="utf-8-sig", errors="ignore") as f:
        for satir in f:
            parcalar = satir.rstrip("\n").split(",", 8)
            if len(parcalar) < 9:
                continue
            metin = parcalar[8].strip()
            if metin:
                satirlar.append(metin)
    return "\n".join(satirlar)


def bolum_isle(bolum_dizini: str, limit: int | None = None):
    """Bir train/ veya test/ klasorunu okuyup ornek listesi uretir."""
    box_dizini = os.path.join(bolum_dizini, "box")
    ent_dizini = os.path.join(bolum_dizini, "entities")

    if not (os.path.isdir(box_dizini) and os.path.isdir(ent_dizini)):
        sys.exit(f"HATA: {bolum_dizini} icinde box/ ve entities/ klasorleri yok")

    ornekler, atlanan = [], 0
    dosyalar = sorted(f for f in os.listdir(ent_dizini) if f.endswith(".txt"))

    for dosya in dosyalar:
        if limit and len(ornekler) >= limit:
            break

        box_yolu = os.path.join(box_dizini, dosya)
        if not os.path.exists(box_yolu):
            atlanan += 1
            continue

        raw_text = _box_dosyasindan_metin(box_yolu)
        if not raw_text.strip():
            atlanan += 1
            continue

        try:
            with open(os.path.join(ent_dizini, dosya), encoding="utf-8-sig") as f:
                etiketler = json.load(f)
        except (json.JSONDecodeError, OSError):
            atlanan += 1
            continue

        hedef = {alan: None for alan in FIELDS}
        for sroie_ad, bizim_ad in ALAN_ESLESMESI.items():
            deger = etiketler.get(sroie_ad)
            if isinstance(deger, str) and deger.strip():
                hedef[bizim_ad] = deger.strip()

        hedef["invoice_no"] = fatura_no_bul(raw_text)

        ornekler.append({"raw_text": raw_text, "target": hedef})

    return ornekler, atlanan


def istatistik_yaz(ad: str, ornekler: list):
    print(f"\n--- {ad}: {len(ornekler)} ornek ---")
    for alan in FIELDS:
        dolu = sum(1 for o in ornekler if o["target"][alan] is not None)
        oran = 100 * dolu / len(ornekler) if ornekler else 0
        print(f"  {alan:<14} {dolu:>4}/{len(ornekler)}  ({oran:.0f}%)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=None, help="SROIE2019 klasoru (bos = otomatik ara)")
    p.add_argument("--out-dir", default="data", help="JSONL dosyalarinin yazilacagi klasor")
    p.add_argument("--limit", type=int, default=None, help="Bolum basina ornek siniri (deneme icin)")
    args = p.parse_args()

    kok = veri_dizini_bul(args.data_dir)
    print(f"Veri seti: {kok}")
    os.makedirs(args.out_dir, exist_ok=True)

    toplam = 0
    for bolum in ("train", "test"):
        bolum_dizini = os.path.join(kok, bolum)
        if not os.path.isdir(bolum_dizini):
            print(f"UYARI: {bolum}/ bulunamadi, atlaniyor")
            continue

        ornekler, atlanan = bolum_isle(bolum_dizini, args.limit)
        cikti = os.path.join(args.out_dir, f"sroie_{bolum}.jsonl")
        with open(cikti, "w", encoding="utf-8") as f:
            for ornek in ornekler:
                f.write(json.dumps(ornek, ensure_ascii=False) + "\n")

        istatistik_yaz(bolum, ornekler)
        if atlanan:
            print(f"  (eslesmeyen/bozuk {atlanan} dosya atlandi)")
        print(f"  -> {cikti}")
        toplam += len(ornekler)

    if not toplam:
        sys.exit("HATA: hic ornek uretilemedi.")

    print(f"\nToplam {toplam} ornek hazir.")
    print(
        "\nNot: invoice_no orani dusuk gorunuyorsa bu beklenen bir sey - "
        "fislerin cogunda fatura numarasi gercekten yok, orada null dogru etiket."
    )


if __name__ == "__main__":
    main()
