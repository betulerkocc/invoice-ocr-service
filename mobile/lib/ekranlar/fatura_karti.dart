/// Ayiklanan alanlari gosteren ve duzenlettiren kart.
///
/// Hem analiz sonrasinda hem de kayitlar listesinden bir fatura acildiginda
/// ayni kart kullaniliyor: iki yerde ayri duzenleme ekrani tutmak, birinde
/// yapilan iyilestirmenin otekine gecmemesi demek olurdu.
library;

import "package:flutter/material.dart";

import "../api.dart";
import "../model.dart";

class FaturaKarti extends StatefulWidget {
  final Api api;
  final Fatura fatura;
  final List<String> kategoriler;
  final VoidCallback? degisti;

  const FaturaKarti({
    super.key,
    required this.api,
    required this.fatura,
    required this.kategoriler,
    this.degisti,
  });

  @override
  State<FaturaKarti> createState() => _FaturaKartiState();
}

class _FaturaKartiState extends State<FaturaKarti> {
  late final Map<String, TextEditingController> _kutular;
  String? _hata;
  final _kaydedilen = <String>{};

  static const _alanlar = <(String, String)>[
    ("company_name", "Firma"),
    ("date", "Tarih"),
    ("invoice_no", "Belge no"),
    ("total_amount", "Toplam"),
    ("kdv", "KDV"),
    ("address", "Adres"),
  ];

  @override
  void initState() {
    super.initState();
    final f = widget.fatura;
    _kutular = {
      "company_name": TextEditingController(text: f.companyName ?? ""),
      "date": TextEditingController(text: f.date ?? ""),
      "invoice_no": TextEditingController(text: f.invoiceNo ?? ""),
      "total_amount": TextEditingController(text: f.totalAmount ?? ""),
      "kdv": TextEditingController(text: f.kdv ?? ""),
      "address": TextEditingController(text: f.address ?? ""),
    };
  }

  @override
  void dispose() {
    for (final k in _kutular.values) {
      k.dispose();
    }
    super.dispose();
  }

  Future<void> _kaydet(String alan) async {
    final id = widget.fatura.id;
    if (id == null) return;
    try {
      await widget.api.alaniGuncelle(id, alan, _kutular[alan]!.text);
      if (!mounted) return;
      setState(() {
        _hata = null;
        _kaydedilen.add(alan);
      });
      // Onay isareti kalici olmasin: dikkat dagitmadan "kaydedildi" desin.
      Future.delayed(const Duration(milliseconds: 1400), () {
        if (mounted) setState(() => _kaydedilen.remove(alan));
      });
      widget.degisti?.call();
    } catch (e) {
      if (mounted) setState(() => _hata = "Kaydedilemedi: $e");
    }
  }

  Future<void> _kategoriDegistir(String? yeni) async {
    final id = widget.fatura.id;
    if (id == null || yeni == null) return;
    setState(() => widget.fatura.category = yeni);
    try {
      await widget.api.alaniGuncelle(id, "category", yeni);
      widget.degisti?.call();
    } catch (e) {
      if (mounted) setState(() => _hata = "Kategori değiştirilemedi: $e");
    }
  }

  Future<void> _dogrula() async {
    final id = widget.fatura.id;
    if (id == null) return;
    final yeni = !widget.fatura.dogrulandi;
    try {
      await widget.api.dogrula(id, yeni);
      if (!mounted) return;
      setState(() => widget.fatura.dogrulandi = yeni);
      widget.degisti?.call();
    } catch (e) {
      if (mounted) setState(() => _hata = "Doğrulanamadı: $e");
    }
  }

  @override
  Widget build(BuildContext context) {
    final f = widget.fatura;
    final renk = Theme.of(context).colorScheme;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    "AYIKLANAN VERİLER",
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1,
                      color: renk.onSurfaceVariant,
                    ),
                  ),
                ),
                if (widget.kategoriler.isNotEmpty)
                  DropdownButton<String>(
                    value: widget.kategoriler.contains(f.category) ? f.category : null,
                    hint: const Text("Kategori"),
                    underline: const SizedBox.shrink(),
                    isDense: true,
                    items: widget.kategoriler
                        .map((k) => DropdownMenuItem(value: k, child: Text(k)))
                        .toList(),
                    onChanged: _kategoriDegistir,
                  ),
              ],
            ),
            const SizedBox(height: 6),

            for (final (alan, etiket) in _alanlar)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: TextField(
                  controller: _kutular[alan],
                  onSubmitted: (_) => _kaydet(alan),
                  onTapOutside: (_) => _kaydet(alan),
                  maxLines: alan == "address" ? 2 : 1,
                  decoration: InputDecoration(
                    labelText: etiket,
                    isDense: true,
                    border: const OutlineInputBorder(),
                    suffixIcon: _kaydedilen.contains(alan)
                        ? const Icon(Icons.check, size: 18, color: Colors.green)
                        : null,
                  ),
                ),
              ),

            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: FilledButton.tonalIcon(
                onPressed: _dogrula,
                icon: Icon(f.dogrulandi ? Icons.verified : Icons.check_circle_outline),
                label: Text(
                  f.dogrulandi
                      ? "Doğrulandı — eğitim verisine dahil"
                      : "Kontrol ettim, doğrula",
                ),
              ),
            ),

            if (f.ocrSaniye != null || f.llmSaniye != null) ...[
              const SizedBox(height: 8),
              Text(
                [
                  if (f.ocrSaniye != null) "OCR ${f.ocrSaniye!.toStringAsFixed(1)} sn",
                  if (f.llmSaniye != null) "LLM ${f.llmSaniye!.toStringAsFixed(1)} sn",
                  if (f.id != null) "#${f.id}",
                ].join(" · "),
                style: TextStyle(fontSize: 12, color: renk.onSurfaceVariant),
              ),
            ],

            if (f.rawText != null && f.rawText!.isNotEmpty)
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: const Text("OCR ham metni", style: TextStyle(fontSize: 13)),
                  children: [
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: renk.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: SelectableText(
                        f.rawText!,
                        style: const TextStyle(fontFamily: "monospace", fontSize: 11.5),
                      ),
                    ),
                  ],
                ),
              ),

            if (_hata != null) ...[
              const SizedBox(height: 8),
              Text(_hata!, style: TextStyle(color: renk.error, fontSize: 13)),
            ],
          ],
        ),
      ),
    );
  }
}
