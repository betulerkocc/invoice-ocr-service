# Kaggle Notebook Kullanımı

Kod VS Code'da yazılır → GitHub'a push edilir → Kaggle notebook repo'yu klonlayıp
çalıştırır. Kaggle'da kod **yazılmaz**, sadece çalıştırılır. Böylece tek bir
doğru kod kopyası olur.

## Notebook ayarları

Notebook açtıktan sonra sağ paneldeki **Settings** bölümünden:

| Ayar | Değer |
|---|---|
| Accelerator | **GPU T4 x2** (ya da P100) |
| Internet | **On** (model indirmek ve repo klonlamak için şart) |
| Persistence | Variables and Files |

> Internet kapalıysa `git clone` ve HuggingFace model indirme çalışmaz.

---

## Hücre 1 — GPU kontrolü

```python
!nvidia-smi
```

Çıktıda `Tesla T4` ve `15360MiB` civarı bellek görmelisin. Görmüyorsan
Accelerator ayarı GPU'ya geçmemiş demektir.

## Hücre 2 — Repo'yu klonla

```python
import os, shutil
if os.path.exists('/kaggle/working/invoice-ocr-service'):
    shutil.rmtree('/kaggle/working/invoice-ocr-service')  # eski kopyayı temizle
!git clone https://github.com/KULLANICI_ADIN/invoice-ocr-service.git /kaggle/working/invoice-ocr-service
%cd /kaggle/working/invoice-ocr-service
```

`KULLANICI_ADIN` yerine kendi GitHub kullanıcı adını yaz.

> Kodu her değiştirdiğinde: VS Code'da commit + push → bu hücreyi tekrar çalıştır.
> Hücre eski klasörü sildiği için her seferinde temiz kopya gelir.

## Hücre 3 — Bağımlılıklar

```python
!pip install -q -U "transformers>=4.45" "peft>=0.13" "accelerate>=0.34"
```

Kaggle'da `torch` zaten kurulu geliyor, ona dokunmuyoruz — yeniden kurmak
hem uzun sürer hem CUDA sürümünü bozabilir. `paddleocr` da bu testte gerekmiyor,
sadece LLM katmanını deniyoruz.

## Hücre 4 — Duman testi

```python
!python scripts/smoke_test_llm.py
```

Beklenen: model yükleniyor, cihaz `cuda:0` görünüyor, üç örnek için de JSON
basılıyor.

> **Not:** Bu test *fine-tune öncesi* base modelle çalışır. Sonuçların bir kısmı
> yanlış veya eksik çıkacak — normal. Amaç boru hattının uçtan uca aktığını
> görmek, doğruluk ölçmek değil. Doğruluk fine-tune sonrası gelecek.

---

## Fine-tune sonrası

Adaptörü eğittikten sonra aynı testi adaptörle çalıştır ve farkı karşılaştır:

```python
!python scripts/smoke_test_llm.py --adapter models/qwen-invoice-lora
```

## Repo private ise

Kaggle → **Add-ons → Secrets** menüsünden `GITHUB_TOKEN` adında bir secret ekle
(GitHub'da Settings → Developer settings → Personal access tokens → `repo` yetkisi),
sonra klonlama hücresini şöyle değiştir:

```python
from kaggle_secrets import UserSecretsClient
token = UserSecretsClient().get_secret("GITHUB_TOKEN")
!git clone https://{token}@github.com/KULLANICI_ADIN/invoice-ocr-service.git /kaggle/working/invoice-ocr-service
```

Token'ı asla kod içine yazma, sadece Secrets üzerinden oku.
