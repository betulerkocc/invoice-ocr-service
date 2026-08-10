# Ölçüm Sonuçları

Üç aşamalı gelişim: base model → SROIE fine-tune → Türkçe ek eğitim.

Bütün ölçümler modelin **hiç görmediği** verilerle yapıldı. Test setleri
eğitimden önce ayrıldı; aynı örnekleri hem eğitip hem ölçmek modelin
ezberlediğini geri söylemesi olurdu.

## 1. SROIE fine-tune'un getirdiği (347 test örneği)

| Alan | Base model | Fine-tune | Fark |
|---|---|---|---|
| Firma adı | 30.0% | **90.5%** | +60.5 |
| Tarih | 49.0% | **96.8%** | +47.8 |
| Adres | 4.6% | **72.3%** | +67.7 |
| Toplam tutar | 70.0% | **94.2%** | +24.2 |
| Fatura no | 41.5% | **91.6%** | +50.1 |
| **Ortalama** | **39.0%** | **89.1%** | **+50.1** |
| **Tam eşleşme** | **0.3%** | **60.2%** | **+59.9** |
| `""` yerine `null` hatası | 171 alan | **0** | — |

**Tam eşleşme** en anlamlı sayı: beş alanın beşi birden doğru demek, yani fiş
hiç elle düzeltme gerektirmeden çıktı. Base modelde 347 fişte 1 tane, fine-tune
sonrası 209 tane.

## 2. Türkçe ek eğitimin getirdiği

Eğitim verisi: 39 doğrulanmış gerçek Türkçe fiş (×4 çoğullanmış) + 250 sentetik
Türkçe + 626 SROIE = 992 örnek. Türkçe payı %37.

### Türkçe test seti (10 gerçek fiş, eğitimde hiç görülmedi)

| Alan | SROIE modeli | + Türkçe | Fark |
|---|---|---|---|
| Adres | 10.0% | **50.0%** | **+40.0** |
| Firma adı | 30.0% | **50.0%** | **+20.0** |
| Tarih | 60.0% | **70.0%** | +10.0 |
| Toplam tutar | 80.0% | 80.0% | — |
| Fatura no | 90.0% | 90.0% | — |
| **Ortalama** | **54.0%** | **68.0%** | **+14.0** |

Toplam tutar ve fatura no değişmedi çünkü onları zaten etiket tabanlı kural
katmanı buluyor; modele bağımlı değiller.

### SROIE (150 test örneği) — İngilizce yeteneği korundu mu

| Alan | SROIE modeli | + Türkçe | Fark |
|---|---|---|---|
| Firma adı | 86.7% | **92.7%** | +6.0 |
| Fatura no | 94.7% | **97.3%** | +2.6 |
| Toplam tutar | 93.3% | **96.0%** | +2.7 |
| Tarih | 94.7% | 94.0% | −0.7 |
| Adres | 68.0% | 67.3% | −0.7 |
| **Ortalama** | **87.5%** | **89.5%** | **+2.0** |
| **Tam eşleşme** | **52.0%** | **57.3%** | **+5.3** |

Alan uyarlamasında bir dili kazanırken ötekini kaybetmek olağandır. Burada
ikisi de kazandı: SROIE karışımda tutuldu ve sentetik veri "etiketli alanı
bul, birebir kopyala" disiplinini genel olarak pekiştirdi.

## 3. Eğitim ayrıntıları

| | SROIE fine-tune | Türkçe ek eğitim |
|---|---|---|
| Örnek | 626 | 992 |
| Epoch | 3 | 3 |
| Donanım | Tesla T4 (Kaggle) | RTX 4060 (yerel) |
| Süre | 11 dk 24 sn | 17 dk 23 sn |
| Kayıp | 0.126 → 0.013 | 0.082 → 0.010 |

Ortak: Qwen2.5-0.5B-Instruct, LoRA r=16 / alpha=32, 7 hedef katman
(dikkat + MLP), eğitilen parametre 8.798.208 (%1.75).

## 4. Hız

| | Başlangıç | Şimdi |
|---|---|---|
| OCR | 386 sn | 3-11 sn |
| LLM | 60 sn | 2.4-3.9 sn |

OCR'da medium → mobile model geçişi ve görsel küçültme; LLM'de float16 ve
LoRA adaptörünün base modele kaynaştırılması.

## 5. Ölçüm yöntemi

Alan alan tam eşleşme. Karşılaştırmada büyük/küçük harf ve fazla boşluk
normalize ediliyor, tutar sayıya indirgeniyor (`9.00` ile `9.0` aynı sayılır).
Aksi halde biçim farkları gerçek hata gibi görünürdü.

`""` ile `null` doğrulukta eşdeğer sayılıyor (ikisi de "değer yok"), ama biçim
farkı ayrıca raporlanıyor — base modelin `""` dönmesi fine-tune'un düzeltmesi
gereken davranışlardan biriydi.

## 6. Bilinen sınırlar

**Türkçe test seti 10 örnek.** Bir fişlik değişim %10 oynatıyor. Yön güvenilir,
kesin değer değil. Daha çok doğrulanmış fiş biriktikçe ölçüm netleşir.

**Eğitim verisinin %38'inde firma adı OCR çıktısında yok.** Fişin üst kısmı
kadraja alınmadığı için OCR o satırları hiç okumamış. Bu alanlar eğitim
hedefinde `null` yapıldı (modele "girdide olmayanı uydur" öğretmemek için) ama
o örnekler firma/adres öğretme fırsatını kaybetti. En etkili sonraki iyileştirme
kod değil, çekim alışkanlığı.

**Sentetik veri gerçeğin yerini tutmuyor.** Buruşuk termal kâğıt, silik baskı,
sıra dışı düzenler taklit edilemiyor. Yapısal olanı (etiket sözlüğü, sayı
biçimi, yerleşim) öğretiyor; gerçek dünyanın dağınıklığını öğretmiyor.
