import os
import time
import threading
import requests
from flask import Flask
from rapidfuzz import process, fuzz

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Momios Novibet vs Draftea/SofaScore activo 24/7"

# === CONFIGURACIÓN DE TELEGRAM ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")

# Umbral de valor: Alerta si Novibet paga 5% o más por encima de la referencia
UMBRAL_VALOR = 1.05 

alertas_enviadas = set()

def enviar_telegram(mensaje):
    if not TOKEN:
        print("Error: No se encontró TELEGRAM_TOKEN")
        return False
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

# === 1. EXTRAER EVENTOS Y CUOTAS DE NOVIBET ===
def obtener_eventos_novibet():
    url = "https://www.novibet.mx/api/sports/v1/events/highlights"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            events = r.json().get("events", [])
            partidos = []
            for ev in events:
                local = ev.get("homeTeam", {}).get("name")
                visita = ev.get("awayTeam", {}).get("name")
                
                markets = ev.get("markets", [])
                cuota_local, cuota_visita = None, None
                if markets:
                    outcomes = markets[0].get("outcomes", [])
                    if len(outcomes) >= 2:
                        cuota_local = outcomes[0].get("price")
                        cuota_visita = outcomes[-1].get("price")
                        
                if local and visita and cuota_local and cuota_visita:
                    partidos.append({
                        "local": local,
                        "visita": visita,
                        "c_local": float(cuota_local),
                        "c_visita": float(cuota_visita)
                    })
            return partidos
        return []
    except Exception as e:
        print(f"Error al consultar Novibet: {e}")
        return []

# === 2. EXTRAER PARTIDOS DE SOFASCORE ===
def obtener_partidos_sofascore():
    fecha_hoy = time.strftime("%Y-%m-%d")
    url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha_hoy}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get("events", [])
        return []
    except Exception as e:
        print(f"Error al consultar SofaScore: {e}")
        return []

# === 3. EXTRAER CUOTAS ESPECÍFICAS DE DRAFTEA/SOFASCORE ===
def obtener_cuotas_evento_sofascore(evento_id):
    url = f"https://api.sofascore.com/api/v1/event/{evento_id}/odds/1/all"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            markets = r.json().get("markets", [])
            for market in markets:
                # Mercado principal 1X2 / Full time
                if market.get("marketName") in ["Full time", "1X2", "Match odds"]:
                    cuota_draftea_local = None
                    cuota_ref_local = None
                    
                    for provider in market.get("providers", []):
                        nombre_casa = provider.get("bookmaker", {}).get("name", "").lower()
                        choices = provider.get("choices", [])
                        
                        if len(choices) >= 2:
                            val_local = float(choices[0].get("initialDecimalValue", choices[0].get("decimalValue", 0)))
                            
                            # Prioridad si el proveedor es Draftea
                            if "draftea" in nombre_casa and val_local > 0:
                                return val_local, "Draftea"
                            
                            if val_local > 0 and not cuota_ref_local:
                                cuota_ref_local = val_local
                                
                    if cuota_ref_local:
                        return cuota_ref_local, "SofaScore (Mercado Global)"
        return None, None
    except Exception as e:
        print(f"Error extrayendo cuotas de evento SofaScore {evento_id}: {e}")
        return None, None

# === 4. CICLO DE MONITOREO Y COMPARACIÓN ===
def monitorear():
    print("🤖 Bot de momios iniciado: Novibet vs Draftea/SofaScore...")
    enviar_telegram("🚀 <b>Bot de Momios Reconfigurado</b>\n\nComparación activa: Novibet vs Draftea (vía SofaScore).")
    
    while True:
        try:
            novi_partidos = obtener_eventos_novibet()
            sofa_partidos = obtener_partidos_sofascore()
            
            if novi_partidos and sofa_partidos:
                nombres_sofa = [f"{s.get('homeTeam', {}).get('name')} vs {s.get('awayTeam', {}).get('name')}" for s in sofa_partidos]
                
                for p_novi in novi_partidos:
                    nombre_novi = f"{p_novi['local']} vs {p_novi['visita']}"
                    
                    # Fuzzy matching de nombres
                    match = process.extractOne(
                        nombre_novi, 
                        nombres_sofa, 
                        scorer=fuzz.token_sort_ratio
                    )
                    
                    if match and match[1] >= 75: # Similitud >= 75%
                        idx_sofa = match[2]
                        evento_sofa = sofa_partidos[idx_sofa]
                        evento_id = evento_sofa.get("id")
                        
                        cuota_ref, fuente = obtener_cuotas_evento_sofascore(evento_id)
                        
                        if cuota_ref and cuota_ref > 0:
                            # Comparar cuota local de Novibet contra la referencia
                            if p_novi['c_local'] >= (cuota_ref * UMBRAL_VALOR):
                                diff = round(((p_novi['c_local'] / cuota_ref) - 1) * 100, 1)
                                alerta_id = f"{nombre_novi}_local_{p_novi['c_local']}"
                                
                                if alerta_id not in alertas_enviadas:
                                    msg = (
                                        f"🔥 <b>VALOR DETECTADO EN NOVIBET</b>\n\n"
                                        f"⚽ <b>Partido:</b> {nombre_novi}\n"
                                        f"🎯 <b>Apuesta:</b> Victoria {p_novi['local']}\n\n"
                                        f"🟢 <b>Novibet:</b> {p_novi['c_local']}\n"
                                        f"📊 <b>Ref ({fuente}):</b> {cuota_ref}\n"
                                        f"📈 <b>Ventaja:</b> +{diff}%"
                                    )
                                    enviar_telegram(msg)
                                    alertas_enviadas.add(alerta_id)
                                    
            time.sleep(300) # Revisa cada 5 minutos

        except Exception as e:
            print(f"Error en el ciclo principal: {e}")
            time.sleep(60)

# Iniciar el bucle en un hilo secundario
hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
