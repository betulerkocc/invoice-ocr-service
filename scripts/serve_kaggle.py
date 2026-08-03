"""
Kaggle uzerinde FastAPI servisini ayaga kaldirir ve ngrok ile disariya acar.

Kaggle notebook'u disaridan gelen istekleri kabul etmez; servis 'localhost:8000'
de calisir ama o localhost Kaggle sunucusunun icidir. ngrok, Kaggle'in icinden
disariya bir tunel acar ve geciçi bir public URL verir. Deligi acan taraf Kaggle
oldugu icin guvenlik duvari sorun cikarmaz.

Gereken: ngrok authtoken (ucretsiz, https://dashboard.ngrok.com).
Token asla koda yazilmaz; sirasiyla su iki yerden aranir:
    1. Kaggle Secrets  -> NGROK_AUTHTOKEN
    2. Ortam degiskeni -> NGROK_AUTHTOKEN

Kullanim:
    python scripts/serve_kaggle.py
    python scripts/serve_kaggle.py --port 8000

Bu script bilerek bloklar: calistigi surece servis ayakta, durdurunca kapanir.
"""

import argparse
import os
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_BASE_DIR, "..", "api"))


def _authtoken_bul() -> str:
    """Token'i once Kaggle Secrets'ta, sonra ortam degiskenlerinde arar."""
    try:
        from kaggle_secrets import UserSecretsClient

        token = UserSecretsClient().get_secret("NGROK_AUTHTOKEN")
        if token:
            print("[ngrok] token Kaggle Secrets'tan alindi")
            return token.strip()
    except Exception:
        pass  # Kaggle disindayiz ya da secret tanimli degil -> ortam degiskenine bak

    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if token:
        print("[ngrok] token ortam degiskeninden alindi")
        return token

    sys.exit(
        "HATA: ngrok authtoken bulunamadi.\n"
        "  Kaggle'da: Add-ons -> Secrets -> 'NGROK_AUTHTOKEN' adiyla ekleyin,\n"
        "  ardindan notebook'ta secret'i bu script icin gorunur kilin.\n"
        "  Token: https://dashboard.ngrok.com/get-started/your-authtoken"
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
