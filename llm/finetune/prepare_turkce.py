"""
Dogrulanmis Turkce kayitlari egitim verisine cevirir.

Veri kaynagi uygulamanin kendisi: fisi cekiyorsun, model tahmin ediyor, sen
yanlislari duzeltip "dogrula" diyorsun. Duzelttigin hali dogru cevap oluyor.

SADECE dogrulandi=1 kayitlar aliniyor. Isaretsiz kayit modelin kendi
tahminidir; onu egitime vermek modele kendi hatalarini dogru olarak
ogretmek olurdu.

Kullanim:
    python llm/finetune/prepare_turkce.py
    python llm/finetune/prepare_turkce.py --db data/faturalar.db --out data/turkce.jsonl
    python llm/finetune/prepare_turkce.py --karistir data/sroie_train.jsonl
"""

import argparse
import json
import os
import random
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "..", "api"))
sys.path.insert(0, os.path.join(_BASE_DIR, ".."))

import db  # noqa: E402
from prompt import FIELDS  # noqa: E402


def kayitlari_ornege_cevir(kayitlar: list) -> list:
    """
    Veritabani satirlarini {raw_text, target} ciftlerine cevirir.

    'kdv' ve 'category' hedefe konmuyor: model prompt'u bes alanli ve o
    prompt ile egitildi (bkz. llm/prompt.py). Alan eklemek egitim ile
    calisma anindaki bicimi ayirir. Bu ikisini kural katmani ve ayri
    siniflandirma adimi hallediyor.
    """
    ornekler = []
    for k in kayitlar:
        raw_text = (k.get("raw_text") or "").strip()
        if not raw_text:
            continue
        hedef = {alan: (k.get(alan) or None) for alan in FIELDS}
        # Hicbir alani doldurulmamis kayit ogretici degil: model zaten
        # "hepsi bos" cevabini kolayca veriyor, bunu pekistirmeye gerek yok.
        if not any(hedef.values()):
            continue
        ornekler.append({"raw_text": raw_text, "target": hedef, "kaynak": "turkce"})
    return ornekler


def jsonl_oku(yol: str) -> list:
    ornekler = []
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if satir:
                o = json.loads(satir)
                o.setdefault("kaynak", "sroie")
                ornekler.append(o)
    return ornekler


def istatistik(ad: str, ornekler: list):
    print(f"\n--- {ad}: {len(ornekler)} ornek ---")
    if not ornekler:
        return
    for alan in FIELDS:
        dolu = sum(1 for o in ornekler if o["target"].get(alan))
        print(f"  {alan:<14} {dolu:>4}/{len(ornekler)}  ({100*dolu/len(ornekler):.0f}%)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None, help="Veritabani yolu (bos = varsayilan)")
    p.add_argument("--out", default="data/turkce_train.jsonl")
    p.add_argument("--karistir", default=None,
                   help="Bu JSONL ile karistirip tek dosya uret (ornek: SROIE)")
    p.add_argument("--tohum", type=int, default=42)
    args = p.parse_args()

    if args.db:
        db.yol_ayarla(args.db)
    db.hazirla()

    kayitlar = db.egitim_kayitlari()
    ornekler = kayitlari_ornege_cevir(kayitlar)

    print(f"Veritabani: {db.yol()}")
    print(f"Dogrulanmis kayit: {len(kayitlar)}  ->  kullanilabilir ornek: {len(ornekler)}")

    if not ornekler:
        sys.exit(
            "\nHATA: dogrulanmis kayit yok.\n"
            "  Arayuzde fisleri acip alanlari kontrol edin ve\n"
            "  'Kontrol ettim, dogrula' dugmesine basin."
        )

    istatistik("turkce", ornekler)

    if args.karistir:
        if not os.path.exists(args.karistir):
            sys.exit(f"HATA: {args.karistir} yok")
        sroie = jsonl_oku(args.karistir)
        istatistik("sroie", sroie)

        # Karistirma sart: ayni kaynaktan ornekler arka arkaya gelirse model
        # once birini sonra otekini ogrenip ilkini kismen unutuyor.
        ornekler = ornekler + sroie
        random.Random(args.tohum).shuffle(ornekler)
        print(f"\nKaristirildi: {len(ornekler)} ornek "
              f"({sum(1 for o in ornekler if o['kaynak']=='turkce')} turkce + "
              f"{sum(1 for o in ornekler if o['kaynak']=='sroie')} sroie)")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for o in ornekler:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    print(f"\n-> {args.out}")
    print("\nEgitim:")
    print(f"  python llm/finetune/train.py --train-file {args.out} "
          f"--out-dir models/qwen-invoice-tr")


if __name__ == "__main__":
    main()
