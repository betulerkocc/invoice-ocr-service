/// Sunucu istemcisi.
///
/// Web arayuzunun kullandigi API'nin aynisina baglaniyor; sunucu tarafinda
/// mobil icin ayri bir uc yok. Bu bilincli: iki istemcinin ayni sozlesmeyi
/// paylasmasi, birinde duzelen bir hatanin otekinde de duzelmesi demek.
library;

import "dart:convert";
import "dart:io";

import "package:http/http.dart" as http;
import "package:shared_preferences/shared_preferences.dart";

import "model.dart";

class ApiHatasi implements Exception {
  final String mesaj;
  ApiHatasi(this.mesaj);
  @override
  String toString() => mesaj;
}

class Api {
  static const _anahtar = "sunucu_adresi";
  static const varsayilanAdres = "http://192.168.1.100:8000";

  String adres;
  Api(this.adres);

  static Future<Api> yukle() async {
    final ayarlar = await SharedPreferences.getInstance();
    return Api(ayarlar.getString(_anahtar) ?? varsayilanAdres);
  }

  Future<void> adresiKaydet(String yeni) async {
    adres = _duzelt(yeni);
    final ayarlar = await SharedPreferences.getInstance();
    await ayarlar.setString(_anahtar, adres);
  }

  /// Kullanicinin yazdigi adresi kullanilabilir hale getirir.
  ///
  /// Elle adres yazdiriyoruz ve insanlar "192.168.1.5:8000" ya da sonunda
  /// egik cizgiyle yaziyor. Bunlari duzeltmek, "baglanamadi" hatasinin
  /// buyuk kismini ortadan kaldiriyor.
  static String _duzelt(String s) {
    var a = s.trim();
    if (a.isEmpty) return varsayilanAdres;
    if (!a.startsWith("http://") && !a.startsWith("https://")) {
      a = "http://$a";
    }
    while (a.endsWith("/")) {
      a = a.substring(0, a.length - 1);
    }
    return a;
  }

  Uri _u(String yol, [Map<String, String>? sorgu]) =>
      Uri.parse("$adres$yol").replace(queryParameters: sorgu);

  Future<Map<String, dynamic>> _json(http.Response c) async {
    if (c.statusCode < 200 || c.statusCode >= 300) {
      String detay = "HTTP ${c.statusCode}";
      try {
        final g = jsonDecode(utf8.decode(c.bodyBytes));
        if (g is Map && g["detail"] != null) detay = g["detail"].toString();
      } catch (_) {}
      throw ApiHatasi(detay);
    }
    return jsonDecode(utf8.decode(c.bodyBytes)) as Map<String, dynamic>;
  }

  // --- durum ---------------------------------------------------------------

  Future<Map<String, dynamic>> saglik() async {
    final c = await http.get(_u("/health")).timeout(const Duration(seconds: 8));
    return _json(c);
  }

  // --- analiz --------------------------------------------------------------

  /// Gorseli sunucuya gonderip ayiklanmis veriyi alir.
  ///
  /// Zaman asimi bilerek uzun: OCR ve LLM arka arkaya calisiyor, telefon
  /// fotografinda ucdan uca 20-30 saniye surebiliyor.
  Future<Fatura> analizEt(File gorsel) async {
    final istek = http.MultipartRequest("POST", _u("/analyze-invoice"))
      ..files.add(await http.MultipartFile.fromPath("file", gorsel.path));

    final akis = await istek.send().timeout(const Duration(minutes: 3));
    final cevap = await http.Response.fromStream(akis);
    return Fatura.analizden(await _json(cevap));
  }

  // --- kayitlar ------------------------------------------------------------

  Future<({int toplam, List<Fatura> kayitlar})> faturalar({
    Donem donem = Donem.tumu,
    int limit = 100,
  }) async {
    final c = await http
        .get(_u("/faturalar", {"limit": "$limit", "donem": donem.deger}))
        .timeout(const Duration(seconds: 15));
    final g = await _json(c);
    return (
      toplam: (g["toplam"] as num?)?.toInt() ?? 0,
      kayitlar: (g["kayitlar"] as List? ?? [])
          .map((e) => Fatura.kayittan(e as Map<String, dynamic>))
          .toList(),
    );
  }

  Future<Fatura> fatura(int id) async {
    final c = await http.get(_u("/faturalar/$id")).timeout(const Duration(seconds: 15));
    return Fatura.kayittan(await _json(c));
  }

  Future<List<KategoriOzeti>> kategoriOzeti({Donem donem = Donem.tumu}) async {
    final c = await http
        .get(_u("/kategoriler", {"donem": donem.deger}))
        .timeout(const Duration(seconds: 15));
    final g = await _json(c);
    return (g["kategoriler"] as List? ?? [])
        .map((e) => KategoriOzeti.json(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<String>> kategoriListesi() async {
    final c = await http.get(_u("/kategori-listesi")).timeout(const Duration(seconds: 8));
    final g = await _json(c);
    return (g["kategoriler"] as List? ?? []).map((e) => e.toString()).toList();
  }

  // --- duzeltme ------------------------------------------------------------

  /// Tek bir alani gunceller. Kullanicinin duzeltmeleri ilerideki egitim icin
  /// etiketli veri olusturuyor, o yuzden her degisiklik aninda kaydediliyor.
  Future<void> alaniGuncelle(int id, String alan, String? deger) async {
    final c = await http.patch(
      _u("/faturalar/$id"),
      headers: const {"Content-Type": "application/json"},
      body: jsonEncode({alan: deger ?? ""}),
    ).timeout(const Duration(seconds: 15));
    await _json(c);
  }

  Future<void> dogrula(int id, bool deger) async {
    final c = await http.post(
      _u("/faturalar/$id/dogrula"),
      headers: const {"Content-Type": "application/json"},
      body: jsonEncode({"dogrulandi": deger}),
    ).timeout(const Duration(seconds: 15));
    await _json(c);
  }

  Future<void> sil(int id) async {
    final c = await http.delete(_u("/faturalar/$id")).timeout(const Duration(seconds: 15));
    await _json(c);
  }

  String gorselAdresi(int id) => "$adres/faturalar/$id/gorsel";
  String disaAktarAdresi(Donem donem) => "$adres/disa-aktar?donem=${donem.deger}";
}
