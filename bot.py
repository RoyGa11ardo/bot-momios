import os
import time
import threading
import requests
from flask import Flask

# Servidor Flask para mantener activo el Web Service gratuito de Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Momios activo 24/7"

# === CONFIGURACIÓN DE TELEGRAM ===
import os
# Lee el token desde las variables de entorno de Render
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = "1530533411"

alertas_enviadas = set()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")
        return False

def obtener_eventos_novibet():
    url = "https://www.novibet.mx/api/sports/v1/events/highlights"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        print(f"Error al consultar Novibet: {e}")
        return None

def obtener_partidos_sofascore():
    fecha_hoy = time.strftime("%Y-%m-%d")
    url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha_hoy}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get("events", [])
        return []
    except Exception as e:
        print(f"Error al consultar SofaScore: {e}")
        return []

def monitorear():
    print("🤖 Bot de momios iniciado en la nube (Render Web Service)...")
    enviar_telegram("🚀 <b>Bot de Momios Activado en la Nube (24/7)</b>\n\nEl servidor está monitoreando Novibet y SofaScore sin restricciones de proxy.")
    
    while True:
        try:
            novi_data = obtener_eventos_novibet()
            if novi_data:
                print("✓ Datos recibidos correctamente de Novibet.")
            
            sofa_events = obtener_partidos_sofascore()
            if sofa_events:
                total_partidos = len(sofa_events)
                print(f"✓ Datos recibidos correctamente de SofaScore ({total_partidos} partidos hoy).")
                
                if "resumen_dia" not in alertas_enviadas and total_partidos > 0:
                    primer_evento = sofa_events[0]
                    local = primer_evento.get("homeTeam", {}).get("name", "Local")
                    visita = primer_evento.get("awayTeam", {}).get("name", "Visita")
                    
                    msg = (
                        f"📊 <b>RESUMEN JORNADA DE HOY</b>\n\n"
                        f"⚽ <b>Partidos programados:</b> {total_partidos}\n"
                        f"🔥 <b>Ejemplo:</b> {local} vs {visita}\n\n"
                        f"🟢 <i>Monitoreo activo para cruce de valor.</i>"
                    )
                    enviar_telegram(msg)
                    alertas_enviadas.add("resumen_dia")

            time.sleep(300)

        except Exception as e:
            print(f"Error en el ciclo principal: {e}")
            time.sleep(60)

# Iniciar el bucle del bot en un hilo secundario
hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
