"""
Egitim setini hazirlar: dogrulanmis Turkce kayitlar + ek kaynaklar.

Veri kaynagi uygulamanin kendisi: fisi cekiyorsun, model tahmin ediyor, sen
yanlislari duzeltip "dogrula" diyorsun. Duzelttigin hali dogru cevap oluyor.

SADECE dogrulandi=1 kayitlar aliniyor. Isaretsiz kayit modelin kendi
tahminidir; onu egitime vermek modele kendi hatalarini dogru olarak
ogretmek olurdu.

Kullanim:
    python llm/finetune/prepare_turkce.py
    python llm/finetune/prepare_turkce.py --karistir data/sentetik_train.jsonl,data/sroie_train.jsonl
"""

import argparse
import json
import os
import random
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "..", "api"))
sys.path.insert(0, os.path.join(_BASE_DIR, ".."))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "inference"))

import db  # noqa: E402
from prompt import FIELDS  # noqa: E402


def _metinde_yoksa_bosalt(hedef: dict, raw_text: str) -> tuple[dict, list]:
    """
    Ham metinde bulunmayan hedef degerleri None yapar.

    Neden gerekli: kullanici fotografa bakip dogru degeri giriyor, ama OCR o
    satiri hic okumamis olabiliyor (fisin ust kismi kirpilmis, baslik silik).
    Olculen veride onayli kayitlarin ucte birinde firma adi ham metinde hic
    gecmiyordu.

    Boyle bir ornekle egitmek modele "girdide olmayani uydur" ogretir - tam
    da duzeltmeye calistigimiz davranis. Prompt zaten "metinde yoksa null
    kullan" diyor; hedefi bu kurala uyduruyoruz.

    Veritabanindaki deger DEGISMIYOR: fatura hakkindaki gercek o, muhasebe
    ciktisinda ve CSV'de kullanilmaya devam ediyor. Degisen yalnizca egitim
    hedefi.
    """
    from infer import _metinde_benziyor_mu, _sadelestir

    bosaltilan = []
    for alan, deger in list(hedef.items()):
        if not isinstance(deger, str) or not deger.strip():
            continue
        if alan == "date":
            continue  # tarih bicimlendirilebiliyor, birebir aranmaz
        if alan in ("total_amount", "invoice_no"):
            gecerli = _sadelestir(deger) in _sadelestir(raw_text)
        else:
            gecerli = _metinde_benziyor_mu(deger, raw_text)
        if not gecerli:
            hedef[alan] = None
            bosaltilan.append(alan)
    return hedef, bosaltilan


def kayitlari_ornege_cevir(kayitlar: list) -> list:
    """
    Veritabani satirlarini {raw_text, target} ciftlerine cevirir.

    'kdv' ve 'category' hedefe konmuyor: model prompt'u bes alanli ve o
    prompt ile egitildi (bkz. llm/prompt.py). Alan eklemek egitim ile
    calisma anindaki bicimi ayirir. Bu ikisini kural katmani ve ayri
    siniflandirma adimi hallediyor.
    """
    ornekler = []
    bosaltma_sayaci = {}
    atlanan = 0

    for k in kayitlar:
        raw_text = (k.get("raw_text") or "").strip()
        if not raw_text:
            continue
        hedef = {alan: (k.get(alan) or None) for alan in FIELDS}
        hedef, bosaltilan = _metinde_yoksa_bosalt(hedef, raw_text)
        for alan in bosaltilan:
            bosaltma_sayaci[alan] = bosaltma_sayaci.get(alan, 0) + 1

        # Hicbir alani doldurulmamis kayit ogretici degil: model zaten
        # "hepsi bos" cevabini kolayca veriyor, bunu pekistirmeye gerek yok.
        # Bu genelde OCR'in tamamen cuvalladigi fisler oluyor.
        if not any(hedef.values()):
            atlanan += 1
            continue
        ornekler.append({"raw_text": raw_text, "target": hedef, "kaynak": "turkce"})

    if bosaltma_sayaci:
        print()
        print("Ham metinde bulunamadigi icin bosaltilan alanlar:")
        for alan, adet in sorted(bosaltma_sayaci.items(), key=lambda x: -x[1]):
            print(f"  {alan:<14} {adet}")
        print("  (veritabanindaki degerler degismedi, yalnizca egitim hedefi)")
    if atlanan:
        print()
        print(f"{atlanan} kayit atlandi: hicbir alani ham metinde bulunamadi")

    return ornekler


def jsonl_oku(yol: str, varsayilan_kaynak: str = "sroie") -> list:
    ornekler = []
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if satir:
                o = json.loads(satir)
                o.setdefault("kaynak", varsayilan_kaynak)
                ornekler.append(o)
    return ornekler


def istatistik(ad: str, ornekler: list):
    print()
    print(f"--- {ad}: {len(ornekler)} ornek ---")
    if not ornekler:
        return
    for alan in FIELDS:
        dolu = sum(1 for o in ornekler if o["target"].get(alan))
        print(f"  {alan:<14} {dolu:>4}/{len(ornekler)}  ({100 * dolu / len(ornekler):.0f}%)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None, help="Veritabani yolu (bos = varsayilan)")
    p.add_argument("--out", default="data/egitim.jsonl")
    p.add_argument("--test-out", default="data/turkce_test.jsonl")
    p.add_argument("--test-adet", type=int, default=10,
                   help="Kac gercek fis test icin ayrilsin (egitime girmez)")
    p.add_argument("--cogulla", type=int, default=4,
                   help="Gercek Turkce ornekler kac kez tekrarlansin")
    p.add_argument("--karistir", default=None,
                   help="Virgulle ayrilmis ek JSONL dosyalari (sentetik, sroie)")
    p.add_argument("--tohum", type=int, default=42)
    args = p.parse_args()

    if args.db:
        db.yol_ayarla(args.db)
    db.hazirla()

    gercek = kayitlari_ornege_cevir(db.egitim_kayitlari())
    print()
    print(f"Veritabani: {db.yol()}")
    print(f"Kullanilabilir gercek ornek: {len(gercek)}")

    if not gercek:
        sys.exit(
            "HATA: dogrulanmis kayit yok.  Arayuzde fisleri acip alanlari "
            "kontrol edin ve 'Kontrol ettim, dogrula' dugmesine basin."
        )

    # Test seti EGITIMDEN once ayriliyor. Ayni fisleri hem egitip hem olcersek
    # model onlari ezberler ve olcum bir sey kanitlamaz.
    rnd = random.Random(args.tohum)
    karisik = gercek[:]
    rnd.shuffle(karisik)
    test = karisik[: args.test_adet]
    egitim_gercek = karisik[args.test_adet:]

    print(f"  test icin ayrilan : {len(test)}")
    print(f"  egitimde kalan    : {len(egitim_gercek)}")

    os.makedirs(os.path.dirname(args.test_out) or ".", exist_ok=True)
    with open(args.test_out, "w", encoding="utf-8") as f:
        for o in test:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"  -> {args.test_out}")

    # Cogullama: 29 gercek ornek 626 SROIE'nin yaninda %4'te kalir ve model
    # onlari fark etmez. Tekrarlamak agirligini artiriyor. Riski ezberleme,
    # bu yuzden olculu tutuluyor ve SROIE karisimda kaliyor.
    egitim = egitim_gercek * args.cogulla
    istatistik(f"gercek turkce (x{args.cogulla})", egitim)

    if args.karistir:
        for yol_ in [y.strip() for y in args.karistir.split(",") if y.strip()]:
            if not os.path.exists(yol_):
                sys.exit(f"HATA: {yol_} yok")
            kaynak = "sentetik" if "sentetik" in os.path.basename(yol_) else "sroie"
            ek = jsonl_oku(yol_, kaynak)
            istatistik(os.path.basename(yol_), ek)
            egitim += ek

    # Karistirma sart: ayni kaynaktan ornekler arka arkaya gelirse model once
    # birini sonra otekini ogrenip ilkini kismen unutuyor.
    rnd.shuffle(egitim)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for o in egitim:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    dagilim = {}
    for o in egitim:
        ad = o.get("kaynak", "?")
        dagilim[ad] = dagilim.get(ad, 0) + 1

    print()
    print(f"=== EGITIM SETI: {len(egitim)} ornek ===")
    for kaynak, adet in sorted(dagilim.items(), key=lambda x: -x[1]):
        print(f"  {kaynak:<12} {adet:>4}  ({100 * adet / len(egitim):.0f}%)")
    print()
    print(f"-> {args.out}")
    print()
    print("Egitim:")
    print(f"  python llm/finetune/train.py --train-file {args.out} "
          f"--out-dir models/qwen-invoice-tr")


if __name__ == "__main__":
    main()
