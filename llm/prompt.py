"""
Ortak prompt tanimi.

ONEMLI: Bu dosya hem fine-tune (llm/finetune/train.py) hem de inference
(llm/inference/infer.py) tarafindan kullanilir. Egitimde gorulen format ile
calisma anindaki format birebir ayni olmak zorunda; aksi halde fine-tune
edilmis model beklenen ciktiyi uretmez. Prompt degisecekse ikisi de ayni anda
degisir -> yeniden egitim gerekir.
"""

import json

# Modelin doldurmasi gereken alanlar (JSON anahtar sirasi da buradan gelir)
FIELDS = ["company_name", "date", "address", "total_amount", "invoice_no"]

SYSTEM_PROMPT = (
    "You are an information extraction engine for invoices and receipts. "
    "The user gives you raw OCR text from a scanned invoice. The text is noisy, "
    "unordered and may contain typos.\n"
    "Extract exactly these fields and return ONLY a JSON object, nothing else:\n"
    '{"company_name": ..., "date": ..., "address": ..., "total_amount": ..., "invoice_no": ...}\n'
    "Rules:\n"
    "- Copy values from the text, do not invent anything.\n"
    "- If a field is not present in the text, use null.\n"
    "- total_amount is the grand total (the final amount paid), as a plain number string.\n"
    "- Do not add explanations, markdown or code fences."
)

USER_TEMPLATE = "OCR TEXT:\n{raw_text}"


def build_messages(raw_text: str):
    """OCR ham metninden chat mesaj listesi uretir (inference icin)."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(raw_text=raw_text.strip())},
    ]


def build_training_messages(raw_text: str, target: dict):
    """
    Egitim icin mesaj listesi: build_messages + beklenen assistant cevabi.
    target: {"company_name": ..., "date": ...} seklinde etiketli sozluk.
    """
    answer = {field: target.get(field) for field in FIELDS}
    return build_messages(raw_text) + [
        {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
    ]


def empty_result() -> dict:
    """Tum alanlari null olan bosluk sozlugu (parse basarisiz olursa kullanilir)."""
    return {field: None for field in FIELDS}
