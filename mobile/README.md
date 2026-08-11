# Mobil uygulama (Flutter)

Web arayüzüyle **aynı API'ye** bağlanan Android/iOS istemcisi. Sunucu tarafında
mobil için ayrı bir uç yok — iki istemcinin aynı sözleşmeyi paylaşması,
birinde düzelen hatanın ötekinde de düzelmesi demek.

## Ekranlar

| Ekran | İş |
|---|---|
| **Analiz** | Fotoğraf çek / galeriden seç (çoklu), analiz et, sonucu düzenle |
| **Kayıtlar** | Dönem filtresi, kategori dökümü, kayıt açma/düzeltme/silme |
| **Ayarlar** | Sunucu adresi, bağlantı testi |

## Durum

Kod `flutter analyze` denetiminden temiz geçiyor (`No issues found!`).
Paketler kurulu. Android SDK olmadığı için **APK henüz üretilmedi** — o adım
Android Studio gerektiriyor.

## Kurulum

Flutter SDK ve Android toolchain gerekiyor. **İndirme boyutu 6-10 GB** —
mobil veri üzerinden yapmayın.

> **Ağ engelleri.** Bazı kurumsal ağlar paket depolarını engelliyor.
> Bu projede ölçülen: `storage.googleapis.com` (Flutter SDK) izinli,
> ama `pub.dev`, `pypi.org` ve `github.com` engelli. SDK'yı kurumsal ağdan
> indirip paketleri (birkaç MB) başka bir bağlantıdan çekmek işe yarıyor.

1. [Flutter SDK](https://docs.flutter.dev/get-started/install/windows) kurun
2. [Android Studio](https://developer.android.com/studio) kurun (Android SDK
   ve platform araçları onunla geliyor)
3. Kurulumu doğrulayın:

```bash
flutter doctor
```

Çıktıda `Flutter` ve `Android toolchain` satırlarının yanında ✓ olmalı.

## Çalıştırma

```bash
cd mobile
flutter pub get
flutter run
```

Telefonu USB ile bağlayıp **geliştirici seçenekleri → USB hata ayıklama**
açık olmalı. `flutter devices` ile cihazın göründüğünü doğrulayın.

## APK üretme

```bash
flutter build apk --release
```

Çıktı: `build/app/outputs/flutter-apk/app-release.apk`. Bu dosyayı telefona
kopyalayıp kurabilirsiniz.

## İlk açılışta

Uygulama **Ayarlar** sekmesinden sunucu adresini ister. Servisi çalıştırdığınızda
terminalde yazan adresi girin:

```
[AG] telefondan    : http://172.20.10.10:8000
```

Adres cihazda saklanıyor, her açılışta yeniden girmek gerekmiyor.

## Ağ izinleri

Android 9 ve üstü şifresiz HTTP trafiğini varsayılan olarak engelliyor.
Yerel ağdaki servise `http://` ile bağlandığımız için
`android/app/src/main/AndroidManifest.xml` içinde `<application>` etiketine
şu nitelik eklenmeli:

```xml
android:usesCleartextTraffic="true"
```

> Bu yalnızca geliştirme/yerel ağ içindir. Servis internete açılacaksa
> `https` kullanılmalı (ngrok zaten https veriyor) ve bu nitelik
> kaldırılmalıdır.

## Neden Flutter

Tek kod tabanından hem Android hem iOS çıkıyor. Projenin mobil tarafı zaten
ince bir istemci — ağır iş (OCR, LLM) sunucuda; burada yapılan şey görsel
göndermek ve dönen veriyi düzenletmek.
