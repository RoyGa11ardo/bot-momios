import os
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from flask import Flask
from rapidfuzz import process, fuzz

app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Bot de Momios (The Odds API + Novibet) activo 24/7"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

UMBRAL_VALOR = 1.05 
alertas_enviadas = set()

def enviar_telegram(mensaje):
    if not TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except:
        return False

# === 1. OBTENER DATOS DE THE ODDS API (REFERENCIA DE MERCADO) ===
def obtener_partidos_odds_api():
    if not THE_ODDS_API_KEY:
        print("⚠️ Falta configurar THE_ODDS_API_KEY en las variables de entorno de Render.", flush=True)
        return []
    
    # Usamos fútbol soccer / ligas principales (ej. Champions, Liga MX, Premier League)
    sport_key = "soccer_mexico_ligamx" # O puedes cambiarlo a soccer_epl, etc.
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us,mx&markets=h2h&oddsFormat=decimal"
    
    try:
        r = requests.get(target_url, timeout=15)
        print(f"DEBUG The Odds API Status: {r.status_code}", flush=True)
        if r.status_code == 200:
            data = r.json()
            print(f"DEBUG The Odds API Eventos encontrados: {len(data)}", flush=True)
            return data
        else:
            print(f"DEBUG The Odds API Error: {r.text[:150]}", flush=True)
            return []
    except Exception as e:
        print(f"Error al consultar The Odds API: {e}", flush=True)
        return []

# === 2. CICLO DE MONITOREO ===
def monitorear():
    print("🤖 Bot de momios optimizado activado...", flush=True)
    
    while True:
        try:
            eventos = obtener_partidos_odds_api()
            
            if eventos:
                for evento in eventos:
                    local = evento.get("home_team")
                    visita = evento.get("away_team")
                    nombre_partido = f"{local} vs {visita}"
                    
                    bookmakers = evento.get("bookmakers", [])
                    
                    # Buscamos si Novibet u otras casas están disponibles en la respuesta
                    # The Odds API incluye casas de apuestas globales y locales según la región
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
                                        precios["X"] = float(price) # En caso de empate
                                        
                                if "novibet" in book_key:
                                    novibet_cuotas = precios
                                else:
                                    # Guardamos como referencia de mercado general
                                    for k, v in precios.items():
                                    # Promediamos o guardamos la referencia
                                        if k not in cuotas_mercado:
                                            cuotas_mercado[k] = []
                                        cuotas_mercado[k].append(v)

                    # Si tenemos cuotas de Novibet y referencias del mercado
                    if novibet_cuotas and cuotas_mercado:
                        # Calcular promedio del mercado
                        promedios_ref = {k: sum(v)/len(v) for k, v in cuotas_mercado.items() if v}
                        
                        etiquetas = {
                            "1": f"Victoria {local}",
                            "X": "Empate",
                            "2": f"Victoria {visita}"
                        }
                        
                        for k, c_novi in novibet_cuotas.items():
                            c_ref = promedios_ref.get(k, 0)
                            if c_ref > 0 and c_novi >= (c_ref * UMBRAL_VALOR):
                                diff = round(((c_novi / c_ref) - 1) * 100, 1)
                                alerta_id = f"{nombre_partido}_{k}_{c_novi}"
                                
                                if alerta_id not in alertas_enviadas:
                                    msg = (
                                        f"🔥 <b>VALOR DETECTADO EN NOVIBET</b>\n\n"
                                        f"⚽ <b>Partido:</b> {nombre_partido}\n"
                                        f"🎯 <b>Apuesta:</b> {etiquetas.get(k, k)}\n\n"
                                        f"🟢 <b>Novibet:</b> {c_novi}\n"
                                        f"📊 <b>Promedio Mercado:</b> {round(c_ref, 2)}\n"
                                        f"📈 <b>Ventaja:</b> +{diff}%"
                                    )
                                    enviar_telegram(msg)
                                    alertas_enviadas.add(alerta_id)
                                    
            time.sleep(300)

        except Exception as e:
            print(f"Error en el ciclo principal: {e}", flush=True)
            time.sleep(60)

hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
