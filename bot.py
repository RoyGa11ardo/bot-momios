import os
import time
import threading
import requests
from flask import Flask
from rapidfuzz import process, fuzz
from curl_cffi import requests as crequests

app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Bot de Momios + Contexto Avanzado Novibet vs SofaScore activo 24/7"

# === CONFIGURACIÓN DE TELEGRAM ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")

UMBRAL_VALOR = 1.05 
alertas_enviadas = set()

# Crear sesión persistente para mantener cookies
session = crequests.Session()

HEADERS_GENERICOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

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

# === 1. EXTRAER EVENTOS Y MERCADOS DE NOVIBET ===
def obtener_eventos_novibet():
    url = "https://www.novibet.mx/api/sports/v1/events/highlights"
    headers = HEADERS_GENERICOS.copy()
    headers["Accept"] = "application/json, text/plain, */*"
    headers["Referer"] = "https://www.novibet.mx/"
    
    try:
        r = session.get(url, headers=headers, impersonate="chrome110", timeout=15)
        print(f"DEBUG Novibet Status: {r.status_code}", flush=True)
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                print("⚠️ Novibet devolvió 200 pero el contenido es HTML/Anti-Bot.", flush=True)
                return []
                
            events = data.get("events", [])
            print(f"DEBUG Novibet Events encontrados: {len(events)}", flush=True)
            
            partidos = []
            for ev in events:
                local = ev.get("homeTeam", {}).get("name")
                visita = ev.get("awayTeam", {}).get("name")
                
                markets = ev.get("markets", [])
                cuotas = {}
                
                for market in markets:
                    m_name = market.get("header", "").lower()
                    outcomes = market.get("outcomes", [])
                    
                    if "resultado" in m_name or "1x2" in m_name or "ganador" in m_name:
                        if len(outcomes) >= 3:
                            cuotas["1"] = float(outcomes[0].get("price", 0))
                            cuotas["X"] = float(outcomes[1].get("price", 0))
                            cuotas["2"] = float(outcomes[2].get("price", 0))
                        elif len(outcomes) == 2:
                            cuotas["1"] = float(outcomes[0].get("price", 0))
                            cuotas["2"] = float(outcomes[2].get("price", 0))
                    
                    if "total" in m_name or "goles" in m_name or "over" in m_name:
                        for out in outcomes:
                            desc = out.get("caption", "").lower()
                            if "más" in desc or "over" in desc or "> 2.5" in desc:
                                cuotas["O2.5"] = float(out.get("price", 0))
                            elif "menos" in desc or "under" in desc or "< 2.5" in desc:
                                cuotas["U2.5"] = float(out.get("price", 0))

                if local and visita and cuotas:
                    partidos.append({
                        "local": local,
                        "visita": visita,
                        "cuotas": cuotas
                    })
            return partidos
        else:
            print(f"⚠️ Novibet respondió con código HTTP: {r.status_code}", flush=True)
        return []
    except Exception as e:
        print(f"Error al consultar Novibet: {e}", flush=True)
        return []

# === 2. EXTRAER PARTIDOS DE SOFASCORE ===
def obtener_partidos_sofascore():
    fecha_hoy = time.strftime("%Y-%m-%d")
    url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha_hoy}"
    
    headers = HEADERS_GENERICOS.copy()
    headers["Referer"] = "https://www.sofascore.com/"
    headers["Origin"] = "https://www.sofascore.com"
    
    try:
        # Visitar primero la home para simular navegación y obtener cookies de Cloudflare
        session.get("https://www.sofascore.com/", headers=HEADERS_GENERICOS, impersonate="chrome110", timeout=10)
        time.sleep(1)
        
        r = session.get(url, headers=headers, impersonate="chrome110", timeout=15)
        print(f"DEBUG SofaScore Status: {r.status_code}", flush=True)
        if r.status_code == 200:
            data = r.json()
            events = data.get("events", [])
            print(f"DEBUG SofaScore Events encontrados para {fecha_hoy}: {len(events)}", flush=True)
            return events
        else:
            print(f"⚠️ SofaScore respondió con código HTTP: {r.status_code}", flush=True)
        return []
    except Exception as e:
        print(f"Error al consultar SofaScore: {e}", flush=True)
        return []

# === 3. EXTRAER CUOTAS DE SOFASCORE ===
def obtener_cuotas_evento_sofascore(evento_id):
    url = f"https://api.sofascore.com/api/v1/event/{evento_id}/odds/1/all"
    headers = HEADERS_GENERICOS.copy()
    headers["Referer"] = f"https://www.sofascore.com/event/{evento_id}"
    
    try:
        r = session.get(url, headers=headers, impersonate="chrome110", timeout=10)
        if r.status_code == 200:
            markets = r.json().get("markets", [])
            cuotas_ref = {}
            fuente = "SofaScore (Mercado Global)"
            
            for market in markets:
                m_name = market.get("marketName", "")
                
                if m_name in ["Full time", "1X2", "Match odds"]:
                    for provider in market.get("providers", []):
                        nombre_casa = provider.get("bookmaker", {}).get("name", "").lower()
                        choices = provider.get("choices", [])
                        
                        if len(choices) >= 2:
                            c1 = float(choices[0].get("initialDecimalValue", choices[0].get("decimalValue", 0)))
                            c2 = float(choices[-1].get("initialDecimalValue", choices[-1].get("decimalValue", 0)))
                            cx = float(choices[1].get("initialDecimalValue", choices[1].get("decimalValue", 0))) if len(choices) == 3 else 0
                            
                            if "draftea" in nombre_casa:
                                fuente = "Draftea"
                                cuotas_ref["1"] = c1
                                cuotas_ref["2"] = c2
                                if cx > 0: cuotas_ref["X"] = cx
                                break
                            elif "1" not in cuotas_ref:
                                cuotas_ref["1"] = c1
                                cuotas_ref["2"] = c2
                                if cx > 0: cuotas_ref["X"] = cx

            return cuotas_ref, fuente
        return {}, ""
    except Exception as e:
        print(f"Error extrayendo cuotas de SofaScore {evento_id}: {e}")
        return {}, ""

# === 4. EXTRAER INFORMACIÓN CONTEXTUAL ===
def obtener_info_extra_sofascore(evento_id):
    texto_extra = ""
    headers = HEADERS_GENERICOS.copy()
    headers["Referer"] = f"https://www.sofascore.com/event/{evento_id}"
    
    try:
        url_referee = f"https://api.sofascore.com/api/v1/event/{evento_id}"
        r = session.get(url_referee, headers=headers, impersonate="chrome110", timeout=5)
        if r.status_code == 200:
            event_data = r.json().get("event", {})
            referee = event_data.get("referee", {})
            if referee:
                nombre_ref = referee.get("name", "N/D")
                yellow_cards = referee.get("yellowCards", 0)
                games = referee.get("games", 0)
                
                if games > 0:
                    prom_yellow = round(yellow_cards / games, 1)
                    texto_extra += f"\n\n👨‍⚖️ <b>Árbitro (Temporada Actual):</b>\n• {nombre_ref} ({prom_yellow} amarillas/partido en {games} PJ)"
                else:
                    texto_extra += f"\n\n👨‍⚖️ <b>Árbitro:</b> {nombre_ref}"
    except Exception as e:
        print(f"Error consultando árbitro: {e}")

    try:
        url_incidents = f"https://api.sofascore.com/api/v1/event/{evento_id}/lineups"
        r = session.get(url_incidents, headers=headers, impersonate="chrome110", timeout=5)
        if r.status_code == 200:
            data = r.json()
            missing_home = data.get("home", {}).get("missingPlayers", [])
            missing_away = data.get("away", {}).get("missingPlayers", [])
            
            bajas = []
            for p in missing_home[:2]:
                bajas.append(f"• (Local) {p.get('player', {}).get('name')}: {p.get('reason', 'Ausente')}")
            for p in missing_away[:2]:
                bajas.append(f"• (Visita) {p.get('player', {}).get('name')}: {p.get('reason', 'Ausente')}")
                
            if bajas:
                texto_extra += "\n\n🚑 <b>Bajas Confirmadas / Dudas:</b>\n" + "\n".join(bajas)
    except Exception as e:
        print(f"Error consultando bajas: {e}")

    try:
        url_streaks = f"https://api.sofascore.com/api/v1/event/{evento_id}/streaks"
        r = session.get(url_streaks, headers=headers, impersonate="chrome110", timeout=5)
        if r.status_code == 200:
            data = r.json()
            general_streaks = data.get("general", [])
            
            lineas_locales = []
            lineas_generales = []
            
            for s in general_streaks:
                nombre_streak = s.get("name", "").lower()
                val = s.get("value", "")
                
                if any(k in nombre_streak for k in ["home", "away", "casa", "visitante"]):
                    lineas_locales.append(f"• {s.get('name')}: {val}")
                else:
                    lineas_generales.append(f"• {s.get('name')}: {val}")
            
            if lineas_locales:
                texto_extra += "\n\n🏟️ <b>Métricas Específicas (Local/Visitante):</b>\n" + "\n".join(lineas_locales[:3])
            
            if lineas_generales:
                texto_extra += "\n\n📊 <b>Dato / Racha Clave:</b>\n" + "\n".join(lineas_generales[:3])
    except Exception as e:
        print(f"Error consultando rachas: {e}")

    try:
        url_h2h = f"https://api.sofascore.com/api/v1/event/{evento_id}/h2h/events"
        r = session.get(url_h2h, headers=headers, impersonate="chrome110", timeout=5)
        if r.status_code == 200:
            h2h_events = r.json().get("events", [])
            if h2h_events:
                lineas_h2h = []
                for ev in h2h_events[:5]:
                    home_team = ev.get("homeTeam", {}).get("name")
                    away_team = ev.get("awayTeam", {}).get("name")
                    home_score = ev.get("homeScore", {}).get("current", 0)
                    away_score = ev.get("awayScore", {}).get("current", 0)
                    lineas_h2h.append(f"• {home_team} {home_score} - {away_score} {away_team}")
                
                texto_extra += "\n\n🥊 <b>Últimos 5 Enfrentamientos Directos (H2H):</b>\n" + "\n".join(lineas_h2h)
    except Exception as e:
        print(f"Error consultando H2H: {e}")

    try:
        url_lineups = f"https://api.sofascore.com/api/v1/event/{evento_id}/lineups"
        r = session.get(url_lineups, headers=headers, impersonate="chrome110", timeout=5)
        if r.status_code == 200:
            data = r.json()
            confirmed = data.get("confirmed", False)
            home_formation = data.get("home", {}).get("formation", "N/D")
            away_formation = data.get("away", {}).get("formation", "N/D")
            
            estado_ali = "Confirmadas" if confirmed else "Por confirmar"
            texto_extra += (
                f"\n\n📋 <b>Alineaciones ({estado_ali}):</b>\n"
                f"• Esquema Táctico: {home_formation} vs {away_formation}"
            )
    except Exception as e:
        print(f"Error consultando alineaciones: {e}")
        
    return texto_extra

# === 5. CICLO DE MONITOREO ===
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
                                        info_extra = obtener_info_extra_sofascore(evento_id)
                                        
                                        msg = (
                                            f"🔥 <b>VALOR DETECTADO EN NOVIBET</b>\n\n"
                                            f"⚽ <b>Partido:</b> {nombre_novi}\n"
                                            f"🎯 <b>Apuesta:</b> {etiquetas.get(k, k)}\n\n"
                                            f"🟢 <b>Novibet:</b> {c_novi}\n"
                                            f"📊 <b>Ref ({fuente}):</b> {c_ref}\n"
                                            f"📈 <b>Ventaja:</b> +{diff}%"
                                            f"{info_extra}"
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
