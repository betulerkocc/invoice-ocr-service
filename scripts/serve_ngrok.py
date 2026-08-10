"""
FastAPI servisini ayaga kaldirir ve ngrok ile disariya acar.

Yerelde neden gerekli: makinenin IP'si ag degistikce kayiyor (hotspot, ev
wifi'si, kampus agi hepsi baska adres veriyor) ve bazi aglar cihazlar arasi
iletisimi engelliyor. ngrok disariya bir tunel acip sabit bir https adresi
veriyor - telefon hangi agda olursa olsun, mobil veride bile calisiyor.

Kaggle'da neden gerekli: notebook disaridan gelen istekleri kabul etmiyor.
Deligi acan taraf ic taraf oldugu icin guvenlik duvari sorun cikarmiyor.

Gereken: ngrok authtoken (ucretsiz, https://dashboard.ngrok.com).
Token asla koda yazilmaz; sirasiyla su iki yerden aranir:
    1. Kaggle Secrets  -> NGROK_AUTHTOKEN
    2. Ortam degiskeni -> NGROK_AUTHTOKEN

Kullanim:
    python scripts/serve_ngrok.py
    python scripts/serve_ngrok.py --port 8000

Token: .env dosyasina NGROK_AUTHTOKEN=... satiri ekleyin
       (Kaggle'da Add-ons -> Secrets uzerinden de okunuyor)

Bu script bilerek bloklar: calistigi surece servis ayakta, durdurunca kapanir.
"""

import argparse
import os
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "api"))

# .env'deki NGROK_AUTHTOKEN okunsun. Token koda yazilmiyor: repo paylasilirsa
# birlikte gitmesin ve baskasi senin hesabin adina tunel acamasin.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_BASE_DIR, "..", ".env"))
except ImportError:
    pass


def _authtoken_bul() -> str:
    """Token'i once Kaggle Secrets'ta, sonra ortam degiskenlerinde arar."""
    # Once ortam degiskeni: notebook'ta elle set edildiyse en guvenilir yol.
    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if token:
        print("[ngrok] token ortam degiskeninden alindi")
        return token

    try:
        from kaggle_secrets import UserSecretsClient

        token = (UserSecretsClient().get_secret("NGROK_AUTHTOKEN") or "").strip()
        if token:
            print("[ngrok] token Kaggle Secrets'tan alindi")
            return token
        neden = "secret bos dondu"
    except ImportError:
        neden = "kaggle_secrets modulu yok (Kaggle disindayiz)"
    except Exception as e:
        # Sebebi bastirmiyoruz: 'secret yok' ile 'secret attach edilmemis'
        # ayrimini yapabilmek icin gercek hata mesaji lazim.
        neden = f"{type(e).__name__}: {e}"

    sys.exit(
        f"HATA: ngrok authtoken bulunamadi.  (denenen: ortam degiskeni, Kaggle Secrets -> {neden})\n"
        "\n"
        "  Yerelde calisiyorsaniz:\n"
        "    Proje kokundeki .env dosyasina su satiri ekleyin:\n"
        "      NGROK_AUTHTOKEN=buraya_token\n"
        "\n"
        "  Kaggle'da calisiyorsaniz:\n"
        "    Add-ons -> Secrets -> 'NGROK_AUTHTOKEN' adiyla ekleyip notebook'a attach edin\n"
        "\n"
        "  Token: https://dashboard.ngrok.com/get-started/your-authtoken\n"
        "  (.env dosyasi .gitignore'da; token repoya girmez)"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    try:
        from pyngrok import ngrok
    except ImportError:
        sys.exit("HATA: pyngrok kurulu degil.  ->  pip install pyngrok")

    import uvicorn

    ngrok.set_auth_token(_authtoken_bul())

    # Ayni oturumda script ikinci kez calistirilirsa eski tunel port'u tutar
    for eski in ngrok.get_tunnels():
        print(f"[ngrok] eski tunel kapatiliyor: {eski.public_url}")
        ngrok.disconnect(eski.public_url)

    tunel = ngrok.connect(args.port, "http")
    url = tunel.public_url.replace("http://", "https://")

    print("\n" + "=" * 62)
    print("  PUBLIC URL :", url)
    print("  Swagger    :", f"{url}/docs")
    print("  Endpoint   :", f"POST {url}/analyze-invoice   (form-data, alan adi: file)")
    print("=" * 62)
    print("\nURL her oturumda degisir. Bu hucre calistigi surece servis ayakta.\n")

    # Import burada: modeller yuklenmeden once URL'i ekrana basmak istiyoruz ki
    # sen Postman'i hazirlarken model yuklemesi arka planda ilerlesin.
    from main import app

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
