/// Sunucudan gelen veri yapilari.
///
/// Alan adlari sunucudaki JSON ile birebir ayni tutuluyor (company_name,
/// total_amount...). Turkcelestirmek okunakli olurdu ama her degisiklikte
/// iki tarafi birden guncellemek gerekirdi; API sozlesmesi tek yerde kalsin.
library;

class Fatura {
  final int? id;
  String? companyName;
  String? date;
  String? address;
  String? totalAmount;
  String? invoiceNo;
  String? kdv;
  String? category;
  bool dogrulandi;

  /// OCR'in okudugu ham metin. Sonuc yanlissa hatanin OCR'da mi LLM'de mi
  /// oldugunu ayirt etmenin tek yolu bu.
  final String? rawText;

  final double? ocrSaniye;
  final double? llmSaniye;
  final String? gorsel;

  Fatura({
    this.id,
    this.companyName,
    this.date,
    this.address,
    this.totalAmount,
    this.invoiceNo,
    this.kdv,
    this.category,
    this.dogrulandi = false,
    this.rawText,
    this.ocrSaniye,
    this.llmSaniye,
    this.gorsel,
  });

  /// /analyze-invoice cevabindan uretir (alanlar `data` icinde gelir).
  factory Fatura.analizden(Map<String, dynamic> j) {
    final d = (j["data"] as Map<String, dynamic>?) ?? const {};
    final meta = (j["meta"] as Map<String, dynamic>?) ?? const {};
    return Fatura(
      id: j["id"] as int?,
      companyName: d["company_name"] as String?,
      date: d["date"] as String?,
      address: d["address"] as String?,
      totalAmount: d["total_amount"] as String?,
      invoiceNo: d["invoice_no"] as String?,
      kdv: d["kdv"] as String?,
      category: j["category"] as String?,
      rawText: j["raw_text"] as String?,
      gorsel: j["gorsel"] as String?,
      ocrSaniye: (meta["ocr_seconds"] as num?)?.toDouble(),
      llmSaniye: (meta["llm_seconds"] as num?)?.toDouble(),
    );
  }

  /// /faturalar ve /faturalar/{id} cevaplarindan uretir (alanlar duz gelir).
  factory Fatura.kayittan(Map<String, dynamic> j) => Fatura(
        id: j["id"] as int?,
        companyName: j["company_name"] as String?,
        date: j["date"] as String?,
        address: j["address"] as String?,
        totalAmount: j["total_amount"] as String?,
        invoiceNo: j["invoice_no"] as String?,
        kdv: j["kdv"] as String?,
        category: j["category"] as String?,
        dogrulandi: (j["dogrulandi"] as int? ?? 0) == 1,
        rawText: j["raw_text"] as String?,
        gorsel: j["gorsel"] as String?,
        ocrSaniye: (j["ocr_saniye"] as num?)?.toDouble(),
        llmSaniye: (j["llm_saniye"] as num?)?.toDouble(),
      );
}

class KategoriOzeti {
  final String kategori;
  final int adet;
  final double toplam;

  KategoriOzeti({
    required this.kategori,
    required this.adet,
    required this.toplam,
  });

  factory KategoriOzeti.json(Map<String, dynamic> j) => KategoriOzeti(
        kategori: j["kategori"] as String? ?? "Bilinmiyor",
        adet: (j["adet"] as num?)?.toInt() ?? 0,
        toplam: (j["toplam"] as num?)?.toDouble() ?? 0,
      );
}

/// Donem filtresi. Sunucudaki adlarla ayni olmali.
enum Donem {
  tumu("tumu", "Tümü"),
  buAy("bu_ay", "Bu ay"),
  gecenAy("gecen_ay", "Geçen ay"),
  son30Gun("son_30_gun", "Son 30 gün"),
  buYil("bu_yil", "Bu yıl");

  final String deger;
  final String etiket;
  const Donem(this.deger, this.etiket);
}
