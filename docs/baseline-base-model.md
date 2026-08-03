# Referans Ölçüm — Fine-tune Öncesi (base model)

Fine-tune'un ne kadar fark yarattığını gösterebilmek için alınan başlangıç
ölçümü. Aynı testi adaptörle tekrar çalıştırıp bu tabloyla karşılaştıracağız.

- **Model:** `Qwen2.5-0.5B-Instruct` (adaptörsüz, düz base)
- **Ortam:** Kaggle Notebook, Tesla T4
- **Komut:** `python scripts/smoke_test_llm.py`

## Performans

| Ölçüm | Değer |
|---|---|
| Model yükleme | 10.3 sn |
| Çıkarım (uzun fiş) | 3.6 sn |
| Çıkarım (kısa fiş) | 1.1 sn |
| Cihaz | `cuda:0` |

## Çıktılar

### Örnek 1 — düz fiş (4/5 alan dolu)

```json
{
  "company_name": "",
  "date": "25/12/2018",
  "address": "Jalan Sagu 18, Johor",
  "total_amount": "9.00",
  "invoice_no": "TD01167104"
}
```

Beklenen `company_name`: `BOOK TA .K(TAMAN DAYA) SDN BHD`
Beklenen `address`: `NO.53 55,57 & 59, JALAN SAGU 18, TAMAN DAYA, 81100 JOHOR BAHRU, JOHOR.`

### Örnek 2 — alanları eksik fiş (1/5 alan dolu)

```json
{
  "company_name": "",
  "date": "",
  "address": "",
  "total_amount": "60.30",
  "invoice_no": ""
}
```

Beklenen `company_name`: `SYARIKAT PERNIAGAAN GIN KEE`
Beklenen `address`: `NO 290, JALAN AIR PANAS, SETAPAK, 53200, KUALA LUMPUR.`

### Örnek 3 — boş metin (savunma testi)

```json
{
  "company_name": null, "date": null, "address": null,
  "total_amount": null, "invoice_no": null
}
```

Doğru davranış: hata fırlatmadan boş sonuç döndü.

## Değerlendirme

**Çalışan:** Boru hattı uçtan uca akıyor. Her üç durumda da parse edilebilir
JSON üretildi, çökme yok. `total_amount` iki örnekte de doğru — kasaya verilen
para (`CASH: 10.00`) ile genel toplamı (`TOTAL: 9.00`) karıştırmamış.

**Bozuk — fine-tune'un hedefi:**

1. **`company_name` hiç bulunamıyor.** İki örnekte de boş. En belirgin eksik.
2. **`null` yerine `""` dönüyor.** Prompt açıkça "yoksa null kullan" diyor ama
   base model talimatı takip etmiyor.
3. **Adres özetleniyor.** Metinde tam adres varken model kısaltıp yeniden
   yazıyor. Kopyalaması gerekirken üretiyor.

Bu üç davranış 0.5B'lik bir base model için beklenen. Sorun prompt'ta değil,
modelin talimat takip kapasitesinde — QLoRA fine-tune'un çözmesi gereken tam
olarak bunlar.
