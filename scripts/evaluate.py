"""
Fine-tune'un ne kadar ise yaradigini olcer.

SROIE test setinde (347 ornek) alan alan dogruluk hesaplar. Egitim kaybi
(loss) bu projede zayif bir gostergedir: cevap tokenlarinin buyuk kismi sabit
JSON iskeleti oldugu icin baslangic kaybi bile dusuk cikar. Gercek soru
"alanlarin kaci dogru" ve cevabi ancak modelin hic gormedigi veride olculur.

Kullanim:
    # sadece base model
    python scripts/evaluate.py

    # sadece fine-tune edilmis model
    python scripts/evaluate.py --adapter models/qwen-invoice-lora

    # ONCESI/SONRASI karsilastirma tablosu (rapor icin asil istedigin bu)
    python scripts/evaluate.py --compare models/qwen-invoice-lora

    # hizli bakis (347 yerine 50 ornek)
    python scripts/evaluate.py --compare models/qwen-invoice-lora --limit 50
"""

import argparse
import json
import os
import re
import sys
import time

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "llm"))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "llm", "inference"))

from prompt import FIELDS  # noqa: E402


# --- karsilastirma ----------------------------------------------------------


def normalize(deger, alan: str):
    """
    Iki degeri karsilastirilabilir hale getirir.

    Ham string esitligi cok sert olurdu: 'ACME LTD' ile 'acme  ltd' ayni seydir,
    '9.00' ile '9.0' da oyle. Ote yandan fazla gevsek davranirsak gercek
    hatalari dogru sayariz. Orta yol: bosluk/buyuk-kucuk harf normalize edilir,
    tutar alani sayiya indirgenir.

    Bos string None'a cevrilir - base model 'yok' demek icin "" kullaniyor,
    fine-tune edilmis model null kullanmali. Ikisi de "deger yok" anlamina
    geldigi icin dogruluk hesabinda esit sayilir. Aradaki bicim farki ayrica
    'bos_string' sayaciyla raporlanir.
    """
    if deger is None:
        return None

    s = re.sub(r"\s+", " ", str(deger).strip().lower())
    if not s or s in ("null", "none", "n/a", "-"):
        return None

    if alan == "total_amount":
        # "1,18 TL" / "RM 9.00" / "9" -> "9.00"
        m = re.search(r"\d+(?:[.,]\d+)?", s.replace(" ", ""))
        if m:
            try:
                return f"{float(m.group(0).replace(',', '.')):.2f}"
            except ValueError:
                pass

    return s


def olc(tahminler: list, hedefler: list) -> dict:
    """Alan alan dogruluk + JSON bicim saglıgi olcer."""
    dogru = {alan: 0 for alan in FIELDS}
    bos_string = 0          # "" donulen alan sayisi (null donulmesi gerekirken)
    tam_eslesme = 0         # 5 alanin 5'i de dogru olan ornek sayisi
    tamamen_bos = 0         # hicbir alani doldurulamayan ornek (JSON bozuk olabilir)

    for tahmin, hedef in zip(tahminler, hedefler):
        hepsi_dogru = True
        for alan in FIELDS:
            t, h = tahmin.get(alan), hedef.get(alan)
            if isinstance(t, str) and not t.strip():
                bos_string += 1
            if normalize(t, alan) == normalize(h, alan):
                dogru[alan] += 1
            else:
                hepsi_dogru = False
        tam_eslesme += hepsi_dogru
        if all(tahmin.get(a) in (None, "") for a in FIELDS):
            tamamen_bos += 1

    n = len(hedefler)
    return {
        "n": n,
        "alan": {a: 100 * dogru[a] / n for a in FIELDS},
        "ortalama": 100 * sum(dogru.values()) / (n * len(FIELDS)),
        "tam_eslesme": 100 * tam_eslesme / n,
        "bos_string": bos_string,
        "tamamen_bos": tamamen_bos,
    }


# --- calistirma -------------------------------------------------------------


def ornekleri_oku(yol: str, limit=None) -> list:
    if not os.path.exists(yol):
        sys.exit(
            f"HATA: {yol} yok.\n"
            "  Once veriyi hazirlayin:  python llm/finetune/prepare_sroie.py"
        )
    ornekler = []
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if satir:
                ornekler.append(json.loads(satir))
            if limit and len(ornekler) >= limit:
                break
    if not ornekler:
        sys.exit(f"HATA: {yol} bos.")
    return ornekler


def calistir(ad: str, model_adi: str, adapter, ornekler: list, dort_bit: bool) -> list:
    from infer import InvoiceExtractor

    print(f"\n[{ad}] model yukleniyor" + (f" (adaptor: {adapter})" if adapter else " (base)"))
    extractor = InvoiceExtractor(
        model_name=model_adi, adapter_path=adapter, load_in_4bit=dort_bit
    )

    tahminler = []
    t0 = time.time()
    for i, ornek in enumerate(ornekler, 1):
        tahminler.append(extractor.extract(ornek["raw_text"]))
        if i % 25 == 0 or i == len(ornekler):
            gecen = time.time() - t0
            kalan = gecen / i * (len(ornekler) - i)
            print(f"  {i}/{len(ornekler)}  ({gecen:.0f} sn gecti, ~{kalan:.0f} sn kaldi)")

    # Bellegi bosalt: --compare ile iki model art arda yukleniyor
    del extractor
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass

    return tahminler


# --- raporlama --------------------------------------------------------------


def tek_rapor(ad: str, m: dict):
    print(f"\n=== {ad}  ({m['n']} ornek) ===")
    for alan in FIELDS:
        print(f"  {alan:<14} {m['alan'][alan]:5.1f}%")
    print(f"  {'-'*22}")
    print(f"  {'ORTALAMA':<14} {m['ortalama']:5.1f}%")
    print(f"  {'TAM ESLESME':<14} {m['tam_eslesme']:5.1f}%   (5 alanin 5'i de dogru)")
    if m["bos_string"]:
        print(f"  not: {m['bos_string']} alanda null yerine \"\" donuldu")
    if m["tamamen_bos"]:
        print(f"  not: {m['tamamen_bos']} ornekte hicbir alan doldurulamadi")


def karsilastirma_raporu(once: dict, sonra: dict):
    print(f"\n{'='*58}")
    print(f"  ONCESI / SONRASI  ({once['n']} test ornegi)")
    print(f"{'='*58}")
    print(f"  {'ALAN':<14} {'BASE':>8} {'FINE-TUNE':>11} {'FARK':>9}")
    print(f"  {'-'*44}")

    for alan in FIELDS:
        a, b = once["alan"][alan], sonra["alan"][alan]
        print(f"  {alan:<14} {a:7.1f}% {b:10.1f}% {b-a:+8.1f}")

    print(f"  {'-'*44}")
    for etiket, anahtar in (("ORTALAMA", "ortalama"), ("TAM ESLESME", "tam_eslesme")):
        a, b = once[anahtar], sonra[anahtar]
        print(f"  {etiket:<14} {a:7.1f}% {b:10.1f}% {b-a:+8.1f}")

    print(f"\n  null yerine \"\" donulen alan: {once['bos_string']} -> {sonra['bos_string']}")
    print(f"  hic doldurulamayan ornek  : {once['tamamen_bos']} -> {sonra['tamamen_bos']}")
    print(f"{'='*58}")


def on_kontrol(adaptor_yolu: str):
    """
    Adaptorun yuklenebilecegini SANIYELER icinde dogrular.

    Neden var: --compare once base modeli calistiriyordu (347 ornek, ~14 dk),
    adaptore sira en sonda geliyordu. Adaptor yuklenemezse yarim saatlik is
    cope gidiyordu. Buradaki kontroller milisaniye suruyor.
    """
    if not os.path.isdir(adaptor_yolu):
        sys.exit(f"HATA: adaptor klasoru yok -> {adaptor_yolu}")

    agirlik = any(
        os.path.exists(os.path.join(adaptor_yolu, ad))
        for ad in ("adapter_model.safetensors", "adapter_model.bin")
    )
    if not agirlik:
        sys.exit(
            f"HATA: {adaptor_yolu} icinde adapter_model.safetensors yok.\n"
            "  Bu klasor bir LoRA adaptoru degil ya da egitim yarim kalmis."
        )

    # peft'in kendi torchao kontrolunu burada tetikliyoruz. Kaggle imajindaki
    # torchao surumu peft'in bekledigi minimumdan eski oldugunda peft, o
    # dispatcher'i atlamak yerine ImportError firlatiyor. torchao'yu hic
    # kullanmiyoruz; paket kurulu degilse peft sessizce geciyor.
    try:
        from peft.import_utils import is_torchao_available
    except Exception:
        return  # peft'in ic yapisi degismis; asil yuklemede zaten anlasilir

    try:
        is_torchao_available()
    except ImportError as e:
        sys.exit(
            f"HATA: adaptor yuklenemez -> {e}\n"
            "\n"
            "  Cozum:  python -m pip uninstall -y torchao\n"
            "\n"
            "  torchao'yu kullanmiyoruz, sadece peft'in yolunun ustunde duruyor.\n"
            "  Kaggle oturumu yeniden baslayinca temel imaj geri geldigi icin\n"
            "  bu paket tekrar kurulu hale gelir; kaldirma islemi tekrarlanmali."
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    p.add_argument("--test-file", default="data/sroie_test.jsonl")
    p.add_argument("--adapter", default=None, help="Tek model degerlendir")
    p.add_argument("--compare", default=None, metavar="ADAPTER",
                   help="Base ile adaptoru art arda calistirip fark tablosu bas")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--4bit", dest="dort_bit", action="store_true")
    p.add_argument("--out", default=None, help="Sonuclari JSON olarak kaydet")
    args = p.parse_args()

    ornekler = ornekleri_oku(args.test_file, args.limit)
    hedefler = [o["target"] for o in ornekler]
    print(f"Test seti: {args.test_file}  ({len(ornekler)} ornek)")

    sonuc = {}
    if args.compare:
        on_kontrol(args.compare)
        # Adaptorlu model ONCE calisiyor: bir sorun varsa 14 dakikalik base
        # turundan sonra degil, hemen ortaya ciksin. Rapor sirasi degismiyor.
        sonra = olc(calistir("FINE-TUNE", args.model, args.compare, ornekler, args.dort_bit), hedefler)
        once = olc(calistir("BASE", args.model, None, ornekler, args.dort_bit), hedefler)
        tek_rapor("BASE MODEL", once)
        tek_rapor("FINE-TUNE EDILMIS", sonra)
        karsilastirma_raporu(once, sonra)
        sonuc = {"base": once, "finetuned": sonra}
    else:
        if args.adapter:
            on_kontrol(args.adapter)
        ad = "FINE-TUNE EDILMIS" if args.adapter else "BASE MODEL"
        m = olc(calistir(ad, args.model, args.adapter, ornekler, args.dort_bit), hedefler)
        tek_rapor(ad, m)
        sonuc = {"finetuned" if args.adapter else "base": m}

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(sonuc, f, indent=2, ensure_ascii=False)
        print(f"\nSonuclar kaydedildi: {args.out}")


if __name__ == "__main__":
    main()
