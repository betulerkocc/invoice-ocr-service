"""
OCR Engine - PaddleOCR wrapper
Gorseldeki metni satir satir okur ve ham metin olarak döndürür.
"""

import os
import tempfile

_ASCII_OLMAYAN_YEDEK_CACHE = r"C:\paddlex_cache"


def _ascii_cache_dizini_ayarla():
    """
    Windows'ta kullanici adi ASCII disi karakter iceriyorsa (ornek: 'Betül'),
    PaddlePaddle'in C++ katmani model dosyalarini acamaz ve su hatayi verir:

        RuntimeError: (NotFound) Cannot open file ...\\inference.json

    Hata "dosya yok" der ama dosya yerindedir; sorun yolun okunamamasidir.
    Cozum: model cache'ini ASCII bir dizine tasimak.

    Bu fonksiyon paddleocr import edilmeden ONCE calismak zorunda - paddlex
    cache yolunu import aninda bir kere okuyup sabitliyor.
    """
    if os.name != "nt" or "PADDLE_PDX_CACHE_HOME" in os.environ:
        return  # Windows degil ya da kullanici zaten kendi yolunu vermis

    varsayilan = os.path.join(os.path.expanduser("~"), ".paddlex")
    try:
        varsayilan.encode("ascii")
    except UnicodeEncodeError:
        os.environ["PADDLE_PDX_CACHE_HOME"] = _ASCII_OLMAYAN_YEDEK_CACHE
        print(
            f"[OCR] Ev dizini ASCII disi karakter iceriyor. "
            f"Model cache'i {_ASCII_OLMAYAN_YEDEK_CACHE} dizinine alindi."
        )


_ascii_cache_dizini_ayarla()

from paddleocr import PaddleOCR  # noqa: E402


# PaddleOCR varsayilan olarak "medium" modelleri indiriyor; bunlar sunucu
# GPU'lari icin tasarlanmis. CPU'da gercek bir market fisi 40 saniye suruyor.
# "mobile" modeller telefon/CPU icin tasarlanmis ve ayni fisi 2-3 saniyede
# okuyor - olculen fark 12-18 kat.
#
# Dogruluktan feragat etmiyoruz: karsilastirma testinde firma adi, toplam
# tutar, tarih, fis no ve VKN'nin hepsi iki modelde de dogru okundu.
VARSAYILAN_DET_MODEL = "PP-OCRv5_mobile_det"
VARSAYILAN_REC_MODEL = "PP-OCRv5_mobile_rec"


class OCREngine:
    def __init__(
        self,
        lang: str = "en",
        max_side: int = 1600,
        det_model: str | None = VARSAYILAN_DET_MODEL,
        rec_model: str | None = VARSAYILAN_REC_MODEL,
    ):
        """
        PaddleOCR modelini başlatir.

        lang     : OCR dili. YALNIZCA model adlari verilmediginde etkili
        max_side : görselin uzun kenari bu degeri asarsa kucultulur (0 = kapali)
        det/rec  : metin tespiti ve tanima modelleri. None verilirse PaddleOCR
                   kendi varsayilanini (medium) secer - yavas ama referans
        """
        self.max_side = max_side

        ayarlar = dict(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        if det_model and rec_model:
            # Model adi verildiginde PaddleOCR lang'i yok sayiyor; birlikte
            # gondermek yaniltici bir uyari uretiyor, o yuzden ayirdik.
            ayarlar["text_detection_model_name"] = det_model
            ayarlar["text_recognition_model_name"] = rec_model
        else:
            ayarlar["lang"] = lang

        self.ocr = PaddleOCR(**ayarlar)

    def _kucult(self, image_path: str):
        """
        Buyuk gorselleri OCR oncesi kucultur, gerekmiyorsa yolu aynen dondurur.

        OCR suresi piksel sayisiyla dogru orantili buyuyor: 3200 pikselde
        ~41 sn, 1600 pikselde ~14 sn. Telefon fotograflari 3000-4000 piksel
        geliyor ama fis metnini okumak icin bu cozunurluk gerekmiyor - fazlasi
        sadece zaman harciyor. Uzun kenari max_side'a indirmek sureyi birkac
        kat kisaltiyor, okunabilirligi ise pratikte etkilemiyor.
        """
        if not self.max_side:
            return image_path, None

        from PIL import Image

        with Image.open(image_path) as img:
            uzun = max(img.size)
            if uzun <= self.max_side:
                return image_path, None

            oran = self.max_side / uzun
            yeni = (max(1, int(img.width * oran)), max(1, int(img.height * oran)))
            kucuk = img.convert("RGB").resize(yeni, Image.LANCZOS)

        gecici = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        gecici.close()
        kucuk.save(gecici.name)
        return gecici.name, gecici.name  # (kullanilacak yol, silinecek gecici dosya)

    def extract_text(self, image_path: str) -> str:
        """
        Verilen görsel yolundan metni çikarir.
        Dönüş: satir satir birleştirilmiş ham metin (string)
        """
        yol, gecici = self._kucult(image_path)
        try:
            result = self.ocr.predict(yol)
        finally:
            if gecici:
                os.remove(gecici)

        lines = []
        for res in result:
            texts = res.get("rec_texts", [])
            lines.extend(texts)

        return "\n".join(lines)

    def extract_raw_result(self, image_path: str):
        """
        Ham PaddleOCR ciktisini döndürür (debug/inceleme için).
        """
        return self.ocr.predict(image_path)


if __name__ == "__main__":
    engine = OCREngine(lang="en")
    text = engine.extract_text("../data/raw/sample_invoice.jpg")
    print("=== OCR ÇIKTISI ===")
    print(text)