import os
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from flask import Flask

app = Flask(__name__)

@app.route('/', methods=['HEAD', 'GET'])
def home():
    return "Bot de Momios con Alerta de Prueba activo 24/7"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

UMBRAL_VALOR = 1.00 
alertas_enviadas = set()

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga"
]

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

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        print("⚠️ Falta configurar THE_ODDS_API_KEY en las variables de entorno de Render.", flush=True)
        return []
    
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us&markets=h2h&oddsFormat=decimal"
    
    try:
        r = requests.get(target_url, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"DEBUG {sport_key} Error Status: {r.status_code}", flush=True)
            return []
    except Exception as e:
        print(f"Error al consultar {sport_key}: {e}", flush=True)
        return []

def ejecutar_ciclo():
    total_eventos = 0
    for sport_key in LIGAS:
        eventos = obtener_partidos_liga(sport_key)
        total_eventos += len(eventos)
        
        if eventos:
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
                            else:
                                for k, v in precios.items():
                                    if k not in cuotas_mercado:
                                        cuotas_mercado[k] = []
                                    cuotas_mercado[k].append(v)

                if novibet_cuotas and cuotas_mercado:
                    promedios_ref = {k: sum(v)/len(v) for k, v in cuotas_mercado.items() if v}
                    etiquetas = {"1": f"Victoria {local}", "X": "Empate", "2": f"Victoria {visita}"}
                    
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
        
        time.sleep(3)

    print(f"🔍 [Revisión Completa] Partidos analizados: {total_eventos}.", flush=True)

def monitorear():
    print("🤖 Bot de momios activado con prueba de formato...", flush=True)
    
    # 🧪 MENSAJE DE PRUEBA DE FORMATO INMEDIATO
    mensaje_ejemplo = (
        "🔥 <b>[MENSAJE DE PRUEBA] VALOR DETECTADO EN NOVIBET</b>\n\n"
        "⚽ <b>Partido:</b> Real Madrid vs Barcelona\n"
        "🎯 <b>Apuesta:</b> Victoria Real Madrid\n\n"
        "🟢 <b>Novibet:</b> 2.15\n"
        "📊 <b>Promedio Mercado:</b> 2.00\n"
        "📈 <b>Ventaja:</b> +7.5%"
    )
    enviar_telegram(mensaje_ejemplo)

    tz = ZoneInfo("America/Mazatlan")
    
    while True:
        ahora = datetime.now(tz)
        objetivo = ahora.replace(hour=6, minute=0, second=0, microsecond=0)
        
        if ahora >= objetivo:
            objetivo += timedelta(days=1)
            
        segundos_hasta_las_6 = (objetivo - ahora).total_seconds()
        horas_espera = round(segundos_hasta_las_6 / 3600, 2)
        
        print(f"⏳ Son las {ahora.strftime('%H:%M:%S')}. Esperando {horas_espera} horas para el primer escaneo a las 6:00 AM...", flush=True)
        
        # Dormimos hasta las 6:00 AM
        time.sleep(segundos_hasta_las_6)
        
        # Bucle de los 4 escaneos diarios (cada 6 horas)
        for _ in range(4):
            print("🌅 Ejecutando escaneo programado...", flush=True)
            ejecutar_ciclo()
            print("💤 Ciclo terminado. Durmiendo 6 horas...", flush=True)
            time.sleep(21600)

hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
