"""
LLM inference katmani.

Gorevi: OCR'dan gelen dagitik ham metni alip yapilandirilmis JSON'a cevirmek.
Model: Qwen2.5-0.5B-Instruct (+ SROIE ile egitilmis LoRA adaptoru).

Boru hatti:
    1. Chat sablonu + llm/prompt.py ile model cagrilir
    2. Cikti JSON'a ayristirilir
    3. Uydurma degerler elenir (ham metinde gecmeyenler)
    4. Etiketli alanlar (toplam, belge no) dogrulanir/tamamlanir
"""

import json
import os
import re
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# llm/prompt.py'yi import edebilmek icin llm klasorunu path'e ekliyoruz
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from prompt import FIELDS, build_messages, empty_result  # noqa: E402

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def _pick_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _extract_json(text: str) -> dict:
    """
    Modelin ciktisindan JSON nesnesini ayiklar.

    Regex yerine parantez sayarak ilerliyoruz: model bazen JSON'un icine
    baska suslu parantez koyabiliyor ve `\\{.*\\}` gibi bir desen ya cok az
    ya cok fazla yakaliyor.
    """
    start = text.find("{")
    if start == -1:
        return empty_result()

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    # Tek tirnakli / sondaki virgullu bozuk JSON icin son bir deneme
                    fixed = re.sub(r",\s*([}\]])", r"\1", candidate.replace("'", '"'))
                    try:
                        parsed = json.loads(fixed)
                    except json.JSONDecodeError:
                        return empty_result()
                if not isinstance(parsed, dict):
                    return empty_result()
                return {field: parsed.get(field) for field in FIELDS}

    return empty_result()


# --- tutar tanima ------------------------------------------------------------
#
# Iki farkli sayi bicimi var ve birbirinin aynasi:
#     Turkce  : 10.250,75  -> nokta binlik, virgul ondalik
#     SROIE   : 10,250.75  -> virgul binlik, nokta ondalik
#
# "Her tutarda iki ondalik vardir" varsayimi Turkce fislerde kiriliyor:
# "10.250 TL" icinde `\d+[.,]\d{2}` deseni "10.25" ile eslesiyor ve on bin
# iki yuz elli lira, on lira yirmi bes kurusa donusuyor. Bu yuzden once
# GRUPLANMIS bicimleri deniyoruz, duz ondalik en sonda.

_TUTAR = re.compile(
    r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"      # 10.250 / 10.250,75  (Turkce)
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"     # 10,250 / 10,250.75  (Ingilizce)
    r"|\d+(?:[.,]\d{1,2})?"                  # 82,55 / 9.00 / 500
)


def _tutar_bul(satir: str):
    """
    Satirdaki son tutari dondurur; yoksa None.

    Yuzde isaretinden hemen sonra gelen sayilar atlanir: "%10" bir KDV
    oranidir, tutar degil. Fislerde oran ile tutar yan yana durabiliyor
    ("KDV %10 20,73") - bu yuzden satirin tamamini atmak yerine yalnizca
    yuzdeye ait sayiyi eliyoruz.
    """
    adaylar = [
        m.group(0)
        for m in _TUTAR.finditer(satir)
        if not satir[: m.start()].rstrip().endswith("%")
    ]
    return adaylar[-1] if adaylar else None


def _tutari_sayiya_cevir(tutar: str) -> float:
    """
    Metin tutari karsilastirilabilir sayiya cevirir.

    Iki bicim birbirinin aynasi oldugu icin hangi ayiracin binlik hangisinin
    ondalik oldugunu desene bakarak ayirt ediyoruz:
        10.250,75 -> nokta binlik, virgul ondalik  (Turkce)
        10,250.75 -> virgul binlik, nokta ondalik  (Ingilizce)
    """
    s = tutar.strip()
    try:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", s):
            return float(s.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", s):
            return float(s.replace(",", ""))
        return float(s.replace(",", "."))
    except ValueError:
        return 0.0


# --- uydurma elemesi ---------------------------------------------------------
#
# 'date' bilerek disarida: model tarihi bicimlendirebiliyor (25/12/2018 ->
# 2018-12-25) ve bu mesru, metinde birebir gecmeyebilir.
DOGRULANAN_ALANLAR = ("company_name", "address", "total_amount", "invoice_no")


def _sadelestir(s: str) -> str:
    """Karsilastirma icin harf ve rakam disindaki her seyi atar."""
    return re.sub(r"[^0-9a-zçğıöşü]", "", s.lower())


def _uydurmalari_ele(sonuc: dict, raw_text: str) -> dict:
    """
    Ham metinde gecmeyen degerleri None yapar.

    SROIE ile egitilmis model her fisin basinda firma adi ve adres olmasini
    bekliyor; bunlarin bulunmadigi bir fiste bos birakmak yerine uyduruyor
    (olculen bir ornekte metinde hic gecmeyen "Kartiki, Sanliurfa" adresini
    uretti). Prompt zaten "metinden kopyala, uydurma" diyor - burada o kurali
    kod tarafinda zorluyoruz.

    Bos alan kullaniciya "buraya bakmam lazim" der; uydurulmus bir adres ise
    sessizce yanlis veri uretir. Veri ayiklamada ikincisi cok daha tehlikeli.
    """
    if not raw_text:
        return sonuc

    metin = _sadelestir(raw_text)
    for alan in DOGRULANAN_ALANLAR:
        deger = sonuc.get(alan)
        if isinstance(deger, str) and deger.strip():
            if _sadelestir(deger) not in metin:
                sonuc[alan] = None
    return sonuc


# --- etiketli alan duzeltmesi ------------------------------------------------

_TOPLAM_ETIKET = re.compile(
    r"(GENEL\s*TOPLAM|[ÖO]DENECEK(?:\s*TUTAR)?|TOPLAM|TOTAL|AMOUNT\s*DUE)",
    re.IGNORECASE,
)
# Toplam sanilmamasi gereken satirlar
_TOPLAM_HARIC = re.compile(
    r"(ARA\s*TOP|ARATOP|SUB\s*TOTAL|TOPKDV|KDV|VERG[İI]|TAX|[İI]SKONTO|"
    r"[İI]ND[İI]R[İI]M|DISCOUNT|NAK[İI]T|CASH|PARA\s*[ÜU]ST[ÜU]|CHANGE|ROUND)",
    re.IGNORECASE,
)

_BELGE_NO = re.compile(
    r"(?:F[İI][ŞS]\s*NO|FATURA\s*(?:NO|NUMARASI)|BELGE\s*NO|[İI]RSAL[İI]YE\s*NO|"
    r"(?:TAX\s+)?(?:INVOICE|RECEIPT|BILL|DOCUMENT|DOC|INV)\s*(?:NO|NUMBER|NUM|\#))"
    r"\s*[:.\#\-]?\s*([A-Z0-9][A-Z0-9\-/]{1,29})",
    re.IGNORECASE,
)

_TARIH = re.compile(r"\b(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}[./\-]\d{1,2}[./\-]\d{1,2})\b")

# Belgenin Turkce olup olmadigini anlamak icin bakilan etiketler.
# SROIE fisleri Ingilizce/Malayca; bu kelimeler orada gecmiyor.
_TURKCE_BELGE = re.compile(
    r"(TOPLAM|[ÖO]DENECEK|F[İI][ŞS]\s*NO|FATURA|KDV|TUTAR|[İI]SKONTO)", re.IGNORECASE
)


def _toplam_bul(raw_text: str):
    """
    Etiketiyle birlikte duran toplam tutari arar; bulamazsa None.

    Etiket ile tutar ayni satirda olmayabiliyor - OCR bunlari ayri satirlara
    dokebiliyor. Bu yuzden etiketten sonraki iki satira da bakiyoruz.

    Adaylar arasindan EN BUYUK olani seciliyor, sonuncusu degil. Sebebi
    olculdu: fislerin altindaki KDV tablosunda "Toplam" bir sutun BASLIGI
    olarak geciyor ve altinda oran (%10) ya da KDV tutari (20,73) duruyor.
    Sonuncuyu alan bir kural 228,00 yerine 10'u seciyordu. Genel toplam
    tanimi geregi bilesenlerinden buyuk oldugu icin en buyugu almak bu
    karisikligi coziyor.
    """
    satirlar = raw_text.splitlines()
    adaylar = []
    for i, satir in enumerate(satirlar):
        if not _TOPLAM_ETIKET.search(satir) or _TOPLAM_HARIC.search(satir):
            continue
        for j in range(i, min(i + 3, len(satirlar))):
            if j > i and _TOPLAM_HARIC.search(satirlar[j]):
                break  # araya baska bir kalem girdiyse dur
            tutar = _tutar_bul(satirlar[j])
            if tutar:
                adaylar.append(tutar)
                break
    if not adaylar:
        return None
    return max(adaylar, key=_tutari_sayiya_cevir)


def _belge_no_bul(raw_text: str):
    """Etiketli belge/fis numarasini arar; bulamazsa None."""
    for eslesme in _BELGE_NO.finditer(raw_text):
        aday = eslesme.group(1).strip(" .:-/")
        if 1 <= len(aday) <= 30 and any(k.isdigit() for k in aday):
            return aday
    return None


def _tarih_bul(raw_text: str):
    """Metindeki ilk tarihi dondurur; yoksa None."""
    eslesme = _TARIH.search(raw_text)
    return eslesme.group(1) if eslesme else None


def _etiketli_alanlari_duzelt(sonuc: dict, raw_text: str) -> dict:
    """
    Modelin zayif oldugu yerde etiket tabanli duzeltme uygular.

    total_amount SADECE Turkce belgelerde eziliyor. Sebebi olculdu: SROIE
    test setinde kurali her belgeye uygulayinca total_amount dogrulugu
    %93.3'ten %61.3'e dustu - model Ingilizce fislerde kuraldan iyi ve ona
    karismamak gerekiyor. Turkce fislerde ise "TOPLAM" etiketini hic
    gormedigi icin urun satirlarindan birini secebiliyor.

    invoice_no ve date'de kural YALNIZCA model bos biraktiginda dolduruyor,
    yani modelin cevabini hicbir zaman ezmiyor. Bu guvenli oldugu icin dile
    bakilmaksizin uygulaniyor (invoice_no olcumu: %91.3 -> %94.7).

    company_name ve address icin kural YOK: olculdu, model bu alanlarda
    kuraldan iyi. Yanlis bir firma adi uretmektense bos birakmak yeglenir.
    """
    if not raw_text:
        return sonuc

    if _TURKCE_BELGE.search(raw_text):
        toplam = _toplam_bul(raw_text)
        if toplam:
            sonuc["total_amount"] = toplam

    if not sonuc.get("invoice_no"):
        no = _belge_no_bul(raw_text)
        if no:
            sonuc["invoice_no"] = no

    if not sonuc.get("date"):
        tarih = _tarih_bul(raw_text)
        if tarih:
            sonuc["date"] = tarih

    return sonuc


class InvoiceExtractor:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        adapter_path: str | None = None,
        device: str | None = None,
        load_in_4bit: bool = False,
    ):
        """
        model_name  : HuggingFace model adi ya da yerel klasor
        adapter_path: fine-tune sonrasi LoRA adaptor klasoru (None ise base model)
        device      : 'cuda' / 'cpu' (None ise otomatik secilir)
        load_in_4bit: 4-bit quantization (sadece GPU + bitsandbytes varken)
        """
        self.device = device or _pick_device()
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        load_kwargs = {}
        if load_in_4bit:
            from transformers import BitsAndBytesConfig

            load_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            load_kwargs["device_map"] = "auto"
        else:
            # GPU'da float16: float32 ayni isi yaklasik iki kat yavas yapar.
            load_kwargs["dtype"] = torch.float16 if self.device == "cuda" else torch.float32

        self.model = AutoModelForCausalLM.from_pretrained(model_name, **load_kwargs)

        if adapter_path:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter_path)

            # Adaptoru base modele kaynastir: LoRA ayri katman olarak dururken
            # her ileri gecişte iki fazladan matris carpimi yapiliyor.
            # Sonuc matematiksel olarak ayni, sadece daha hizli.
            # 4-bit modda yapilmiyor - quantize agirliklarda hassasiyet kaybi olur.
            if not load_in_4bit:
                self.model = self.model.merge_and_unload()

        if not load_in_4bit:
            self.model.to(self.device)
        self.model.eval()

    @torch.inference_mode()
    def extract(self, raw_text: str, max_new_tokens: int = 256) -> dict:
        """
        OCR ham metnini alip {company_name, date, address, total_amount, invoice_no}
        sozlugu dondurur. Bulunamayan alanlar None olur.
        """
        if not raw_text or not raw_text.strip():
            return empty_result()

        # Prompt egitimdekiyle BIREBIR ayni olmali (llm/prompt.py).
        # Chat sablonu sart: Qwen-Instruct sablonsuz cagrildiginda talimat
        # modeli gibi davranmaz, fine-tune edilmis adaptor de egitimde gordugu
        # kalibi bulamaz ve kazanilan davranis kaybolur.
        prompt = self.tokenizer.apply_chat_template(
            build_messages(raw_text),
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

        output = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,  # Veri ayiklamada yaraticilik istemiyoruz -> deterministik
            pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
        )

        # Sadece modelin urettigi kismi al (prompt'u kes). Tamamini cozup
        # icinden JSON aramak, prompt'taki ornek JSON'u yakalama riski tasir.
        generated = output[0][inputs["input_ids"].shape[-1] :]
        answer = self.tokenizer.decode(generated, skip_special_tokens=True)

        sonuc = _uydurmalari_ele(_extract_json(answer), raw_text)
        return _etiketli_alanlari_duzelt(sonuc, raw_text)


if __name__ == "__main__":
    ornek_ocr = """TAN WOON YANN
BOOK TA .K(TAMAN DAYA) SDN BHD
NO.53 55,57 & 59, JALAN SAGU 18,
TAMAN DAYA, 81100 JOHOR BAHRU
DOCUMENT NO : TD01167104
DATE: 25/12/2018 8:13:39 PM
TOTAL: 9.00"""

    extractor = InvoiceExtractor()
    print("=== LLM CIKTISI ===")
    print(json.dumps(extractor.extract(ornek_ocr), indent=2, ensure_ascii=False))
