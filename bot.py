import os
import requests
from flask import Flask

app = Flask(__name__)

@app.route('/', methods=['HEAD', 'GET'])
def home():
    return "Bot de Momios - Radar de Bookmakers Activo"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga"
]

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        print("❌ ERROR: THE_ODDS_API_KEY está vacía.", flush=True)
        return []
    
    # Probamos ampliando regiones a eu,us,uk para atrapar más bookmakers
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us,uk&markets=h2h&oddsFormat=decimal"
    
    try:
        r = requests.get(target_url, timeout=15)
        print(f"🔍 API Response [{sport_key}] -> Status: {r.status_code}", flush=True)
        if r.status_code == 200:
            data = r.json()
            print(f"📦 Partidos devueltos para {sport_key}: {len(data)}", flush=True)
            return data
        else:
            print(f"⚠️ Error de API en {sport_key}: {r.text}", flush=True)
            return []
    except Exception as e:
        print(f"❌ Excepción consultando {sport_key}: {e}", flush=True)
        return []

def escanear_bookmakers():
    print("🚀 Iniciando escaneo de casas de apuestas disponibles...", flush=True)
    casas_encontradas = set()
    total_eventos = 0

    for sport_key in LIGAS:
        eventos = obtener_partidos_liga(sport_key)
        total_eventos += len(eventos)
        
        for evento in eventos:
            bookmakers = evento.get("bookmakers", [])
            for book in bookmakers:
                key = book.get("key", "")
                title = book.get("title", "")
                casas_encontradas.add(f"{title} (key: {key})")

    print(f"📋 CASAS DE APUESTAS DISPONIBLES EN TU PLAN DE LA API:", flush=True)
    for casa in sorted(casas_encontradas):
        print(f"   - {casa}", flush=True)
    
    if not casas_encontradas:
        print("⚠️ No se encontró ninguna casa de apuestas. Revisa tu API Key.", flush=True)

# Ejecutar el escaneo al arrancar para ver qué casas llegan
escanear_bookmakers()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
