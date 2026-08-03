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
os.environ['GIT_TERMINAL_PROMPT'] = '0'   # şifre sorup kilitlenmesin, hata versin
%cd /kaggle/working
if os.path.exists('/kaggle/working/invoice-ocr-service'):
    shutil.rmtree('/kaggle/working/invoice-ocr-service')  # eski kopyayı temizle
!git clone https://github.com/KULLANICI_ADIN/invoice-ocr-service.git /kaggle/working/invoice-ocr-service
%cd /kaggle/working/invoice-ocr-service
```

`KULLANICI_ADIN` yerine kendi GitHub kullanıcı adını yaz.

> **Baştaki `%cd /kaggle/working` neden var?** Hücrenin sonundaki `%cd` seni
> repo klasörünün içine sokuyor. Hücreyi ikinci kez çalıştırdığında `rmtree`
> tam da içinde durduğun klasörü siler — altındaki zemin çekilir. Klasör
> yeniden oluşsa bile notebook silinmiş dizini "bulunduğum yer" sanmaya devam
> eder ve her komut şu hatayı verir:
>
> ```
> shell-init: error retrieving current directory: getcwd: ...
> python3: can't open file 'scripts/xxx.py': [Errno 2] No such file or directory
> ```
>
> Baştaki `%cd` silinecek klasörün dışına çıkmayı garantiler.
> Bu hatayı yine de alırsan: bir hücrede `%cd /kaggle/working` çalıştır,
> sonra bu hücreyi tekrar çalıştır.

> **`GIT_TERMINAL_PROMPT=0` neden var?** Repo private ya da adres yanlışsa git
> `Username for 'https://github.com':` diye sorar. Notebook hücresine klavyeden
> cevap yazamazsın, hücre sonsuza kadar asılı kalır. Bu satır git'e "soru sorma,
> direkt hata ver" der — böylece saniyeler içinde `Authentication failed` görüp
> sorunu anlarsın.

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

# Servisi dışarıya açma (ngrok)

Buraya kadar olan hücreler LLM'i script olarak deniyordu. Şimdi **gerçek bir
fatura fotoğrafını Postman'den gönderip** uçtan uca sonucu göreceğiz.

## Ön hazırlık — ngrok token'ı (bir kere yapılır)

1. [ngrok.com](https://ngrok.com) → ücretsiz üye ol
2. [Authtoken sayfasından](https://dashboard.ngrok.com/get-started/your-authtoken) token'ı kopyala
3. Kaggle notebook'ta **Add-ons → Secrets → Add a new secret**
   - Label: `NGROK_AUTHTOKEN`
   - Value: kopyaladığın token
4. Secret'ın yanındaki kutuyu işaretleyip notebook'a **attach** et

> Token'ı asla hücreye yazma. Notebook'u paylaşırsan token da gider ve
> o token'la senin ngrok hesabın adına tünel açılabilir.

## Hücre 5 — Servis bağımlılıkları

```python
!pip install -q pyngrok "paddlepaddle==3.1.1" paddleocr
```

Bu kurulum **birkaç dakika sürer** — paddle büyük bir paket. Önceki hücrelerde
gerekmiyordu çünkü sadece LLM'i deniyorduk; şimdi görsel işleyeceğimiz için OCR
katmanı da lazım.

> CPU sürümü kuruyoruz. OCR görsel başına ~5-7 sn sürecek. GPU sürümü
> (`paddlepaddle-gpu`) daha hızlı ama CUDA sürüm uyumu zahmetli ve darboğaz
> zaten OCR değil.

## Hücre 6 — Servisi başlat

```python
!python scripts/serve_kaggle.py
```

Bu hücre **bilerek durmaz** — çalıştığı sürece servis ayakta. Çıktıda şuna benzer
bir kutu göreceksin:

```
==============================================================
  PUBLIC URL : https://xxxx-yy-zz.ngrok-free.app
  Swagger    : https://xxxx-yy-zz.ngrok-free.app/docs
  Endpoint   : POST https://xxxx-yy-zz.ngrok-free.app/analyze-invoice
==============================================================
```

URL göründükten sonra modeller yüklenmeye devam eder. `[OCR] hazir` ve
`[LLM] hazir` satırlarını görmeden istek atma — servis o ana kadar cevap vermez.

Servisi kapatmak için hücreyi durdur (⏹).

## Hücre 7 — Postman'den test

Postman'de yeni bir istek:

| Alan | Değer |
|---|---|
| Method | `POST` |
| URL | `https://xxxx.ngrok-free.app/analyze-invoice` |
| Body | **form-data** |
| Key | `file` — tipini **File** olarak değiştir (Key kutusunun sağındaki açılır menü) |
| Value | Fatura/fiş fotoğrafını seç |

> **Key tipini File yapmayı unutma.** Varsayılan `Text`'tir; öyle bırakırsan
> dosya değil dosya adı gider ve `422 Unprocessable Entity` alırsın.

Tarayıcıdan `/docs` adresine girersen ngrok araya bir uyarı sayfası koyar;
**Visit Site** deyip geçebilirsin. Postman'de bu sorun çıkmaz.

### Cevapta neye bakacaksın

```json
{
  "data":     { "company_name": "...", "total_amount": "..." },
  "raw_text": "OCR'ın okuduğu ham metin",
  "meta":     { "ocr_seconds": 6.5, "llm_seconds": 1.2 }
}
```

`data` yanlışsa **önce `raw_text`'e bak** — sorunun kaynağını ayırt etmenin tek
yolu bu:

- **`raw_text` de bozuksa** → OCR problemi. Fotoğraf eğik, karanlık ya da
  düşük çözünürlüklü olabilir. Fine-tune bunu düzeltmez.
- **`raw_text` doğru ama `data` yanlışsa** → LLM problemi. Fine-tune'un
  çözeceği şey tam olarak bu.

Bu ayrımı yapmadan fine-tune'a geçmek, yanlış sorunu çözmeye çalışmak olur.

---

## Fine-tune sonrası

Adaptörü eğittikten sonra aynı testi adaptörle çalıştır ve farkı karşılaştır:

```python
!python scripts/smoke_test_llm.py --adapter models/qwen-invoice-lora
```

Servisi adaptörle çalıştırmak için `ADAPTER_PATH` ortam değişkenini ver:

```python
import os
os.environ['ADAPTER_PATH'] = 'models/qwen-invoice-lora'
!ADAPTER_PATH=models/qwen-invoice-lora python scripts/serve_kaggle.py
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
