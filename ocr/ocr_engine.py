"""
OCR Engine - PaddleOCR wrapper
Gorseldeki metni satir satir okur ve ham metin olarak döndürür.
"""

from paddleocr import PaddleOCR


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