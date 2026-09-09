import os
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from flask import Flask

# Intentar importar la librería oficial de Google GenAI
try:
    from google import genai
    from google.genai import types
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False

app = Flask(__name__)

@app.route('/', methods=['HEAD', 'GET'])
def home():
    return "Bot de Momios Avanzado con Gemini y Estadísticas Recientes Activo"

# === CONFIGURACIÓN ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Memoria de control inteligente y seguimiento de cuotas
# Estructura: { "Nombre del Partido": {"previo_enviado": "...", "hoy_enviado": "...", "ultima_cuota_1": 2.10} }
historial_partidos = {}

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga"
]

# Horarios fijos (Hora Sinaloa)
HORARIOS_OBJETIVO = [
    (7, 0),   # 7:00 a.m.
    (12, 0),  # 12:00 p.m.
    (16, 30)  # 4:30 p.m.
]

UMBRAL_CAMBIO_BRUSCO = 0.10  # 10% de variación para alerta de volatilidad

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

def obtener_analisis_gemini(local, visita, liga_nombre):
    """Consulta a Gemini para obtener estadísticas de los últimos 5 partidos y radiografía táctica en curso."""
    if not GEMINI_DISPONIBLE or not GEMINI_API_KEY:
        return "<i>(Análisis de IA no disponible: Falta configurar GEMINI_API_KEY)</i>"
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Analiza el próximo partido de {liga_nombre}: {local} contra {visita}. "
            "IMPORTANTE: Basate estrictamente en el rendimiento y las estadísticas de los ÚLTIMOS 5 PARTIDOS RECIENTES "
            "de la temporada actual. Ignora por completo datos de temporadas pasadas. "
            "Proporciona en un formato muy breve y directo (máximo 4 líneas): "
            "1. Breve tendencia goleadora reciente de ambos. "
            "2. Un dato clave o inercia actual (ej. córners, tarjetas o momento de forma). "
            "3. Un veredicto táctico rápido para apuestas. "
            "Sé conciso y ve al grano."
        )
        
        # Usamos el modelo estándar con búsqueda web habilitada (Grounding) si está soportada
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.3,
            )
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"⚠️ Error consultando a Gemini para {local} vs {visita}: {e}", flush=True)
    
    return "<i>(No se pudo generar el análisis estadístico en este momento)</i>"

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
            return data
        else:
            print(f"⚠️ Error de API en {sport_key}: {r.text}", flush=True)
            return []
    except Exception as e:
        print(f"❌ Excepción consultando {sport_key}: {e}", flush=True)
        return []

def ejecutar_ciclo(es_prueba_inicial=False):
    global historial_partidos
    tipo_ciclo = "PRUEBA DE INICIO" if es_prueba_inicial else "PROGRAMADO"
    print(f"🚀 Ejecutando ciclo [{tipo_ciclo}]...", flush=True)
    
    tz = ZoneInfo("America/Mazatlan")
    hoy = datetime.now(tz).date()

    partidos_para_aviso_previo = []
    partidos_para_reporte_hoy = []
    alertas_volatilidad = []

    for sport_key in LIGAS:
        eventos = obtener_partidos_liga(sport_key)
        
        if eventos:
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

                dias_restantes = (fecha_partido - hoy).days
                if dias_restantes < 0:
                    continue

                # Procesar cuotas de mercado actuales
                bookmakers = evento.get("bookmakers", [])
                cuotas_mercado = { "1": [], "X": [], "2": [] }
                
                for book in bookmakers:
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
                                    
                            for k, v in precios.items():
                                if k in cuotas_mercado:
                                    cuotas_mercado[k].append(v)

                promedios_ref = {k: (sum(v)/len(v)) for k, v in cuotas_mercado.items() if v}
                p_1 = round(promedios_ref.get("1", 0), 2) if promedios_ref.get("1") else 0
                p_x = round(promedios_ref.get("X", 0), 2) if promedios_ref.get("X") else 0
                p_2 = round(promedios_ref.get("2", 0), 2) if promedios_ref.get("2") else 0

                url_sofascore = "https://www.sofascore.com"

                # Inicializar registro si es nuevo
                if nombre_partido not in historial_partidos:
                    historial_partidos[nombre_partido] = {
                        "previo_enviado": None, 
                        "hoy_enviado": None, 
                        "ultima_cuota_1": p_1
                    }

                registro = historial_partidos[nombre_partido]
                cuota_anterior = registro.get("ultima_cuota_1", p_1)

                # 1. CHEQUEO DE VOLATILIDAD (Cambios bruscos de momios)
                if not es_prueba_inicial and cuota_anterior > 0 and p_1 > 0:
                    cambio_porcentual = abs(p_1 - cuota_anterior) / cuota_anterior
                    if cambio_porcentual >= UMBRAL_CAMBIO_BRUSCO:
                        direccion = "📈 SUBIÓ" if p_1 > cuota_anterior else "📉 BAJÓ"
                        alertas_volatilidad.append(
                            f"⚠️ <b>¡MOVIMIENTO BRUSCO EN MOMIOS!</b>\n"
                            f"• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                            f"   ⏰ <b>Partido:</b> {hora_local_str}\n"
                            f"   📊 Cuota anterior: {cuota_anterior} ➔ Nueva: <b>{p_1}</b> ({direccion} {round(cambio_porcentual*100, 1)}%)\n"
                            f"   👉 <a href='{url_sofascore}'>Revisar en Sofascore</a>"
                        )
                        registro["ultima_cuota_1"] = p_1

                # 2. CASO A: ES EL MERO DÍA (Incluye análisis estadístico de IA)
                if dias_restantes == 0:
                    if registro["hoy_enviado"] != hoy or es_prueba_inicial:
                        print(f"🤖 Solicitando análisis estadístico a Gemini para {local} vs {visita}...", flush=True)
                        analisis_ia = obtener_analisis_gemini(local, visita, nombre_liga_limpio)
                        
                        partidos_para_reporte_hoy.append(
                            f"• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                            f"   ⏰ <b>Hora:</b> {hora_local_str} ⚡ <b>¡JUEGA HOY!</b>\n"
                            f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n\n"
                            f"   📈 <b>Radiografía Reciente (Últimos 5 juegos):</b>\n"
                            f"   {analisis_ia}\n\n"
                            f"   👉 <a href='{url_sofascore}'>Abrir Sofascore</a>"
                        )
                        registro["hoy_enviado"] = hoy

                # 3. CASO B: PARTIDO PRÓXIMO (1 a 4 días antes)
                elif 1 <= dias_restantes <= 4:
                    if not registro["previo_enviado"] or es_prueba_inicial:
                        partidos_para_aviso_previo.append(
                            f"📌 <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                            f"   📅 <b>Fecha:</b> {hora_local_str} (En {dias_restantes} días)\n"
                            f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n"
                            f"   👉 <a href='{url_sofascore}'>Abrir Sofascore</a>"
                        )
                        registro["previo_enviado"] = str(hoy)

                registro["ultima_cuota_1"] = p_1

        time.sleep(1)

    # ENVÍO DE REPORTES A TELEGRAM
    if alertas_volatilidad and not es_prueba_inicial:
        enviar_telegram("\n\n".join(alertas_volatilidad))

    if partidos_para_aviso_previo and not es_prueba_inicial:
        cuerpo_previo = "\n\n".join(partidos_para_aviso_previo[:5])
        enviar_telegram(f"🗓️ <b>AGENDA: PARTIDOS PRÓXIMOS</b>\n\n{cuerpo_previo}")

    if partidos_para_reporte_hoy:
        cuerpo_hoy = "\n\n".join(partidos_para_reporte_hoy)
        titulo_rep = "🧪 <b>REPORTE DE PRUEBA (IA + ESTADÍSTICAS)</b>" if es_prueba_inicial else f"📊 <b>REPORTE DEL DÍA</b>\n<i>Hora local Sinaloa: {datetime.now(tz).strftime('%H:%M')}</i>"
        enviar_telegram(f"{titulo_rep}\n\n{cuerpo_hoy}")
    elif es_prueba_inicial:
        enviar_telegram("ℹ️ <b>REPORTE DE PRUEBA:</b> Sistema sincronizado (7:00, 12:00, 16:30) con Gemini y estadísticas recientes activo.")

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
    print("🤖 Bot de Momios Avanzado inicializando hilo principal...", flush=True)
    tz = ZoneInfo("America/Mazatlan")
    
    try:
        ejecutar_ciclo(es_prueba_inicial=True)
    except Exception as e:
        print(f"❌ Error en la prueba inicial: {e}", flush=True)

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
    app.run(0.0.0.0, port=port)
