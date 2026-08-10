import "package:flutter/material.dart";

import "api.dart";
import "ekranlar/analiz.dart";
import "ekranlar/ayarlar.dart";
import "ekranlar/kayitlar.dart";

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final api = await Api.yukle();
  runApp(FaturaUygulamasi(api: api));
}

class FaturaUygulamasi extends StatelessWidget {
  final Api api;
  const FaturaUygulamasi({super.key, required this.api});

  @override
  Widget build(BuildContext context) {
    // Web arayuzuyle ayni renk ailesi: iki istemci yan yana gosterildiginde
    // ayni urunun parcasi gibi dursunlar.
    const vurgu = Color(0xFF4338CA);

    return MaterialApp(
      title: "Fatura OCR",
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: vurgu),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: vurgu,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: AnaKabuk(api: api),
    );
  }
}

class AnaKabuk extends StatefulWidget {
  final Api api;
  const AnaKabuk({super.key, required this.api});

  @override
  State<AnaKabuk> createState() => _AnaKabukState();
}

class _AnaKabukState extends State<AnaKabuk> {
  int _sekme = 0;

  // Kayitlar ekranina "yenile" diyebilmek icin anahtar tutuyoruz: yeni bir
  // fatura analiz edildiginde liste kendiliginden guncellensin.
  final _kayitlarAnahtari = GlobalKey<KayitlarEkraniState>();

  @override
  Widget build(BuildContext context) {
    final ekranlar = [
      AnalizEkrani(
        api: widget.api,
        kaydedildi: () => _kayitlarAnahtari.currentState?.yenile(),
      ),
      KayitlarEkrani(key: _kayitlarAnahtari, api: widget.api),
      AyarlarEkrani(api: widget.api),
    ];

    return Scaffold(
      body: IndexedStack(index: _sekme, children: ekranlar),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _sekme,
        onDestinationSelected: (i) {
          setState(() => _sekme = i);
          if (i == 1) _kayitlarAnahtari.currentState?.yenile();
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.document_scanner_outlined),
            selectedIcon: Icon(Icons.document_scanner),
            label: "Analiz",
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: "Kayıtlar",
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: "Ayarlar",
          ),
        ],
      ),
    );
  }
}
