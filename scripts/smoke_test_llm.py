"""
LLM katmani duman testi (Kaggle T4 uzerinde calistirmak icin).

OCR'i devreye sokmadan, elde hazir ham metinlerle InvoiceExtractor'i dener.
Amac: model yukleniyor mu, GPU gorunuyor mu, cikti gercekten JSON mu?

Kullanim:
    python scripts/smoke_test_llm.py
    python scripts/smoke_test_llm.py --adapter models/qwen-invoice-lora
"""

import argparse
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "llm", "inference"))
from infer import InvoiceExtractor  # noqa: E402

# SROIE tarzi, gercek OCR ciktisina benzer ornekler (dagitik ve gurultulu)
ORNEKLER = [
    (
        "duz fis",
        """TAN WOON YANN
BOOK TA .K(TAMAN DAYA) SDN BHD
789417-W
NO.53 55,57 & 59, JALAN SAGU 18,
TAMAN DAYA,
81100 JOHOR BAHRU,
JOHOR.
DOCUMENT NO : TD01167104
DATE: 25/12/2018 8:13:39 PM
CASHIER: MANIS
MEMBER
CASH BILL
9556939040116 KF MODELLING CLAY KIDDY FISH
1 PC * 9.000 9.00
TOTAL: 9.00
ROUNDING ADJUSTMENT: 0.00
CASH: 10.00
CHANGE: 1.00""",
    ),
    (
        "alanlari eksik fis",
        """SYARIKAT PERNIAGAAN GIN KEE
NO 290, JALAN AIR PANAS,
SETAPAK,
53200, KUALA LUMPUR.
INVOICE
CASH
TOTAL AMOUNT 60.30""",
    ),
    (
        "bos metin (savunma testi)",
        "",
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default=None, help="Fine-tune sonrasi LoRA adaptor klasoru")
    parser.add_argument("--load-in-4bit", action="store_true", help="4-bit yukle (GPU gerekir)")
    args = parser.parse_args()

    print("Model yukleniyor...")
    t0 = time.time()
    extractor = InvoiceExtractor(adapter_path=args.adapter, load_in_4bit=args.load_in_4bit)
    print(f"Yuklendi ({time.time() - t0:.1f} sn)  |  cihaz: {extractor.model.device}")
    if args.adapter:
        print(f"LoRA adaptoru: {args.adapter}")
    print()

    for isim, metin in ORNEKLER:
        t0 = time.time()
        sonuc = extractor.extract(metin)
        sure = time.time() - t0

        dolu = sum(1 for v in sonuc.values() if v not in (None, ""))
        print(f"--- {isim}  ({sure:.1f} sn, {dolu}/{len(sonuc)} alan dolu) ---")
        print(json.dumps(sonuc, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
