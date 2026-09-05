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
    return "Bot de Momios (Horarios Personalizados) activo 24/7"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

# Umbral de valor para alertas prioritarias (+5%)
UMBRAL_VALOR = 1.05 
alertas_enviadas = set()

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga"
]

# Horarios exactos del día en formato (hora, minuto)
HORARIOS_OBJETIVO = [
    (7, 0),   # 7:00 a.m.
    (11, 30), # 11:30 a.m.
    (15, 0),  # 3:00 p.m.
    (18, 0)   # 6:00 p.m.
]

def enviar_telegram(mensaje):
    if not TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except:
        return False

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        print("⚠️ Falta configurar THE_ODDS_API_KEY.", flush=True)
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
    partidos_para_reporte = []

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
                            else:
                                for k, v in precios.items():
                                    if k not in cuotas_mercado:
                                        cuotas_mercado[k] = []
                                    cuotas_mercado[k].append(v)

                # 1. EVALUAR ALERTA DE VALOR (+5%)
                if novibet_cuotas and cuotas_mercado:
                    promedios_ref = {k: sum(v)/len(v) for k, v in cuotas_mercado.items() if v}
                    etiquetas = {"1": f"Victoria {local}", "X": "Empate", "2": f"Victoria {visita}"}
                    
                    for k, c_novi in novibet_cuotas.items():
                        c_ref = promedios_ref.get(k, 0)
                        if c_ref > 0 and c_novi >= (c_ref * UMBRAL_VALOR):
                            diff = round(((c_novi / c_ref) - 1) * 100, 1)
                            alerta_id = f"{nombre_partido}_{k}_{c_novi}"
                            
                            if alerta_id not in alertas_enviadas:
                                query_busqueda = f"site:sofascore.com {local} {visita}".replace(" ", "+")
                                url_stats = f"https://www.google.com/search?q={query_busqueda}"

                                msg = (
                                    f"🔥 <b>¡VALOR DETECTADO EN NOVIBET!</b>\n\n"
                                    f"⚽ <b>Partido:</b> {nombre_partido}\n"
                                    f"🎯 <b>Apuesta:</b> {etiquetas.get(k, k)}\n\n"
                                    f"🟢 <b>Novibet:</b> {c_novi}\n"
                                    f"📊 <b>Mercado:</b> {round(c_ref, 2)}\n"
                                    f"📈 <b>Ventaja:</b> +{diff}%\n\n"
                                    f"📋 <b>Análisis:</b>\n"
                                    f"<a href='{url_stats}'>👉 Ver rachas y estadísticas en Sofascore</a>"
                                )
                                enviar_telegram(msg)
                                alertas_enviadas.add(alerta_id)

                # 2. RECOPILAR DATOS PARA EL REPORTE PERIÓDICO
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

        time.sleep(2)

    # ENVIAR REPORTE DE CARTELERA DEL CICLO
    if partidos_para_reporte:
        cuerpo_reporte = "\n\n".join(partidos_para_reporte)
        reporte_msg = (
            f"📊 <b>REPORTE DE CARTELERA (CICLO)</b>\n"
            f"<i>Partidos clave analizados en este bloque:</i>\n\n"
            f"{cuerpo_reporte}"
        )
        enviar_telegram(reporte_msg)

    print(f"🔍 [Revisión Completa] Partidos analizados: {total_eventos}.", flush=True)

def obtener_siguiente_ejecucion(tz):
    ahora = datetime.now(tz)
    candidatos = []
    
    for h, m in HORARIOS_OBJETIVO:
        # Probamos el horario para hoy
        objetivo_hoy = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if objetivo_hoy > ahora:
            candidatos.append(objetivo_hoy)
        
        # Probamos también sumándole un día (para los horarios que ya pasaron hoy)
        objetivo_mañana = objetivo_hoy + timedelta(days=1)
        candidatos.append(objetivo_mañana)
        
    # Nos quedamos con el candidato más cercano en el tiempo
    siguiente = min(candidatos)
    return siguiente

def monitorear():
    print("🤖 Bot inicializando con horarios personalizados...", flush=True)
    tz = ZoneInfo("America/Mazatlan")
    
    enviar_telegram("💤 <b>Bot actualizado</b> (Horarios: 7:00, 11:30, 15:00 y 18:00). Calculando siguiente ciclo...")
    
    while True:
        ahora = datetime.now(tz)
        siguiente_objetivo = obtener_siguiente_ejecucion(tz)
        
        segundos_espera = (siguiente_objetivo - ahora).total_seconds()
        horas_espera = round(segundos_espera / 3600, 2)
        
        print(f"⏳ Son las {ahora.strftime('%H:%M:%S')}. Durmiendo {horas_espera} horas hasta las {siguiente_objetivo.strftime('%H:%M')}...", flush=True)
        
        # Dormimos exactamente los segundos que faltan para el próximo objetivo
        time.sleep(segundos_espera)
        
        # Al despertar, ejecutamos el ciclo
        print(f"🌅 Ejecutando escaneo programado a las {datetime.now(tz).strftime('%H:%M:%S')}...", flush=True)
        ejecutar_ciclo()
        print("💤 Ciclo finalizado.", flush=True)

hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
