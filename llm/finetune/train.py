"""
QLoRA fine-tune: Qwen2.5-0.5B-Instruct -> fatura ayiklama modeli.

QLoRA = 4-bit NF4 quantization (bitsandbytes) + LoRA adaptorleri (peft).
Base modelin agirliklari donmus ve 4-bit sikistirilmis halde durur; sadece
araya eklenen kucuk LoRA matrisleri egitilir. Bu sayede 0.5B'lik model T4'un
15 GB belleginde rahatca egitilir ve ciktida 1 GB'lik model degil, birkac MB'lik
adaptor dosyasi olusur.

trl/SFTTrainer yerine transformers.Trainer + elle maskeleme kullaniyoruz:
trl'in API'si surumler arasi cok degisti ve Kaggle her calistirmada guncel
surumu kuruyor. Burada ne oldugu acikca gorunuyor ve surum riski yok.

Kullanim:
    # once veri hazirlanmali:
    python llm/finetune/prepare_sroie.py

    # hizli duman testi (2-3 dakika) - once bunu calistir:
    python llm/finetune/train.py --limit 20 --epochs 1

    # gercek egitim:
    python llm/finetune/train.py
"""

import argparse
import json
import os
import sys

# --- torch import edilmeden ONCE calismali ---
#
# bitsandbytes'in 4-bit katmanlari torch'un DataParallel'i ile calismiyor.
# Kaggle'da "GPU T4 x2" secilirse Trainer modeli iki karta kopyalar; 4-bit
# agirliklari acmak icin gereken quantization durumu ikinci karta dogru
# tasinmadigi icin egitim su hatayla cokuyor:
#
#     CUDA error: an illegal memory access was encountered
#
# 0.5B'lik model tek T4'e rahatca sigdigi icin tek karta sabitliyoruz.
# Ikinci kart zaten hiz kazandirmazdi: DataParallel her adimda modeli
# kopyalayip gradyanlari toplar, bu boyutta faydadan cok yuk getirir.
# Gerekirse disaridan CUDA_VISIBLE_DEVICES verilerek degistirilebilir.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import torch  # noqa: E402
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, ".."))

from prompt import FIELDS, build_messages  # noqa: E402

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


class FaturaVeriSeti(Dataset):
    """
    JSONL dosyasini egitilebilir token dizilerine cevirir.

    Kritik nokta - MASKELEME: her ornek "prompt + cevap" olarak tokenlanir ama
    kayip (loss) sadece CEVAP tokenlari uzerinden hesaplanir. Prompt tokenlarinin
    etiketi -100 yapilir; PyTorch bu degeri kayip hesabinda yok sayar.

    Maskelemeseydik model sistem prompt'unu ve OCR metnini de "uretmeyi"
    ogrenirdi - oysa bunlar zaten girdi olarak veriliyor. Ogrenmesini
    istedigimiz tek sey: bu girdiye karsilik hangi JSON'un uretilecegi.
    """

    def __init__(self, jsonl_yolu: str, tokenizer, max_length: int = 1024, limit=None):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.ornekler = []

        with open(jsonl_yolu, encoding="utf-8") as f:
            for satir in f:
                satir = satir.strip()
                if not satir:
                    continue
                self.ornekler.append(json.loads(satir))
                if limit and len(self.ornekler) >= limit:
                    break

        if not self.ornekler:
            sys.exit(f"HATA: {jsonl_yolu} bos. Once prepare_sroie.py calistirin.")

        # Bos metinle sablonun kendi maliyeti (sistem prompt'u + chat isaretleri).
        # Ham metne ne kadar yer kaldigini buradan hesapliyoruz.
        self._sablon_maliyeti = len(self._prompt_tokenlari(""))
        self.kirpilan = 0  # kac ornekte ham metin kisaltildi

    def __len__(self):
        return len(self.ornekler)

    def _prompt_tokenlari(self, raw_text: str) -> list:
        """
        Chat sablonunu uygulayip DUZ token listesi dondurur.

        apply_chat_template surume gore farkli sey donduruyor: kimi surumde
        dogrudan [int, ...], kimi surumde BatchEncoding, kimi surumde de
        batch boyutuyla [[int, ...]]. Hepsini burada tek bicime indiriyoruz.

        Onemli: BatchEncoding uzerinde len() token sayisini degil ANAHTAR
        sayisini verir. Duzeltmeden birakilirsa kirpma hesabi sessizce
        yanlis calisir - hata vermez, sadece yanlis egitir.
        """
        cikti = self.tokenizer.apply_chat_template(
            build_messages(raw_text), tokenize=True, add_generation_prompt=True
        )
        if not isinstance(cikti, list):     # BatchEncoding / dict benzeri
            cikti = cikti["input_ids"]
        if cikti and isinstance(cikti[0], list):  # [[...]] -> [...]
            cikti = cikti[0]
        return list(cikti)

    def __getitem__(self, i):
        ornek = self.ornekler[i]
        hedef = {alan: ornek["target"].get(alan) for alan in FIELDS}

        # Cevabi ONCE hazirliyoruz: uzunlugu bilinsin ki ham metni ona gore
        # kirpalim. Tersini yapip sonda toptan kirpsaydik cevabin kuyrugu
        # kesilebilir ve model kapanis parantezi olmayan bozuk JSON ogrenirdi.
        cevap = json.dumps(hedef, ensure_ascii=False)
        cevap_ids = self.tokenizer(cevap, add_special_tokens=False)["input_ids"]
        cevap_ids += [self.tokenizer.eos_token_id]  # Qwen'de <|im_end|>

        # Ham metne kalan yer (8 token pay: tokenlestirme sinirlarindaki sapma icin)
        izin = self.max_length - len(cevap_ids) - self._sablon_maliyeti - 8
        raw_text = self._kirp(ornek["raw_text"], max(izin, 0))

        # Prompt: inference'taki ile BIREBIR ayni olmali (llm/prompt.py)
        prompt_ids = self._prompt_tokenlari(raw_text)

        # Son emniyet kemeri: yukaridaki hesap tutmadiysa bile cevap hep tam kalir
        azami_prompt = self.max_length - len(cevap_ids)
        if len(prompt_ids) > azami_prompt:
            prompt_ids = prompt_ids[:azami_prompt]

        return {
            "input_ids": prompt_ids + cevap_ids,
            # Prompt kismi -100 -> kayip hesabina girmez
            "labels": [-100] * len(prompt_ids) + cevap_ids,
        }

    def _kirp(self, raw_text: str, azami_token: int) -> str:
        """
        Ham OCR metnini token bazinda kisaltir. Kirpma metnin SONUNDAN olur:
        fislerde firma adi ve adres bastadir, en fazla kalem listesinin
        kuyrugu kaybolur.
        """
        ids = self.tokenizer(raw_text, add_special_tokens=False)["input_ids"]
        if len(ids) <= azami_token:
            return raw_text
        self.kirpilan += 1
        return self.tokenizer.decode(ids[:azami_token])


def harmanla(batch, pad_id: int):
    """Batch icindeki ornekleri en uzuna gore sagdan doldurur."""
    en_uzun = max(len(o["input_ids"]) for o in batch)
    input_ids, labels, attention_mask = [], [], []

    for o in batch:
        dolgu = en_uzun - len(o["input_ids"])
        input_ids.append(o["input_ids"] + [pad_id] * dolgu)
        labels.append(o["labels"] + [-100] * dolgu)  # dolgu da kayba girmez
        attention_mask.append([1] * len(o["input_ids"]) + [0] * dolgu)

    return {
        "input_ids": torch.tensor(input_ids),
        "labels": torch.tensor(labels),
        "attention_mask": torch.tensor(attention_mask),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--train-file", default="data/sroie_train.jsonl")
    p.add_argument("--out-dir", default="models/qwen-invoice-lora")
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--max-length", type=int, default=1024)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--limit", type=int, default=None, help="Duman testi icin ornek siniri")
    p.add_argument("--no-4bit", action="store_true", help="Quantization'i kapat")
    args = p.parse_args()

    if not os.path.exists(args.train_file):
        sys.exit(
            f"HATA: {args.train_file} yok.\n"
            "  Once veriyi hazirlayin:  python llm/finetune/prepare_sroie.py"
        )
    if not torch.cuda.is_available():
        sys.exit("HATA: GPU bulunamadi. Bu script Kaggle T4 (ya da baska CUDA GPU) ister.")

    # Gorunur kart sayisi 1 olmali; 2 ise DataParallel devreye girer ve
    # 4-bit egitim cokerdi (yukaridaki CUDA_VISIBLE_DEVICES notuna bakin).
    print(f"GPU: {torch.cuda.get_device_name(0)} | gorunur kart: {torch.cuda.device_count()}")

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    print(f"Model yukleniyor: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    yukleme = {"device_map": {"": 0}}
    if args.no_4bit:
        yukleme["dtype"] = torch.float16
    else:
        yukleme["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",          # normal-float 4: agirlik dagilimina uygun
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,     # quantization sabitlerini de sikistirir
        )

    model = AutoModelForCausalLM.from_pretrained(args.model, **yukleme)
    model.config.use_cache = False  # gradient checkpointing ile birlikte kullanilamaz

    if args.no_4bit:
        # gradient checkpointing, girdi gomulerinin gradyan tasimasini ister.
        # 4-bit yolda bunu prepare_model_for_kbit_training kendisi yapiyor.
        model.enable_input_require_grads()
    else:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_r * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        # Hem dikkat hem MLP katmanlari: sadece dikkate uygulamak kucuk
        # modellerde yetersiz kaliyor.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    veri = FaturaVeriSeti(args.train_file, tokenizer, args.max_length, args.limit)
    print(f"Egitim ornegi: {len(veri)}")

    egitim_ayarlari = TrainingArguments(
        output_dir=os.path.join(args.out_dir, "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        save_strategy="no",          # adaptoru sonda elle kaydediyoruz
        fp16=True,
        optim="paged_adamw_8bit" if not args.no_4bit else "adamw_torch",
        gradient_checkpointing=True,
        report_to="none",            # wandb vs. baglanmaya calismasin
    )

    trainer = Trainer(
        model=model,
        args=egitim_ayarlari,
        train_dataset=veri,
        data_collator=lambda b: harmanla(b, tokenizer.pad_token_id),
    )

    print("\nEgitim basliyor...\n")
    trainer.train()

    if veri.kirpilan:
        print(f"\nNot: {veri.kirpilan} ornekte ham metin {args.max_length} token"
              f" sinirina sigmadigi icin sonundan kisaltildi.")

    os.makedirs(args.out_dir, exist_ok=True)
    model.save_pretrained(args.out_dir)      # sadece LoRA adaptoru (birkac MB)
    tokenizer.save_pretrained(args.out_dir)
    print(f"\nAdaptor kaydedildi: {args.out_dir}")
    print("Test etmek icin:")
    print(f"  python scripts/smoke_test_llm.py --adapter {args.out_dir}")


if __name__ == "__main__":
    main()
