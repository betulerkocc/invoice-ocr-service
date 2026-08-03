"""
OCR Engine - PaddleOCR wrapper
Gorseldeki metni satir satir okur ve ham metin olarak döndürür.
"""

import os

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


class OCREngine:
    def __init__(self, lang: str = "en"):
        """
        PaddleOCR modelini başlatir.
        lang: OCR dili ('en' İngilizce faturalar için, 'tr' Türkçe için gerekirse)
        """
        self.ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang=lang,
        )

    def extract_text(self, image_path: str) -> str:
        """
        Verilen görsel yolundan metni çikarir.
        Dönüş: satir satir birleştirilmiş ham metin (string)
        """
        result = self.ocr.predict(image_path)

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