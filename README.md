# Fatura & Fiş OCR + Otomatik Veri Ayıklama Servisi

Fatura/fiş görselinden yapılandırılmış JSON üreten iki aşamalı bir servis.

## Problem

Faturalar firma firma farklı düzen, yazı tipi ve yerleşime sahip. "Toplam tutar
şu koordinatta" ya da "şu regex ile yakala" gibi kural tabanlı yaklaşımlar her
yeni fatura formatında kırılıyor. Bu yüzden problem ikiye bölündü:

| Aşama | Görev | Teknoloji |
|---|---|---|
| **Görme** | Görseldeki metni ham metne çevir | PaddleOCR (PP-OCRv4) |
| **Akıl yürütme** | Dağınık ham metni anlamlı JSON'a dönüştür | Qwen2.5-0.5B-Instruct |

OCR nerede ne yazdığını bilir ama ne anlama geldiğini bilmez. LLM ise dağınık
metinden "bu satır firma adı, şu sayı genel toplam" çıkarımını yapar.

## Çıktı formatı

```json
{
  "company_name": "BOOK TA .K(TAMAN DAYA) SDN BHD",
  "date": "25/12/2018",
  "address": "NO.53 55,57 & 59, JALAN SAGU 18, TAMAN DAYA, 81100 JOHOR BAHRU",
  "total_amount": "9.00",
  "invoice_no": "TD01167104"
}
```

Bulunamayan alanlar `null` döner.

## Proje yapısı

```
ocr/ocr_engine.py        PaddleOCR sarmalayıcı  -> görsel'den ham metin
llm/prompt.py            Ortak prompt tanımı    -> train ve inference aynı formatı kullanır
llm/inference/infer.py   InvoiceExtractor       -> ham metin'den JSON
llm/finetune/train.py    QLoRA fine-tune scripti
api/main.py              FastAPI servisi        -> POST /analyze-invoice
```

### `llm/prompt.py` neden ayrı bir dosya?

Fine-tune sırasında modele gösterilen prompt formatı ile çalışma anındaki
format **birebir aynı** olmak zorunda. Aksi halde model eğitildiği kalıbı
göremez ve beklenen çıktıyı üretmez. İki yerde ayrı ayrı yazılırsa er geç
ayrışırlar, o yüzden tek kaynakta tutuluyor.

## Model ve fine-tuning

Base model `Qwen2.5-0.5B-Instruct` prompt ile de iş görür, ama etrafına
"Sure! Here is the JSON..." gibi laf ekler ve alan adlarını tutturamaz.
Bunu düzeltmek için **QLoRA** ile fatura-özel hale getiriliyor:

- **4-bit NF4 quantization** — model ağırlıkları 4 bit'e sıkıştırılır, T4'ün
  16 GB belleğine rahat sığar
- **LoRA adaptörleri** — 0.5B parametrenin tamamı değil, sadece küçük adaptör
  matrisleri eğitilir. Sonuç birkaç MB'lık bir adaptör dosyası
- **Veri seti:** SROIE v2 (626 eğitim + 347 test örneği)

Fine-tune sonrası servise takmak için tek satır değişir:

```python
InvoiceExtractor(adapter_path="models/qwen-invoice-lora")
```

## Kurulum

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Fine-tune için ek paketler (GPU gerekir, yerel makinede kurmayın):

```bash
pip install -r requirements-train.txt
```

## Çalıştırma

```bash
uvicorn api.main:app --reload
```

`http://127.0.0.1:8000/docs` adresinden Swagger arayüzü ile test edilebilir.

Ayarlar için `.env.example` dosyasını `.env` olarak kopyalayın.

### Endpoint

`POST /analyze-invoice` — `multipart/form-data` ile `file` alanında görsel alır.

```json
{
  "filename": "fis.png",
  "data": { "company_name": "...", "date": "...", "address": "...",
            "total_amount": "...", "invoice_no": "..." },
  "raw_text": "OCR'ın okuduğu ham metin",
  "meta": { "llm_used": true, "llm_error": null,
            "ocr_seconds": 6.58, "llm_seconds": 1.2 }
}
```

`raw_text` bilerek cevapta tutuluyor: sonuç yanlış geldiğinde hatanın OCR'da mı
(metni yanlış okudu) yoksa LLM'de mi (metni yanlış anladı) olduğunu ayırt etmenin
tek yolu bu.

`GET /` — sağlık kontrolü. OCR ve LLM'in yüklenip yüklenmediğini, yüklenmediyse
sebebini döner.

### LLM olmadan çalışma

torch kurulu değilse ya da `ENABLE_LLM=0` ise servis **çökmez**: OCR ile çalışmaya
devam eder, `data` alanını boş döndürüp `meta.llm_error` içinde sebebini bildirir.
Böylece LLM bağımlılıkları olmayan bir makinede de OCR katmanı test edilebilir.

### Windows'ta ASCII dışı kullanıcı adı

Kullanıcı adınız `ü`, `ş` gibi karakter içeriyorsa PaddlePaddle model
dosyalarını açamaz ve yanıltıcı bir `Cannot open file ... inference.json`
hatası verir (dosya aslında yerindedir, sorun yolun okunamamasıdır).
`ocr/ocr_engine.py` bunu otomatik algılayıp model cache'ini `C:\paddlex_cache`
dizinine alır; ek bir şey yapmanız gerekmez.

## Çalışma ortamı

Model inference ve fine-tuning **Kaggle Notebook (Tesla T4 GPU)** üzerinde
çalışır. Kod VS Code'da yazılır, GitHub'a push edilir, Kaggle notebook'u
repo'yu klonlayıp çalıştırır. Servisi dışarıya (Postman / Flutter) açmak için
**ngrok** ile geçici public URL alınır.

## Durum

- [x] OCR katmanı
- [x] FastAPI iskeleti (`/analyze-invoice` ham metin döndürüyor)
- [x] LLM inference katmanı (base model) — ölçüm: [docs/baseline-base-model.md](docs/baseline-base-model.md)
- [x] API'ye LLM entegrasyonu
- [x] ngrok ile servisi dışarıya açma — bkz. [notebooks/KAGGLE.md](notebooks/KAGGLE.md)
- [x] SROIE v2 veri hazırlama (`llm/finetune/prepare_sroie.py`) — 626 + 347 örnek
- [x] QLoRA fine-tune scripti (`llm/finetune/train.py`)
- [x] Değerlendirme scripti (`scripts/evaluate.py`)
- [ ] Eğitimi çalıştır ve öncesi/sonrası tabloyu al
- [ ] Fine-tuned adaptörü servise takma

> ngrok adımı bilerek fine-tune'dan **önce** yapıldı: gerçek bir fatura
> fotoğrafında OCR çıktısının ne kadar dağınık geldiğini görmeden fine-tune
> verisinin nasıl hazırlanacağına karar vermek doğru olmaz.
