/// Sunucu adresi ve baglanti durumu.
library;

import "package:flutter/material.dart";

import "../api.dart";

class AyarlarEkrani extends StatefulWidget {
  final Api api;
  const AyarlarEkrani({super.key, required this.api});

  @override
  State<AyarlarEkrani> createState() => _AyarlarEkraniState();
}

class _AyarlarEkraniState extends State<AyarlarEkrani> {
  late final TextEditingController _adres;
  String? _durum;
  bool _deneniyor = false;
  bool _basarili = false;

  @override
  void initState() {
    super.initState();
    _adres = TextEditingController(text: widget.api.adres);
  }

  @override
  void dispose() {
    _adres.dispose();
    super.dispose();
  }

  Future<void> _kaydetVeDene() async {
    setState(() {
      _deneniyor = true;
      _durum = null;
    });
    await widget.api.adresiKaydet(_adres.text);
    _adres.text = widget.api.adres;

    try {
      final s = await widget.api.saglik();
      if (!mounted) return;
      final model = (s["adapter"] != null) ? "fine-tuned" : "base";
      setState(() {
        _basarili = true;
        _durum = "Bağlandı · $model model · ${s["kayit_sayisi"]} kayıt";
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _basarili = false;
        _durum = "Bağlanılamadı: $e";
      });
    } finally {
      if (mounted) setState(() => _deneniyor = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final renk = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(title: const Text("Ayarlar")),
      body: ListView(
        padding: const EdgeInsets.all(14),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Sunucu adresi",
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    "Servisi çalıştıran bilgisayarın adresi. Terminalde "
                    "servis açılırken \"[AG] telefondan\" satırında yazıyor.",
                    style: TextStyle(fontSize: 12.5, color: renk.onSurfaceVariant),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _adres,
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    decoration: const InputDecoration(
                      border: OutlineInputBorder(),
                      isDense: true,
                      hintText: "192.168.1.100:8000",
                    ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _deneniyor ? null : _kaydetVeDene,
                      child: Text(_deneniyor ? "Deneniyor…" : "Kaydet ve bağlantıyı dene"),
                    ),
                  ),
                  if (_durum != null) ...[
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Icon(
                          _basarili ? Icons.check_circle : Icons.error_outline,
                          size: 18,
                          color: _basarili ? Colors.green : renk.error,
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(_durum!, style: const TextStyle(fontSize: 13)),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),

          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Bağlanamıyorsan",
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  _madde(renk, "Telefon ve bilgisayar aynı ağda olmalı. "
                      "Telefon mobil veriye düşmüşse bağlanamaz."),
                  _madde(renk, "Bilgisayarın IP'si ağ değiştikçe kayıyor. "
                      "Servis açılışta güncel adresi yazıyor."),
                  _madde(renk, "Windows güvenlik duvarı 8000 portuna izin "
                      "vermeli."),
                  _madde(renk, "Kurumsal ağlar cihazlar arası iletişimi "
                      "engelleyebilir; o durumda ngrok adresini kullan."),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _madde(ColorScheme renk, String metin) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text("• ", style: TextStyle(color: renk.onSurfaceVariant)),
            Expanded(
              child: Text(
                metin,
                style: TextStyle(fontSize: 13, color: renk.onSurfaceVariant),
              ),
            ),
          ],
        ),
      );
}
