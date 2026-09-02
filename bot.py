import os
import time
import json
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from flask import Flask
from rapidfuzz import process, fuzz

app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Bot de Momios Novibet vs SofaScore activo 24/7"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")

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

def hacer_peticion_proxy(target_url, extra_headers=None, render_js=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, application/xhtml+xml, */*",
        "Accept-Language": "es-MX,es;q=0.9,en;q=0.8"
    }
    if extra_headers:
        headers.update(extra_headers)

    if SCRAPERAPI_KEY:
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={target_url}&keep_headers=true"
        if render_js:
            proxy_url += "&render=true"
        return requests.get(proxy_url, headers=headers, timeout=60)
    else:
        return requests.get(target_url, headers=headers, timeout=20)

# === 1. EXTRAER EVENTOS Y MERCADOS DE NOVIBET (CON RENDERIZADO JS) ===
def obtener_eventos_novibet():
    target_url = "https://www.novibet.mx/apuestas-deportivas/futbol/1"
    
    try:
        # render_js=True para que ScraperAPI ejecute Angular y cargue los partidos en el DOM
        r = hacer_peticion_proxy(target_url, render_js=True)
        print(f"DEBUG Novibet Status: {r.status_code}", flush=True)
        
        partidos = []
        if r.status_code == 200:
            texto = r.text
            
            # Buscar bloques JSON inyectados o estados globales de la aplicación
            json_blocks = re.findall(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', texto, re.DOTALL | re.IGNORECASE)
            json_blocks.extend(re.findall(r'window\.[a-zA-Z0-9_]+\s*=\s*({.*?});', texto, re.DOTALL))
            
            events = []
            
            def buscar_eventos_dict(d):
                if isinstance(d, dict):
                    if "homeTeam" in d and "awayTeam" in d and ("markets" in d or "prices" in d or "odds" in d):
                        events.append(d)
                    for v in d.values():
                        buscar_eventos_dict(v)
                elif isinstance(d, list):
                    for item in d:
                        buscar_eventos_dict(item)

            for block in json_blocks:
                try:
                    data = json.loads(block)
                    buscar_eventos_dict(data)
                except:
                    continue
                    
            print(f"DEBUG Novibet Events encontrados en HTML renderizado: {len(events)}", flush=True)

            for ev in events:
                local = ev.get("homeTeam", {}).get("name") if isinstance(ev.get("homeTeam"), dict) else ev.get("homeTeam")
                visita = ev.get("awayTeam", {}).get("name") if isinstance(ev.get("awayTeam"), dict) else ev.get("awayTeam")
                
                markets = ev.get("markets", [])
                cuotas = {}
                
                for market in markets:
                    m_name = str(market.get("header", "") or market.get("name", "")).lower()
                    outcomes = market.get("outcomes", [])
                    
                    if any(k in m_name for k in ["resultado", "1x2", "ganador"]):
                        if len(outcomes) >= 3:
                            cuotas["1"] = float(outcomes[0].get("price", 0))
                            cuotas["X"] = float(outcomes[1].get("price", 0))
                            cuotas["2"] = float(outcomes[2].get("price", 0))
                        elif len(outcomes) == 2:
                            cuotas["1"] = float(outcomes[0].get("price", 0))
                            cuotas["2"] = float(outcomes[1].get("price", 0))
                    
                    if any(k in m_name for k in ["total", "goles", "over"]):
                        for out in outcomes:
                            desc = str(out.get("caption", "") or out.get("name", "")).lower()
                            if "más" in desc or "over" in desc or "> 2.5" in desc:
                                cuotas["O2.5"] = float(out.get("price", 0))
                            elif "menos" in desc or "under" in desc or "< 2.5" in desc:
                                cuotas["U2.5"] = float(out.get("price", 0))

                if local and visita and cuotas:
                    partidos.append({
                        "local": str(local),
                        "visita": str(visita),
                        "cuotas": cuotas
                    })
        return partidos
    except Exception as e:
        print(f"Error al consultar Novibet: {e}", flush=True)
        return []

# === 2. EXTRAER PARTIDOS DE SOFASCORE (CON RENDERIZADO JS) ===
def obtener_partidos_sofascore():
    tz = ZoneInfo("America/Mexico_City")
    fecha_hoy = datetime.now(tz).strftime("%Y-%m-%d")
    
    target_url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha_hoy}"
    extra_headers = {
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com"
    }
    
    try:
        # Activamos render_js aquí también para evitar bloqueos por IP Cloudflare
        r = hacer_peticion_proxy(target_url, extra_headers, render_js=True)
        print(f"DEBUG SofaScore Status: {r.status_code}", flush=True)
        
        if r.status_code == 200:
            try:
                data = r.json()
                events = data.get("events", [])
                print(f"DEBUG SofaScore Events encontrados para {fecha_hoy}: {len(events)}", flush=True)
                return events
            except:
                print("⚠️ SofaScore no retornó JSON válido tras renderizado.", flush=True)
        else:
             print(f"DEBUG SofaScore Error Response: {r.text[:150]}", flush=True)
        return []
    except Exception as e:
        print(f"Error al consultar SofaScore: {e}", flush=True)
        return []

# === 3. EXTRAER CUOTAS DE SOFASCORE ===
def obtener_cuotas_evento_sofascore(evento_id):
    target_url = f"https://api.sofascore.com/api/v1/event/{evento_id}/odds/1/all"
    extra_headers = {"Referer": "https://www.sofascore.com/"}
    try:
        r = hacer_peticion_proxy(target_url, extra_headers, render_js=False)
        if r.status_code == 200:
            markets = r.json().get("markets", [])
            cuotas_ref = {}
            fuente = "SofaScore"
            
            for market in markets:
                m_name = market.get("marketName", "")
                if m_name in ["Full time", "1X2", "Match odds"]:
                    for provider in market.get("providers", []):
                        choices = provider.get("choices", [])
                        if len(choices) >= 2 and "1" not in cuotas_ref:
                            cuotas_ref["1"] = float(choices[0].get("initialDecimalValue", choices[0].get("decimalValue", 0)))
                            cuotas_ref["2"] = float(choices[-1].get("initialDecimalValue", choices[-1].get("decimalValue", 0)))
                            if len(choices) == 3:
                                cuotas_ref["X"] = float(choices[1].get("initialDecimalValue", choices[1].get("decimalValue", 0)))

            return cuotas_ref, fuente
        return {}, ""
    except Exception as e:
        return {}, ""

# === 4. CICLO DE MONITOREO ===
def monitorear():
    print("🤖 Bot de momios activado...", flush=True)
    
    while True:
        try:
            novi_partidos = obtener_eventos_novibet()
            sofa_partidos = obtener_partidos_sofascore()
            
            print(f"🔍 [Revisión] Novibet: {len(novi_partidos)} partidos | SofaScore: {len(sofa_partidos)} partidos", flush=True)
            
            if novi_partidos and sofa_partidos:
                nombres_sofa = [f"{s.get('homeTeam', {}).get('name')} vs {s.get('awayTeam', {}).get('name')}" for s in sofa_partidos]
                
                for p_novi in novi_partidos:
                    nombre_novi = f"{p_novi['local']} vs {p_novi['visita']}"
                    
                    match = process.extractOne(
                        nombre_novi, 
                        nombres_sofa, 
                        scorer=fuzz.token_sort_ratio
                    )
                    
                    if match and match[1] >= 75:
                        idx_sofa = match[2]
                        evento_sofa = sofa_partidos[idx_sofa]
                        evento_id = evento_sofa.get("id")
                        
                        cuotas_ref, fuente = obtener_cuotas_evento_sofascore(evento_id)
                        
                        if cuotas_ref:
                            etiquetas = {
                                "1": f"Victoria {p_novi['local']}",
                                "X": "Empate",
                                "2": f"Victoria {p_novi['visita']}",
                                "O2.5": "Más de 2.5 Goles",
                                "U2.5": "Menos de 2.5 Goles"
                            }
                            
                            for k, c_novi in p_novi["cuotas"].items():
                                c_ref = cuotas_ref.get(k, 0)
                                if c_ref > 0 and c_novi >= (c_ref * UMBRAL_VALOR):
                                    diff = round(((c_novi / c_ref) - 1) * 100, 1)
                                    alerta_id = f"{nombre_novi}_{k}_{c_novi}"
                                    
                                    if alerta_id not in alertas_enviadas:
                                        msg = (
                                            f"🔥 <b>VALOR DETECTADO EN NOVIBET</b>\n\n"
                                            f"⚽ <b>Partido:</b> {nombre_novi}\n"
                                            f"🎯 <b>Apuesta:</b> {etiquetas.get(k, k)}\n\n"
                                            f"🟢 <b>Novibet:</b> {c_novi}\n"
                                            f"📊 <b>Ref ({fuente}):</b> {c_ref}\n"
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
