"""
Fis/fatura kategorilendirme.

Ayiklama modeline dokunmuyoruz: o SROIE'nin 5 alanli prompt'uyla egitildi ve
olculen %89 dogruluk oradan geliyor. Altinci bir alan eklemek egitim ile
calisma anindaki prompt uyumunu bozar (bkz. llm/prompt.py) ve yeniden egitim
gerektirir. Bu yuzden kategori AYRI bir adim.

Iki asamali calisiyor:
    1. Anahtar kelime - taninan zincirler ve acik ifadeler icin. Hizli ve
       kesin: "SHELL" gorunce akaryakit oldugundan supheye gerek yok.
    2. LLM - kelime tutmazsa. Kapali listeden secim yapmasi isteniyor,
       listede olmayan bir sey uretirse "Diger"e dusuyor.

Anahtar kelime tablosunda YALNIZCA yuksek guvenli ifadeler var. "gida" gibi
belirsiz kelimeler bilerek disarida: "TULU GIDA" bir kahveci cikti, market
degil. Belirsiz olanlari LLM'e birakiyoruz.
"""

import re

KATEGORILER = [
    "Market",
    "Akaryakıt",
    "Yemek/Restoran",
    "Giyim",
    "Kırtasiye/Ofis",
    "Konaklama",
    "Ulaşım",
    "Telekom/İnternet",
    "Fatura",
    "Sağlık",
    "Eğlence",
    "Banka/Finans",
    "Kargo/Posta",
    "Bağış/Aidat",
    "Diğer",
]

VARSAYILAN = "Diğer"

# Kucuk harfe cevrilmis metinde aranan ifadeler.
ANAHTAR_KELIMELER = {
    "Market": [
        "migros", "bim ", "a101", "şok market", "sok market", "carrefour",
        "macrocenter", "tarım kredi", "metro market", "hipermarket",
        "süpermarket", "supermarket",
    ],
    "Akaryakıt": [
        "shell", "opet", "petrol ofisi", "petrolofisi", "lukoil", "aytemiz",
        "akaryakıt", "akaryakit", "motorin", "kurşunsuz", "kursunsuz",
        "benzin", "dizel", "lpg",
    ],
    "Yemek/Restoran": [
        "restoran", "restaurant", "lokanta", "kahve dünyası", "kahve dunyasi",
        "starbucks", "kafe", "cafe", "pastane", "fırın", "firin", "pizza",
        "burger", "döner", "doner", "çay bahçesi", "kebap", "bistro",
        "espresso", "latte", "büfe", "bufe", "bife", "coffee", "coffy",
        "kahvaltı", "kahvalti", "tost", "sandviç", "sandvic", "çay ocağı",
        "yemek", "mutfak", "sofra", "izgara", "balık evi",
    ],
    "Kırtasiye/Ofis": [
        "kırtasiye", "kirtasiye", "office", "ofis malzeme", "toner", "kartuş",
        "kartus", "fotokopi", "matbaa",
    ],
    "Konaklama": [
        "otel", "hotel", "konaklama", "pansiyon", "hostel", "resort",
    ],
    "Ulaşım": [
        "taksi", "uber", "bitaksi", "havaş", "havas", "otogar", "thy",
        "türk hava yolları", "turk hava yollari", "pegasus",
        "otoyol", "hgs", "ogs", "köprü geçiş", "kopru gecis", "otopark",
    ],
    "Telekom/İnternet": [
        "turkcell", "vodafone", "türk telekom", "turk telekom", "ttnet",
        "superonline", "turknet", "millenicom",
    ],
    "Fatura": [
        "elektrik", "doğalgaz", "dogalgaz", "su ve kanalizasyon", "aski",
        "iski", "başkentgaz", "baskentgaz", "igdaş", "igdas", "enerjisa",
        "ayedaş", "ayedas", "bedaş", "bedas",
    ],
    "Giyim": [
        "tekstil", "giyim", "konfeksiyon", "mango", "lc waikiki", "koton",
        "defacto", "boyner", "ayakkabı", "ayakkabi", "deri", "moda",
    ],
    "Eğlence": [
        "sinema", "cinemaximum", "cinema", "tiyatro", "konser", "müze",
        "muze", "spor salonu", "fitness", "oyun",
    ],
    "Banka/Finans": [
        "bankası", "bankasi", "bank a.ş", "bank a.s", "havale", "eft ücreti",
        "eft ucreti", "hesap işletim", "hesap isletim", "komisyon bedeli",
    ],
    "Kargo/Posta": [
        "kargo", "ptt", "yurtiçi kargo", "yurtici kargo", "aras kargo",
        "mng kargo", "sürat kargo", "surat kargo",
    ],
    "Bağış/Aidat": [
        "bağış", "bagis", "dernek", "vakıf", "vakif", "aidat",
        "güçlendirme", "guclendirme", "yardımlaşma", "yardimlasma",
    ],
    "Sağlık": [
        "eczane", "hastane", "tıp merkezi", "tip merkezi", "poliklinik",
        "diş", "laboratuvar", "medical", "sağlık", "saglik",
    ],
}

SISTEM_PROMPT = (
    "You classify Turkish receipts and invoices into exactly one expense category.\n"
    "Allowed categories (answer with one of these, nothing else):\n"
    + "\n".join(f"- {k}" for k in KATEGORILER)
    + "\nRules:\n"
    "- Answer with the category name only. No explanation, no punctuation.\n"
    "- Base your decision mainly on the company name and the purchased items.\n"
    "- If you cannot tell, answer Diğer."
)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower())


def anahtar_kelimeyle_bul(firma: str, raw_text: str):
    """
    Taninan ifadelere gore kategori dondurur; emin degilse None.

    Firma adina raw_text'ten daha cok agirlik veriliyor: fisin govdesinde
    gecen bir kelime (ornegin urun listesindeki "kahve") isletmenin turunu
    yansitmayabilir, firma adi yansitir.
    """
    ad = _normalize(firma)
    govde = _normalize(raw_text)

    puanlar = {}
    for kategori, kelimeler in ANAHTAR_KELIMELER.items():
        puan = 0
        for kelime in kelimeler:
            if kelime in ad:
                puan += 3
            elif kelime in govde:
                puan += 1
        if puan:
            puanlar[kategori] = puan

    if not puanlar:
        return None

    en_iyi = max(puanlar.values())
    kazananlar = [k for k, p in puanlar.items() if p == en_iyi]
    # Beraberlik varsa karar veremiyoruz demektir; LLM'e birakalim.
    return kazananlar[0] if len(kazananlar) == 1 else None


def cevabi_esle(cevap: str) -> str:
    """
    LLM ciktisini gecerli bir kategoriye esler.

    Model bazen "Category: Market" ya da "market." gibi seyler donduruyor;
    listedeki adlardan biri metnin icinde geciyorsa onu kabul ediyoruz.
    Hicbiri gecmiyorsa uydurmasina izin vermeyip Diger'e dusuyoruz.
    """
    c = _normalize(cevap)
    for kategori in KATEGORILER:
        if _normalize(kategori) in c:
            return kategori
    # Turkce karakter kaybi ihtimaline karsi sadelestirilmis karsilastirma
    sade = lambda s: re.sub(r"[^a-z]", "", _normalize(s)
                            .replace("ı", "i").replace("ğ", "g").replace("ü", "u")
                            .replace("ş", "s").replace("ö", "o").replace("ç", "c"))
    cs = sade(cevap)
    for kategori in KATEGORILER:
        if sade(kategori) and sade(kategori) in cs:
            return kategori
    return VARSAYILAN


def build_messages(firma: str, raw_text: str, azami_karakter: int = 1200):
    """Siniflandirma icin chat mesaj listesi uretir."""
    metin = (raw_text or "")[:azami_karakter]
    return [
        {"role": "system", "content": SISTEM_PROMPT},
        {
            "role": "user",
            "content": f"Company: {firma or '(unknown)'}\n\nRECEIPT TEXT:\n{metin}",
        },
    ]
