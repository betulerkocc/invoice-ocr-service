/// Fotograf cekme / secme ve analiz ekrani.
library;

import "dart:io";

import "package:flutter/material.dart";
import "package:image_picker/image_picker.dart";

import "../api.dart";
import "../model.dart";
import "fatura_karti.dart";

class AnalizEkrani extends StatefulWidget {
  final Api api;
  final VoidCallback? kaydedildi;
  const AnalizEkrani({super.key, required this.api, this.kaydedildi});

  @override
  State<AnalizEkrani> createState() => _AnalizEkraniState();
}

class _AnalizEkraniState extends State<AnalizEkrani> {
  final _secici = ImagePicker();

  List<File> _secilenler = [];
  Fatura? _sonuc;
  List<String> _kategoriler = [];

  bool _calisiyor = false;
  int _islenen = 0;
  String? _hata;

  @override
  void initState() {
    super.initState();
    _kategorileriYukle();
  }

  Future<void> _kategorileriYukle() async {
    try {
      final k = await widget.api.kategoriListesi();
      if (mounted) setState(() => _kategoriler = k);
    } catch (_) {
      // Kategori listesi alinamazsa uygulama yine calisir, sadece acilir
      // menu bos kalir. Bunun icin kullaniciyi rahatsiz etmeye gerek yok.
    }
  }

  Future<void> _sec({required bool kamera}) async {
    try {
      if (kamera) {
        final x = await _secici.pickImage(
          source: ImageSource.camera,
          // Sunucu zaten 1600 piksele indiriyor. Burada kucultmek yukleme
          // suresini de kisaltiyor - telefon fotografi 4-5 MB geliyor.
          maxWidth: 1600,
          maxHeight: 1600,
          imageQuality: 85,
        );
        if (x != null) setState(() => _secilenler = [File(x.path)]);
      } else {
        final list = await _secici.pickMultiImage(
          maxWidth: 1600,
          maxHeight: 1600,
          imageQuality: 85,
        );
        if (list.isNotEmpty) {
          setState(() => _secilenler = list.map((x) => File(x.path)).toList());
        }
      }
      setState(() {
        _hata = null;
        _sonuc = null;
      });
    } catch (e) {
      setState(() => _hata = "Görsel seçilemedi: $e");
    }
  }

  Future<void> _analizEt() async {
    if (_secilenler.isEmpty) return;
    setState(() {
      _calisiyor = true;
      _hata = null;
      _sonuc = null;
      _islenen = 0;
    });

    Fatura? sonSonuc;
    var hatali = 0;

    // Dosyalar SIRAYLA gonderiliyor: sunucuda tek model ornegi var, es zamanli
    // istekler GPU'da birbirini bekletmekten baska bir sey yapmiyor.
    for (final dosya in _secilenler) {
      try {
        sonSonuc = await widget.api.analizEt(dosya);
      } catch (e) {
        hatali++;
      }
      if (!mounted) return;
      setState(() => _islenen++);
    }

    setState(() {
      _calisiyor = false;
      // Tek dosyada sonucu gosteriyoruz; toplu yuklemede kayitlar sekmesine
      // bakmak daha anlamli, 40 karti alt alta basmanin faydasi yok.
      _sonuc = _secilenler.length == 1 ? sonSonuc : null;
      if (hatali > 0) {
        _hata = "$hatali görsel işlenemedi "
            "(${_secilenler.length - hatali} tanesi kaydedildi).";
      }
      if (_secilenler.length > 1) _secilenler = [];
    });
    widget.kaydedildi?.call();
  }

  @override
  Widget build(BuildContext context) {
    final renk = Theme.of(context).colorScheme;
    final coklu = _secilenler.length > 1;

    return Scaffold(
      appBar: AppBar(title: const Text("Fatura OCR")),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _calisiyor ? null : () => _sec(kamera: true),
                          icon: const Icon(Icons.photo_camera_outlined),
                          label: const Text("Fotoğraf çek"),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _calisiyor ? null : () => _sec(kamera: false),
                          icon: const Icon(Icons.photo_library_outlined),
                          label: const Text("Galeriden seç"),
                        ),
                      ),
                    ],
                  ),

                  if (_secilenler.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    if (coklu)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text("${_secilenler.length} görsel seçildi"),
                      )
                    else
                      ClipRRect(
                        borderRadius: BorderRadius.circular(10),
                        child: Image.file(_secilenler.first, fit: BoxFit.cover),
                      ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _calisiyor ? null : _analizEt,
                        child: Text(
                          coklu
                              ? "${_secilenler.length} fişi analiz et"
                              : "Analiz Et",
                        ),
                      ),
                    ),
                  ],

                  if (_calisiyor) ...[
                    const SizedBox(height: 14),
                    LinearProgressIndicator(
                      value: _secilenler.length > 1
                          ? _islenen / _secilenler.length
                          : null,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _secilenler.length > 1
                          ? "$_islenen / ${_secilenler.length} işlendi"
                          : "Okunuyor ve ayıklanıyor…",
                      style: TextStyle(fontSize: 13, color: renk.onSurfaceVariant),
                    ),
                  ],

                  if (_hata != null) ...[
                    const SizedBox(height: 10),
                    Text(_hata!, style: TextStyle(color: renk.error, fontSize: 13)),
                  ],
                ],
              ),
            ),
          ),

          if (_sonuc != null)
            FaturaKarti(
              api: widget.api,
              fatura: _sonuc!,
              kategoriler: _kategoriler,
              degisti: widget.kaydedildi,
            ),
        ],
      ),
    );
  }
}
