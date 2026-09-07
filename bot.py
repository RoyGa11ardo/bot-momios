import os
import requests
from flask import Flask

app = Flask(__name__)

@app.route('/', methods=['HEAD', 'GET'])
def home():
    return "Bot de Momios Activo"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

UMBRAL_VALOR = 1.05 
alertas_enviadas = set()

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga"
]

def enviar_telegram(mensaje):
    if not TOKEN:
        print("❌ ERROR: TELEGRAM_TOKEN no está configurado.", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"📱 Telegram Status: {r.status_code}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}", flush=True)
        return False

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        print("❌ ERROR: THE_ODDS_API_KEY está vacía.", flush=True)
        return []
    
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us&markets=h2h&oddsFormat=decimal"
    
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

def ejecutar_prueba_inmediata():
    print("🚀 Ejecutando escaneo de prueba inmediato al arrancar...", flush=True)
    total_eventos = 0
    partidos_para_reporte = []
    novibet_encontrados_total = 0

    for sport_key in LIGAS:
        eventos = obtener_partidos_liga(sport_key)
        total_eventos += len(eventos)
        
        if eventos:
            nombre_liga_limpio = sport_key.replace("soccer_", "").replace("_", " ").title()

            for evento in eventos:
                local = evento.get("home_team")
                visita = evento.get("away_team")
                nombre_partido = f"{local} vs {visita}"
                
                bookmakers = evento.get("bookmakers", [])
                cuotas_mercado = {}
                novibet_cuotas = {}
                
                for book in bookmakers:
                    book_key = book.get("key", "").lower()
                    markets = book.get("markets", [])
                    for m in markets:
                        if m.get("key") == "h2h":
                            outcomes = m.get("outcomes", [])
                            precios = {}
                            for out in outcomes:
                                name = out.get("name")
                                price = out.get("price")
                                if name == local:
                                    precios["1"] = float(price)
                                elif name == visita:
                                    precios["2"] = float(price)
                                else:
                                    precios["X"] = float(price)
                                    
                            if "novibet" in book_key:
                                novibet_cuotas = precios
                                novibet_encontrados_total += 1
                            else:
                                for k, v in precios.items():
                                    if k not in cuotas_mercado:
                                        cuotas_mercado[k] = []
                                    cuotas_mercado[k].append(v)

                if novibet_cuotas and len(partidos_para_reporte) < 6:
                    query_busqueda = f"site:sofascore.com {local} {visita}".replace(" ", "+")
                    url_stats = f"https://www.google.com/search?q={query_busqueda}"
                    
                    c_1 = novibet_cuotas.get("1", "-")
                    c_x = novibet_cuotas.get("X", "-")
                    c_2 = novibet_cuotas.get("2", "-")

                    partidos_para_reporte.append(
                        f"• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                        f"   🟢 Novibet: 1({c_1}) | X({c_x}) | 2({c_2})\n"
                        f"   👉 <a href='{url_stats}'>Ver estadísticas en Sofascore</a>"
                    )

    print(f"📊 [Resumen] Total eventos: {total_eventos} | Novibet encontrados: {novibet_encontrados_total}", flush=True)

    if partidos_para_reporte:
        cuerpo_reporte = "\n\n".join(partidos_para_reporte)
        reporte_msg = (
            f"🧪 <b>PRUEBA DE ARRANQUE EXITOSA</b>\n\n"
            f"{cuerpo_reporte}"
        )
        enviar_telegram(reporte_msg)
    else:
        enviar_telegram("⚠️ El bot arrancó pero The Odds API no devolvió partidos con cuotas de Novibet en este momento.")

# Ejecutar la prueba en cuanto el script compile
ejecutar_prueba_inmediata()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
