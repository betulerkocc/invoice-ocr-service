"""
LLM inference katmani.

Gorevi: OCR'dan gelen dagitik ham metni alip yapilandirilmis JSON'a cevirmek.
Model: Qwen2.5-0.5B-Instruct (fine-tune oncesi base hali de calisir).

Fine-tune sonrasi tek yapilacak sey: adapter_path parametresine LoRA
adaptorunun klasorunu vermek. Kod degismez.
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

    Model bazen JSON'un onune/arkasina aciklama ya da ```json cite ekleyebilir,
    ozellikle fine-tune oncesi base halde. Bu yuzden ham json.loads yerine
    ilk '{' ile dengeli kapanan '}' arasini tariyoruz.
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
                # Sadece bekledigimiz alanlari, sabit sirayla dondur
                return {field: parsed.get(field) for field in FIELDS}

    return empty_result()


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
            load_kwargs["dtype"] = torch.float16 if self.device == "cuda" else torch.float32

        self.model = AutoModelForCausalLM.from_pretrained(model_name, **load_kwargs)

        if adapter_path:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter_path)

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

        # Sadece modelin urettigi kismi al (prompt'u kes)
        generated = output[0][inputs["input_ids"].shape[-1] :]
        answer = self.tokenizer.decode(generated, skip_special_tokens=True)
        return _extract_json(answer)


if __name__ == "__main__":
    ornek_ocr = """TAN WOON YANN
BOOK TA .K(TAMAN DAYA) SDN BHD
789417-W
NO.53 55,57 & 59, JALAN SAGU 18,
TAMAN DAYA,
81100 JOHOR BAHRU,
JOHOR.
DOCUMENT NO : TD01167104
DATE: 25/12/2018 8:13:39 PM
TOTAL: 9.00"""

    extractor = InvoiceExtractor()
    print("=== LLM CIKTISI ===")
    print(json.dumps(extractor.extract(ornek_ocr), indent=2, ensure_ascii=False))
