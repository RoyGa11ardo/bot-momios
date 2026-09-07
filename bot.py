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
    return "Bot de Momios Operativo y Sincronizado"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

UMBRAL_VALOR = 1.05  # +5% de valor
alertas_enviadas = set()

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga"
]

HORARIOS_OBJETIVO = [
    (7, 0),   # 7:00 a.m.
    (11, 30), # 11:30 a.m.
    (15, 0),  # 3:00 p.m.
    (18, 0)   # 6:00 p.m.
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

def ejecutar_ciclo(es_prueba_inicial=False):
    tipo_ciclo = "PRUEBA DE INICIO" if es_prueba_inicial else "PROGRAMADO"
    print(f"🚀 Ejecutando ciclo [{tipo_ciclo}]...", flush=True)
    
    total_eventos = 0
    partidos_para_reporte = []
    tz = ZoneInfo("America/Mazatlan")

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
                cuotas_mercado = { "1": [], "X": [], "2": [] }
                draftkings_cuotas = {}
                pinnacle_cuotas = {}
                
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
                                    
                            if book_key == "draftkings":
                                draftkings_cuotas = precios
                            elif book_key == "pinnacle":
                                pinnacle_cuotas = precios
                            
                            for k, v in precios.items():
                                if k in cuotas_mercado:
                                    cuotas_mercado[k].append(v)

                # Calcular promedios de referencia del mercado
                promedios_ref = {k: (sum(v)/len(v)) for k, v in cuotas_mercado.items() if v}
                
                # 1. EVALUAR VALOR EN DRAFTKINGS (+5% vs Promedio o Pinnacle)
                if draftkings_cuotas:
                    etiquetas = {"1": f"Victoria {local}", "X": "Empate", "2": f"Victoria {visita}"}
                    ref_base = pinnacle_cuotas if pinnacle_cuotas else promedios_ref
                    
                    for k, c_dk in draftkings_cuotas.items():
                        c_ref = ref_base.get(k, 0)
                        if c_ref > 0 and c_dk >= (c_ref * UMBRAL_VALOR):
                            diff = round(((c_dk / c_ref) - 1) * 100, 1)
                            alerta_id = f"{nombre_partido}_{k}_{c_dk}"
                            
                            if alerta_id not in alertas_enviadas:
                                query_busqueda = f"site:sofascore.com {local} {visita}".replace(" ", "+")
                                url_stats = f"https://www.google.com/search?q={query_busqueda}"

                                msg = (
                                    f"🔥 <b>¡VALOR DETECTADO EN DRAFTKINGS!</b>\n\n"
                                    f"⚽ <b>Partido:</b> {nombre_partido}\n"
                                    f"🎯 <b>Apuesta:</b> {etiquetas.get(k, k)}\n\n"
                                    f"🟢 <b>DraftKings:</b> {c_dk}\n"
                                    f"📊 <b>Referencia Mercado/Pinnacle:</b> {round(c_ref, 2)}\n"
                                    f"📈 <b>Ventaja:</b> +{diff}%\n\n"
                                    f"📋 <b>Análisis:</b>\n"
                                    f"<a href='{url_stats}'>👉 Ver rachas y estadísticas en Sofascore</a>"
                                )
                                enviar_telegram(msg)
                                alertas_enviadas.add(alerta_id)

                # 2. RECOPILAR DATOS PARA EL REPORTE DE CARTELERA
                if len(partidos_para_reporte) < 6:
                    query_busqueda = f"site:sofascore.com {local} {visita}".replace(" ", "+")
                    url_stats = f"https://www.google.com/search?q={query_busqueda}"
                    
                    p_1 = round(promedios_ref.get("1", 0), 2) if promedios_ref.get("1") else "-"
                    p_x = round(promedios_ref.get("X", 0), 2) if promedios_ref.get("X") else "-"
                    p_2 = round(promedios_ref.get("2", 0), 2) if promedios_ref.get("2") else "-"

                    partidos_para_reporte.append(
                        f"• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                        f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n"
                        f"   👉 <a href='{url_stats}'>Ver estadísticas en Sofascore</a>"
                    )

        time.sleep(1)

    print(f"📊 [Resumen Ciclo] Total eventos procesados: {total_eventos}", flush=True)

    # ENVIAR REPORTE
    if partidos_para_reporte:
        cuerpo_reporte = "\n\n".join(partidos_para_reporte)
        titulo_rep = "🧪 <b>REPORTE DE PRUEBA (ARRANQUE)</b>" if es_prueba_inicial else f"📊 <b>REPORTE DE CARTELERA</b>\n<i>Hora local Sinaloa: {datetime.now(tz).strftime('%H:%M')}</i>"
        
        reporte_msg = f"{titulo_rep}\n\n{cuerpo_reporte}"
        enviar_telegram(reporte_msg)

def obtener_siguiente_ejecucion(tz):
    ahora = datetime.now(tz)
    candidatos = []
    
    for h, m in HORARIOS_OBJETIVO:
        objetivo_hoy = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if objetivo_hoy > ahora:
            candidatos.append(objetivo_hoy)
        
        objetivo_mañana = objetivo_hoy + timedelta(days=1)
        candidatos.append(objetivo_mañana)
        
    return min(candidatos)

def monitorear():
    print("🤖 Bot de Momios inicializando hilo principal...", flush=True)
    tz = ZoneInfo("America/Mazatlan")
    
    # 1. Ejecutar prueba inmediata al arrancar para verificar Telegram
    try:
        ejecutar_ciclo(es_prueba_inicial=True)
    except Exception as e:
        print(f"❌ Error en la prueba inicial: {e}", flush=True)

    # 2. Entrar en bucle de horarios establecidos
    while True:
        ahora = datetime.now(tz)
        siguiente_objetivo = obtener_siguiente_ejecucion(tz)
        
        segundos_espera = (siguiente_objetivo - ahora).total_seconds()
        horas_espera = round(segundos_espera / 3600, 2)
        
        print(f"⏳ Hora local actual: {ahora.strftime('%H:%M:%S')}. Durmiendo {horas_espera} horas hasta las {siguiente_objetivo.strftime('%H:%M')}...", flush=True)
        
        time.sleep(segundos_espera)
        
        print(f"🌅 Ejecutando escaneo programado a las {datetime.now(tz).strftime('%H:%M:%S')}...", flush=True)
        try:
            ejecutar_ciclo(es_prueba_inicial=False)
        except Exception as e:
            print(f"❌ Error en ciclo programado: {e}", flush=True)
        print("💤 Ciclo finalizado.", flush=True)

hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
