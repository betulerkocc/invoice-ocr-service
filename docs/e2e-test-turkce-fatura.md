# Uçtan Uca Test — Türkçe e-Fatura (fine-tune öncesi)

İlk gerçek uçtan uca test: görsel → PaddleOCR → Qwen2.5-0.5B (base) → JSON.
Kaggle T4 üzerinde ngrok ile açılan servise Postman'den gönderildi.

- **Girdi:** Türkçe e-Fatura çıktısı (PNG, dijital render — telefon fotoğrafı değil)
- **Model:** `Qwen2.5-0.5B-Instruct`, adaptörsüz
- **Süreler:** OCR 19.01 sn (CPU paddle), LLM 2.99 sn

## Sonuç

| Alan | Model çıktısı | Metinde doğrusu | Durum |
|---|---|---|---|
| `invoice_no` | `OAR2019000000002` | aynı | Doğru |
| `total_amount` | `1,18 TL` | `Ödenecek Tutar: 1,18 TL` | Doğru |
| `date` | `2019-08-09` | `09-08-2019` | Doğru (ISO'ya çevirmiş) |
| `company_name` | `AYDIN ÖZEL` | `AYDIN ÖZEL ENTEGRASYON` | Kesik |
| `address` | `Türkiye Yenimahalle/ ANKARA` | `Odtü teknokent deneme Silikon Blok, Türkiye Yenimahalle/ANKARA` | Eksik |

## Değerlendirme

**OCR katmanı sorunsuz.** Ham metin neredeyse kusursuz okundu. Üç küçük hata
(`DOĞANBEY`→`DOČANBEY`, `Vergi`→`Verqi`, `aydinefatest`→`avdinefatest`)
çıkarılan alanların hiçbirine denk gelmiyor. Görsel ön işlemeye (eğiklik
düzeltme, kontrast) gerek yok.

> Bu test dijital bir e-Fatura çıktısıyla yapıldı. Buruşuk/eğik/karanlık
> telefon fotoğraflarında OCR kalitesi düşecektir; o senaryo henüz test
> edilmedi.

**`total_amount` beklenenden iyi.** Metinde beş tutar adayı vardı
(`1,00 TL` mal hizmet toplamı, `0,18 TL` KDV, `1,18 TL` vergiler dahil,
`1,18 TL` ödenecek, `0,00 TL` iskonto). Base model doğru olanı seçti.

**Kalan iki hata fine-tune'un hedefinde.** Model hem `company_name` hem
`address` alanında metinden kopyalamak yerine kısaltıyor — SROIE ölçümündeki
(bkz. [baseline-base-model.md](baseline-base-model.md)) "adresi özetliyor"
davranışının aynısı. Dil değişse de hata deseni aynı kaldı.

## Açık soru: dil uyumsuzluğu

Fine-tune verisi olarak seçilen **SROIE v2 İngilizce/Malezya fişlerinden
oluşuyor**, oysa hedef belgeler Türkçe e-Faturalar. SROIE eğitimi şunları
öğretir ve bunlar dilden bağımsızdır:

- Sadece JSON üretmek, etrafına açıklama yazmamak
- Alanı bulamayınca `""` değil `null` dönmek
- Metinden **kopyalamak**, yeniden yazmamak

Öğretmedikleri ise Türkçeye özgü: `Ödenecek Tutar`, `Fatura No`, `VKN`,
`Vergiler Dahil Toplam Tutar` gibi etiketlerin ne anlama geldiği. Fine-tune
sonrası bu test tekrarlanıp transferin ne kadar gerçekleştiği ölçülmeli.
