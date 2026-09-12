import os
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from flask import Flask

try:
    from google import genai
    from google.genai import types
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False

app = Flask(__name__)

@app.route('/', methods=['HEAD', 'GET'])
def home():
    return "Bot de Momios Avanzado con Control de Cuotas y Límites Activo"

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

historial_partidos = {}

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_netherlands_eredivisie"
]

HORARIOS_OBJETIVO = [
    (7, 0),   # 7:00 a.m.
    (12, 0),  # 12:00 p.m.
    (16, 30)  # 4:30 p.m.
]

UMBRAL_CAMBIO_BRUSCO = 0.10

EQUIPOS_TOP = [
    "barcelona", "real madrid", "atletico madrid", "atlético de madrid",
    "manchester city", "arsenal", "liverpool", "manchester united", "chelsea", "tottenham",
    "bayern munich", "bayern münchen", "borussia dortmund", "leverkusen",
    "juventus", "inter", "ac milan", "napoli", "roma", "atalanta",
    "psg", "ajax", "psv", "feyenoord",
    "america", "américa", "chivas", "cruz azul", "pumas", "tigres", "rayados", "monterrey"
]

def es_equipo_top(local, visita):
    texto = f"{local} {visita}".lower()
    return any(top in texto for top in EQUIPOS_TOP)

def enviar_telegram(mensaje):
    if not TOKEN:
        print("❌ ERROR: TELEGRAM_TOKEN no está configurado.", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}", flush=True)
        return False

def obtener_analisis_gemini(local, visita, liga_nombre):
    """Consulta a Gemini con manejo de pausas para evitar errores 429."""
    if not GEMINI_DISPONIBLE or not GEMINI_API_KEY:
        return "<i>(Análisis de IA no disponible: Falta configurar GEMINI_API_KEY)</i>"
    
    prompt = (
        f"Analiza el siguiente partido de {liga_nombre}: {local} contra {visita}. "
        "Basate estrictamente en el rendimiento y las estadísticas de los ÚLTIMOS 5 PARTIDOS RECIENTES. "
        "Proporciona en un formato muy breve y directo (máximo 3 líneas): "
        "1. Tendencia goleadora reciente. "
        "2. Patrón o dato clave para apuesta. "
        "3. Veredicto rápido."
    )
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        # Pausa de cortesía para respetar los límites gratuitos de la API por minuto
        time.sleep(5)
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"⚠️ Límite de IA alcanzado o error en {local} vs {visita}: {e}", flush=True)
        time.sleep(10) # Pausa larga si salta el error
        
    return "<i>(Análisis omitido temporalmente por protección de cuota de la API)</i>"

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        return []
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us,uk&markets=h2h&oddsFormat=decimal"
    try:
        r = requests.get(target_url, timeout=15)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception:
        return []

def ejecutar_ciclo(es_prueba_inicial=False):
    global historial_partidos
    tipo_ciclo = "PRUEBA DE INICIO" if es_prueba_inicial else "PROGRAMADO"
    print(f"🚀 Ejecutando ciclo [{tipo_ciclo}] con control inteligente de cuota...", flush=True)
    
    tz = ZoneInfo("America/Mazatlan")
    ahora_local = datetime.now(tz)
    hoy = ahora_local.date()

    partidos_para_reporte_hoy = []
    partidos_para_aviso_previo = []
    alertas_volatilidad = []

    # Contador para gastar IA con moderación en el plan gratuito (máximo 4 llamadas por ejecución)
    llamadas_ia_realizadas = 0
    LIMITE_IA_POR_CICLO = 3

    for sport_key in LIGAS:
        eventos = obtener_partidos_liga(sport_key)
        if not eventos:
            continue
            
        nombre_liga_limpio = sport_key.replace("soccer_", "").replace("_", " ").title()

        for evento in eventos:
            local = evento.get("home_team")
            visita = evento.get("away_team")
            nombre_partido = f"{local} vs {visita}"
            commence_time_str = evento.get("commence_time", "")
            
            try:
                dt_utc = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone(tz)
                fecha_partido = dt_local.date()
                hora_local_str = dt_local.strftime("%H:%M hrs (%d/%b)")
            except Exception:
                continue

            if dt_local <= ahora_local:
                continue

            dias_restantes = (fecha_partido - hoy).days
            if dias_restantes < 0:
                continue

            bookmakers = evento.get("bookmakers", [])
            cuotas_mercado = { "1": [], "X": [], "2": [] }
            
            for book in bookmakers:
                for m in book.get("markets", []):
                    if m.get("key") == "h2h":
                        precios = {}
                        for out in m.get("outcomes", []):
                            name = out.get("name")
                            price = out.get("price")
                            if name == local:
                                precios["1"] = float(price)
                            elif name == visita:
                                precios["2"] = float(price)
                            else:
                                precios["X"] = float(price)
                        for k, v in precios.items():
                            if k in cuotas_mercado:
                                cuotas_mercado[k].append(v)

            promedios_ref = {k: (sum(v)/len(v)) for k, v in cuotas_mercado.items() if v}
            p_1 = round(promedios_ref.get("1", 0), 2) if promedios_ref.get("1") else 0
            p_x = round(promedios_ref.get("X", 0), 2) if promedios_ref.get("X") else 0
            p_2 = round(promedios_ref.get("2", 0), 2) if promedios_ref.get("2") else 0

            url_sofascore = "https://www.sofascore.com"

            if nombre_partido not in historial_partidos:
                historial_partidos[nombre_partido] = {
                    "previo_enviado": None, 
                    "hoy_enviado": None, 
                    "ultima_cuota_1": p_1
                }

            registro = historial_partidos[nombre_partido]
            is_top = es_equipo_top(local, visita)

            # Decidir si consultamos a la IA (Solo si es Top o si tenemos cupo disponible)
            analisis_ia = "<i>(Momios analizados por mercado - IA reservada para partidos clave)</i>"
            if (is_top or dias_restantes == 0) and llamadas_ia_realizadas < LIMITE_IA_POR_CICLO:
                print(f"🤖 Consultando IA para: {local} vs {visita}...", flush=True)
                analisis_ia = obtener_analisis_gemini(local, visita, nombre_liga_limpio)
                llamadas_ia_realizadas += 1

            # REPORTE DE HOY
            if dias_restantes == 0:
                if registro["hoy_enviado"] != hoy or es_prueba_inicial:
                    etiqueta = "⭐ <b>[DESTACADO / EQUIPO TOP]</b>\n" if is_top else "⚽ "
                    partidos_para_reporte_hoy.append(
                        f"{etiqueta}• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                        f"   ⏰ <b>Hora:</b> {hora_local_str} ⚡ <b>¡JUEGA HOY!</b>\n"
                        f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n\n"
                        f"   📈 <b>Radiografía / Patrón:</b>\n"
                        f"   {analisis_ia}\n\n"
                        f"   👉 <a href='{url_sofascore}'>Abrir Sofascore</a>"
                    )
                    registro["hoy_enviado"] = hoy

            # PRÓXIMOS PARTIDOS
            elif 1 <= dias_restantes <= 5:
                if not registro["previo_enviado"] or es_prueba_inicial:
                    etiqueta = "⭐ " if is_top else "📌 "
                    partidos_para_aviso_previo.append(
                        f"{etiqueta}<b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                        f"   📅 <b>Fecha:</b> {hora_local_str} (En {dias_restantes} días)\n"
                        f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n\n"
                        f"   👉 <a href='{url_sofascore}'>Abrir Sofascore</a>"
                    )
                    registro["previo_enviado"] = str(hoy)

            registro["ultima_cuota_1"] = p_1

    cuerpo_mensaje_total = []

    if partidos_para_reporte_hoy:
        cuerpo_mensaje_total.append("🔥 <b>PARTIDOS DE HOY</b>\n\n" + "\n\n".join(partidos_para_reporte_hoy))

    if partidos_para_aviso_previo:
        cuerpo_previo = "\n\n".join(partidos_para_aviso_previo[:4])
        cuerpo_mensaje_total.append("🗓️ <b>PRÓXIMOS ENCUENTROS</b>\n\n" + cuerpo_previo)

    if cuerpo_mensaje_total and not es_prueba_inicial:
        titulo_rep = f"📊 <b>REPORTE DEL DÍA</b>\n<i>Hora local Sinaloa: {ahora_local.strftime('%H:%M')}</i>"
        enviar_telegram(f"{titulo_rep}\n\n" + "\n\n━━━━━━━━━━━━━━━\n\n".join(cuerpo_mensaje_total))
    elif es_prueba_inicial:
        cuerpo_prueba = "\n\n━━━━━━━━━━━━━━━\n\n".join(cuerpo_mensaje_total) if cuerpo_mensaje_total else "ℹ️ <i>No hay partidos detectados en el rango actual.</i>"
        enviar_telegram(f"🧪 <b>REPORTE DE PRUEBA (CONTROL DE CUOTAS ACTIVO)</b>\n\n{cuerpo_prueba}")

def obtener_siguiente_ejecucion(tz):
    ahora = datetime.now(tz)
    candidatos = []
    for h, m in HORARIOS_OBJETIVO:
        objetivo_hoy = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if objetivo_hoy > ahora:
            candidatos.append(objetivo_hoy)
        candidatos.append(objetivo_hoy + timedelta(days=1))
    return min(candidatos)

def monitorear():
    print("🤖 Bot de Momios Avanzado inicializando hilo principal...", flush=True)
    tz = ZoneInfo("America/Mazatlan")
    
    try:
        ejecutar_ciclo(es_prueba_inicial=True)
    except Exception as e:
        print(f"❌ Error crítico en la prueba inicial: {e}", flush=True)

    while True:
        ahora = datetime.now(tz)
        siguiente_objetivo = obtener_siguiente_ejecucion(tz)
        segundos_espera = (siguiente_objetivo - ahora).total_seconds()
        
        print(f"⏳ Durmiendo hasta las {siguiente_objetivo.strftime('%H:%M')}...", flush=True)
        time.sleep(segundos_espera)
        
        print(f"🌅 Ejecutando escaneo programado...", flush=True)
        try:
            ejecutar_ciclo(es_prueba_inicial=False)
        except Exception as e:
            print(f"❌ Error crítico en ciclo programado: {e}", flush=True)

hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run("0.0.0.0", port=port)
