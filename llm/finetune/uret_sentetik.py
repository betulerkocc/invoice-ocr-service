"""
Sentetik Turkce fis/fatura egitim verisi uretir.

Neden gerekli: elimizde 39 gercek Turkce fis var, SROIE'de ise 626 Ingilizce
ornek. Karistirinca Turkce oran %6'da kaliyor ve model Turkce etiketleri
(TOPLAM, FIS NO, KDV) SROIE'nin agirligi altinda ogrenemiyor.

Sentetik veri gercegin yerini TUTMAZ - burusuk termal kagit, silik baski,
sira disi duzenler taklit edilemiyor. Ama ogretebildigi seyler yapisal ve
onlar da gercekten gerekli:

  - TOPLAM genel toplamdir, ARA TOPLAM degildir
  - FIS NO / BELGE NO / VKN etiketlerinin ne oldugu
  - 10.250,75 bicimi (nokta binlik, virgul ondalik)
  - Turk fisinin yerlesimi: firma ustte, kalemler ortada, toplam altta

Uretilen metin gercek OCR ciktisini taklit ediyor: satir bolunmeleri,
Turkce karakter karismalari (I/I, U/U, S/S), ondalik ayiracindan sonra
bosluk. Bu gurultuler gercek verimizde olculdu.

Kullanim:
    python llm/finetune/uret_sentetik.py --adet 250
    python llm/finetune/uret_sentetik.py --adet 250 --tohum 7 --out data/sentetik.jsonl
"""

import argparse
import json
import os
import random
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, ".."))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "inference"))

from prompt import FIELDS  # noqa: E402

# --- sozlukler ---------------------------------------------------------------

ISLETME_TURLERI = [
    # (tur, firma sonekleri, urun havuzu)
    ("market", ["GIDA SAN. VE TİC. LTD. ŞTİ.", "MARKET LTD. ŞTİ.",
                "PERAKENDE GIDA SANAYİ TİC. A.Ş.", "TİCARET A.Ş."],
     ["EKMEK TAM BUĞDAY", "SÜT 1L", "PEYNİR BEYAZ 500G", "YOĞURT 1KG",
      "ZEYTİN SİYAH 400G", "ÇAY 1KG", "ŞEKER 1KG", "MAKARNA 500G",
      "AYÇİÇEK YAĞI 1L", "DETERJAN 2.5KG", "YUMURTA 15Lİ", "DOMATES KG"]),
    ("kafe", ["GIDA LİMİTED ŞİRKETİ", "KAHVE VE GIDA A.Ş.", "BÜFE",
              "TURİZM GIDA SAN. TİC. LTD."],
     ["TÜRK KAHVESİ", "ESPRESSO", "LATTE", "ÇAY", "CHEESECAKE",
      "SANDVİÇ", "TOST", "LİMONATA", "SU 500ML", "KRUVASAN"]),
    ("akaryakit", ["PETROL ÜRÜNLERİ VE TAŞ. TİC. LTD. ŞTİ.",
                   "AKARYAKIT SAN. TİC. A.Ş.", "PETROL LTD. ŞTİ."],
     ["KURŞUNSUZ 95", "MOTORİN", "LPG OTOGAZ", "V/POWER DİZEL"]),
    ("eczane", ["ECZANESİ", "ECZANE LTD. ŞTİ."],
     ["PARASETAMOL 500MG", "C VİTAMİNİ", "BANDAJ", "ÖKSÜRÜK ŞURUBU",
      "AĞRI KESİCİ", "TERMOMETRE"]),
    ("kirtasiye", ["KIRTASİYE LTD. ŞTİ.", "OFİS MALZEMELERİ TİC."],
     ["A4 KAĞIT 500'LÜ", "TÜKENMEZ KALEM", "DOSYA", "TONER", "ZIMBA TELİ"]),
]

ADLAR = ["ANADOLU", "BEREKET", "GÜNEŞ", "YILDIZ", "MARMARA", "EGE", "TOROS",
         "SELÇUK", "ATLAS", "PINAR", "ÇINAR", "AKSU", "DENİZ", "ŞAFAK",
         "GÜVEN", "UMUT", "BAŞAK", "MERİÇ", "KARDELEN", "ZÜMRÜT"]

MAHALLELER = ["ATATÜRK MAH.", "CUMHURİYET MAH.", "BEŞTEPE MAH.", "YENİMAHALLE",
              "KIZILAY MAH.", "BAHÇELİEVLER MAH.", "FATİH MAH.", "ÇANKAYA MAH."]
CADDELER = ["GAZİ BULVARI", "İSTİKLAL CAD.", "DUMLUPINAR BLV.", "ATATÜRK CAD.",
            "MİLLİ EGEMENLİK CAD.", "İNÖNÜ CAD.", "SAKARYA SOK."]
ILCE_IL = ["ÇANKAYA/ANKARA", "YENİMAHALLE/ANKARA", "KADIKÖY/İSTANBUL",
           "KONAK/İZMİR", "NİLÜFER/BURSA", "SELÇUKLU/KONYA", "KARESİ/BALIKESİR"]

TOPLAM_ETIKETLERI = ["TOPLAM", "GENEL TOPLAM", "ÖDENECEK TUTAR", "TOPLAM TUTAR"]
BELGE_ETIKETLERI = ["FİŞ NO", "FIS NO", "BELGE NO", "FATURA NO", "FATURA NUMARASI"]
TARIH_ETIKETLERI = ["TARİH", "TARIH", "FATURA TARİHİ", "BELGE TARİHİ"]


# --- OCR gurultusu -----------------------------------------------------------
#
# Gercek verimizde olculen karismalar. PaddleOCR Turkce noktali/noktasiz
# harfleri ve bazi rakam-harf ciftlerini duzenli olarak karistiriyor.
KARISMALAR = {
    "İ": ["I", "i", "İ", "1"], "I": ["I", "l", "İ"], "ı": ["i", "ı", "l"],
    "Ü": ["U", "Ü", "Ii"], "ü": ["u", "ü"], "Ş": ["S", "Ş", "$"],
    "ş": ["s", "ş"], "Ğ": ["G", "Ğ"], "ğ": ["g", "ğ"],
    "Ö": ["O", "Ö", "0"], "ö": ["o", "ö"], "Ç": ["C", "Ç"], "ç": ["c", "ç"],
    "O": ["O", "0"], "0": ["0", "O"], "S": ["S", "5"], "B": ["B", "8"],
}


def gurultule(metin: str, rnd: random.Random, olasilik: float = 0.16) -> str:
    """
    Metne gercekci OCR gurultusu ekler.

    Olasilik dusuk tutuluyor: amac metni okunmaz yapmak degil, modelin
    "IIMITED" gordugunde "LİMİTED" anlamasini ogretmek. Cok gurultu
    ogrenilemez ornek uretir.
    """
    return "".join(
        rnd.choice(KARISMALAR[k]) if k in KARISMALAR and rnd.random() < olasilik else k
        for k in metin
    )


def tutar_yaz(deger: float, rnd: random.Random) -> str:
    """Turk bicimiyle tutar metni (bazen OCR'in ekledigi bosluklarla)."""
    tam = int(deger)
    kurus = int(round((deger - tam) * 100))
    binlikli = f"{tam:,}".replace(",", ".")
    s = f"{binlikli},{kurus:02d}"
    # OCR ondalik ayiracindan sonra bazen bosluk birakiyor
    if rnd.random() < 0.12:
        s = s.replace(",", ", ", 1)
    return s


# --- fis uretimi -------------------------------------------------------------


def fis_uret(rnd: random.Random) -> dict:
    """Bir fis icin (ham metin, hedef) cifti uretir."""
    tur, sonekler, urunler = rnd.choice(ISLETME_TURLERI)
    firma = f"{rnd.choice(ADLAR)} {rnd.choice(sonekler)}"
    adres = f"{rnd.choice(MAHALLELER)} {rnd.choice(CADDELER)} NO {rnd.randint(1, 240)}"
    ilce = rnd.choice(ILCE_IL)
    tarih = f"{rnd.randint(1,28):02d}.{rnd.randint(1,12):02d}.{rnd.choice([2024,2025,2026])}"
    belge_no = rnd.choice([
        f"{rnd.randint(1, 9999):04d}",
        f"{rnd.choice('ABCDEFGHJKMNP')}{rnd.randint(100000, 999999)}",
        f"EM-{rnd.choice([2024,2025,2026])}-{rnd.randint(1, 9999):04d}",
    ])
    vkn = f"{rnd.randint(1000000000, 9999999999)}"

    # Kalemler ve tutarlar
    kalem_sayisi = rnd.randint(1, 8)
    kalemler = []
    ara_toplam = 0.0
    for _ in range(kalem_sayisi):
        fiyat = round(rnd.uniform(3, 480), 2)
        ara_toplam += fiyat
        kalemler.append((rnd.choice(urunler), fiyat))
    ara_toplam = round(ara_toplam, 2)

    kdv_orani = rnd.choice([1, 10, 20])
    kdv = round(ara_toplam * kdv_orani / (100 + kdv_orani), 2)
    toplam = ara_toplam  # Turk fislerinde toplam KDV dahildir

    toplam_etiketi = rnd.choice(TOPLAM_ETIKETLERI)
    belge_etiketi = rnd.choice(BELGE_ETIKETLERI)
    tarih_etiketi = rnd.choice(TARIH_ETIKETLERI)

    toplam_metni = tutar_yaz(toplam, rnd)
    kdv_metni = tutar_yaz(kdv, rnd)

    # --- satirlari kur ---
    satirlar = [firma]
    if rnd.random() < 0.85:
        satirlar.append(adres)
        satirlar.append(ilce)
    if rnd.random() < 0.6:
        satirlar.append(f"VKN: {vkn}")
    satirlar.append("")

    # Etiket ve deger bazen ayni satirda, bazen alt alta - OCR ikisini de uretiyor
    def etiketli(etiket: str, deger: str):
        if rnd.random() < 0.55:
            satirlar.append(f"{etiket}: {deger}")
        else:
            satirlar.extend([etiket, deger])

    etiketli(tarih_etiketi, tarih)
    etiketli(belge_etiketi, belge_no)
    satirlar.append("")

    for ad, fiyat in kalemler:
        if rnd.random() < 0.5:
            satirlar.append(f"{ad}  {tutar_yaz(fiyat, rnd)}")
        else:
            satirlar.extend([ad, f"%{kdv_orani}", f"*{tutar_yaz(fiyat, rnd)}"])
    satirlar.append("")

    if rnd.random() < 0.7:
        etiketli("ARA TOPLAM", tutar_yaz(ara_toplam, rnd))
    etiketli(rnd.choice(["TOPKDV", "TOPLAM KDV", f"KDV %{kdv_orani}"]), kdv_metni)
    etiketli(toplam_etiketi, toplam_metni)

    if rnd.random() < 0.6:
        satirlar.append(rnd.choice(["NAKİT", "KREDİ KARTI", "BANKA KARTI"]))
        satirlar.append(tutar_yaz(toplam, rnd))

    ham = "\n".join(satirlar)

    # Gurultu SADECE harflere: tutarlar ve numaralar bozulursa hedef
    # girdiden turetilemez hale gelir ve ornek ogrenilemez olur.
    ham = "\n".join(
        gurultule(s, rnd) if not any(k.isdigit() for k in s) else s
        for s in ham.split("\n")
    )

    hedef = {
        "company_name": firma,
        "date": tarih,
        "address": f"{adres} {ilce}",
        "total_amount": toplam_metni.replace(", ", ","),
        "invoice_no": belge_no,
    }

    # Hedef girdiden turetilebilir olmali. Adres bu fise hic konmadiysa ya da
    # gurultu onu tanimazlik derecesinde bozduysa hedefte de olmamali; aksi
    # halde modele "girdide olmayani uret" ogretmis oluruz.
    from infer import _metinde_benziyor_mu

    if not _metinde_benziyor_mu(hedef["address"], ham):
        hedef["address"] = None

    return {"raw_text": ham, "target": {a: hedef.get(a) for a in FIELDS},
            "kaynak": "sentetik"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--adet", type=int, default=250)
    p.add_argument("--out", default="data/sentetik_train.jsonl")
    p.add_argument("--tohum", type=int, default=42)
    p.add_argument("--ornek-goster", type=int, default=1)
    args = p.parse_args()

    rnd = random.Random(args.tohum)
    ornekler = [fis_uret(rnd) for _ in range(args.adet)]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for o in ornekler:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    print(f"{len(ornekler)} sentetik ornek -> {args.out}")
    print()
    for alan in FIELDS:
        dolu = sum(1 for o in ornekler if o["target"].get(alan))
        print(f"  {alan:<14} {dolu:>4}/{len(ornekler)}  ({100*dolu/len(ornekler):.0f}%)")

    for o in ornekler[: args.ornek_goster]:
        print("\n" + "=" * 54)
        print(o["raw_text"])
        print("-" * 54)
        print(json.dumps(o["target"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
