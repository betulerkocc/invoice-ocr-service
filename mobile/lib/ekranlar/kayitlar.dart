/// Kayitlar listesi, kategori dokumu ve donem filtresi.
library;

import "package:flutter/material.dart";

import "../api.dart";
import "../model.dart";
import "fatura_karti.dart";

class KayitlarEkrani extends StatefulWidget {
  final Api api;
  const KayitlarEkrani({super.key, required this.api});

  @override
  State<KayitlarEkrani> createState() => KayitlarEkraniState();
}

class KayitlarEkraniState extends State<KayitlarEkrani> {
  Donem _donem = Donem.tumu;
  List<Fatura> _kayitlar = [];
  List<KategoriOzeti> _ozet = [];
  List<String> _kategoriler = [];
  int _toplam = 0;
  bool _yukleniyor = false;
  String? _hata;

  @override
  void initState() {
    super.initState();
    yenile();
  }

  Future<void> yenile() async {
    if (!mounted) return;
    setState(() {
      _yukleniyor = true;
      _hata = null;
    });
    try {
      final sonuc = await widget.api.faturalar(donem: _donem);
      final ozet = await widget.api.kategoriOzeti(donem: _donem);
      final kategoriler = _kategoriler.isEmpty
          ? await widget.api.kategoriListesi()
          : _kategoriler;
      if (!mounted) return;
      setState(() {
        _kayitlar = sonuc.kayitlar;
        _toplam = sonuc.toplam;
        _ozet = ozet.where((o) => o.toplam > 0).toList();
        _kategoriler = kategoriler;
        _yukleniyor = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _yukleniyor = false;
        _hata = "Bağlanılamadı: $e";
      });
    }
  }

  Future<void> _ac(Fatura kayit) async {
    if (kayit.id == null) return;
    try {
      // Listede raw_text gelmiyor (liste hafif tutuluyor); detay icin tek
      // kaydi ayrica cekiyoruz.
      final tam = await widget.api.fatura(kayit.id!);
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (_) => DraggableScrollableSheet(
          initialChildSize: 0.9,
          maxChildSize: 0.95,
          expand: false,
          builder: (_, kaydirma) => ListView(
            controller: kaydirma,
            children: [
              if (tam.gorsel != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.network(
                      widget.api.gorselAdresi(tam.id!),
                      errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                    ),
                  ),
                ),
              FaturaKarti(
                api: widget.api,
                fatura: tam,
                kategoriler: _kategoriler,
                degisti: yenile,
              ),
            ],
          ),
        ),
      );
      yenile();
    } catch (e) {
      if (mounted) setState(() => _hata = "Kayıt açılamadı: $e");
    }
  }

  Future<void> _sil(Fatura kayit) async {
    final onay = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text("#${kayit.id} silinsin mi?"),
        content: const Text("Bu işlem geri alınamaz."),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text("Vazgeç"),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text("Sil"),
          ),
        ],
      ),
    );
    if (onay != true || kayit.id == null) return;
    try {
      await widget.api.sil(kayit.id!);
      yenile();
    } catch (e) {
      if (mounted) setState(() => _hata = "Silinemedi: $e");
    }
  }

  @override
  Widget build(BuildContext context) {
    final renk = Theme.of(context).colorScheme;
    final enBuyuk = _ozet.isEmpty
        ? 1.0
        : _ozet.map((o) => o.toplam).reduce((a, b) => a > b ? a : b);

    return Scaffold(
      appBar: AppBar(
        title: Text("Kayıtlar ($_toplam)"),
        actions: [
          IconButton(
            onPressed: _yukleniyor ? null : yenile,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: yenile,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final d in Donem.values)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        label: Text(d.etiket),
                        selected: _donem == d,
                        onSelected: (_) {
                          setState(() => _donem = d);
                          yenile();
                        },
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 12),

            if (_hata != null)
              Card(
                color: renk.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(_hata!, style: TextStyle(color: renk.onErrorContainer)),
                ),
              ),

            if (_ozet.isNotEmpty)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "KATEGORİYE GÖRE HARCAMA",
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1,
                          color: renk.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 10),
                      for (final o in _ozet)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 5),
                          child: Row(
                            children: [
                              SizedBox(
                                width: 110,
                                child: Text(
                                  o.kategori,
                                  style: const TextStyle(fontSize: 13),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              Expanded(
                                child: ClipRRect(
                                  borderRadius: BorderRadius.circular(99),
                                  child: LinearProgressIndicator(
                                    value: o.toplam / enBuyuk,
                                    minHeight: 6,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Text(
                                o.toplam.toStringAsFixed(2),
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ),

            const SizedBox(height: 8),

            if (_yukleniyor && _kayitlar.isEmpty)
              const Padding(
                padding: EdgeInsets.all(32),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_kayitlar.isEmpty)
              Padding(
                padding: const EdgeInsets.all(32),
                child: Center(
                  child: Text(
                    "Bu dönemde kayıt yok",
                    style: TextStyle(color: renk.onSurfaceVariant),
                  ),
                ),
              )
            else
              Card(
                child: Column(
                  children: [
                    for (final k in _kayitlar)
                      ListTile(
                        leading: CircleAvatar(
                          child: Text(
                            _basHarfler(k.companyName),
                            style: const TextStyle(fontSize: 12),
                          ),
                        ),
                        title: Text(
                          k.companyName ?? "(firma yok)",
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          [
                            if (k.category != null) k.category!,
                            k.date ?? "tarihsiz",
                            "#${k.id}",
                          ].join(" · "),
                          style: const TextStyle(fontSize: 12),
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (k.dogrulandi)
                              const Icon(Icons.verified, size: 16, color: Colors.green),
                            const SizedBox(width: 6),
                            Text(
                              k.totalAmount ?? "—",
                              style: const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            IconButton(
                              icon: const Icon(Icons.close, size: 18),
                              onPressed: () => _sil(k),
                            ),
                          ],
                        ),
                        onTap: () => _ac(k),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  static String _basHarfler(String? ad) {
    if (ad == null || ad.trim().isEmpty) return "?";
    final harfler = ad.replaceAll(RegExp(r"[^A-Za-zÇĞİÖŞÜçğıöşü]"), "");
    return harfler.isEmpty
        ? "?"
        : harfler.substring(0, harfler.length >= 2 ? 2 : 1).toUpperCase();
  }
}
