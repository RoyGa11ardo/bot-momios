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
    return "Bot de Momios Avanzado con Análisis Amplio y Patrones Activo"

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

# Lista de referencia para darles prioridad visual (estrellita), pero NO exclusiva
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
        print(f"📱 Telegram Status: {r.status_code}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}", flush=True)
        return False

def obtener_analisis_gemini(local, visita, liga_nombre):
    """Consulta a Gemini utilizando el modelo oficial actual gemini-3.6-flash."""
    if not GEMINI_DISPONIBLE or not GEMINI_API_KEY:
        return "<i>(Análisis de IA no disponible: Falta configurar GEMINI_API_KEY)</i>"
    
    prompt = (
        f"Analiza el siguiente partido de {liga_nombre}: {local} contra {visita}. "
        "IMPORTANTE: Basate estrictamente en el rendimiento y las estadísticas de los ÚLTIMOS 5 PARTIDOS RECIENTES "
        "de la temporada actual. Ignora por completo datos de temporadas pasadas. "
        "Proporciona en un formato muy breve y directo (máximo 4 líneas): "
        "1. Breve tendencia goleadora reciente de ambos. "
        "2. Un patrón claro o dato clave que indique si hay una apuesta segura (ej. dominio de posesión, inercia clara o rachas). "
        "3. Un veredicto táctico rápido y conservador. "
        "Sé conciso y ve al grano."
    )
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
            )
        )
        if response and response.text:
            print(f"✅ Éxito consultando Gemini para {local} vs {visita}", flush=True)
            return response.text.strip()
    except Exception as e:
        print(f"⚠️ Error consultando Gemini para {local} vs {visita}: {e}", flush=True)
        
    return "<i>(Análisis estadístico temporalmente no disponible, pero momios activos)</i>"

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        print("❌ ERROR: THE_ODDS_API_KEY está vacía.", flush=True)
        return []
    
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us,uk&markets=h2h&oddsFormat=decimal"
    
    try:
        r = requests.get(target_url, timeout=15)
        print(f"🔍 API Response [{sport_key}] -> Status: {r.status_code}", flush=True)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"⚠️ Error de API en {sport_key}: {r.text}", flush=True)
            return []
    except Exception as e:
        print(f"❌ Excepción consultando {sport_key}: {e}", flush=True)
        return []

def ejecutar_ciclo(es_prueba_inicial=False):
    global historial_partidos
    tipo_ciclo = "PRUEBA DE INICIO" if es_prueba_inicial else "PROGRAMADO"
    print(f"🚀 Ejecutando ciclo [{tipo_ciclo}] analizando todas las opciones...", flush=True)
    
    tz = ZoneInfo("America/Mazatlan")
    ahora_local = datetime.now(tz)
    hoy = ahora_local.date()

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
                cuota_anterior = registro.get("ultima_cuota_1", p_1)
                is_top = es_equipo_top(local, visita)

                # Alerta de volatilidad para CUALQUIER partido con movimiento fuerte
                if not es_prueba_inicial and cuota_anterior > 0 and p_1 > 0:
                    cambio_porcentual = abs(p_1 - cuota_anterior) / cuota_anterior
                    if cambio_porcentual >= UMBRAL_CAMBIO_BRUSCO:
                        direccion = "📈 SUBIÓ" if p_1 > cuota_anterior else "📉 BAJÓ"
                        print(f"🤖 Solicitando contexto a Gemini por cambio brusco en {local} vs {visita}...", flush=True)
                        contexto_ia = obtener_analisis_gemini(local, visita, nombre_liga_limpio)
                        
                        etiqueta_alerta = "⭐ <b>¡MOVIMIENTO EN EQUIPO TOP!</b>" if is_top else "⚠️ <b>¡MOVIMIENTO BRUSCO EN MOMIOS!</b>"
                        alertas_volatilidad.append(
                            f"{etiqueta_alerta}\n"
                            f"• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                            f"   ⏰ <b>Partido:</b> {hora_local_str}\n"
                            f"   📊 <b>Cuota Local ({local}):</b> {cuota_anterior} ➔ <b>{p_1}</b> ({direccion} {round(cambio_porcentual*100, 1)}%)\n\n"
                            f"   🧠 <b>Contexto de la IA sobre el cambio:</b>\n"
                            f"   {contexto_ia}\n\n"
                            f"   👉 <a href='{url_sofascore}'>Revisar en Sofascore</a>"
                        )
                        registro["ultima_cuota_1"] = p_1

                # REPORTE DE HOY (Abierto a todos, priorizando visualmente a los Top o con patrones claros)
                if dias_restantes == 0:
                    if registro["hoy_enviado"] != hoy or es_prueba_inicial:
                        print(f"🤖 Analizando partido de HOY: {local} vs {visita}...", flush=True)
                        analisis_ia = obtener_analisis_gemini(local, visita, nombre_liga_limpio)
                        
                        etiqueta = "⭐ <b>[DESTACADO / EQUIPO TOP]</b>\n" if is_top else ""
                        partidos_para_reporte_hoy.append(
                            f"{etiqueta}• <b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                            f"   ⏰ <b>Hora:</b> {hora_local_str} ⚡ <b>¡JUEGA HOY!</b>\n"
                            f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n\n"
                            f"   📈 <b>Patrones y Radiografía Reciente:</b>\n"
                            f"   {analisis_ia}\n\n"
                            f"   👉 <a href='{url_sofascore}'>Abrir Sofascore</a>"
                        )
                        registro["hoy_enviado"] = hoy

                # PARTIDOS PRÓXIMOS (Abierto a más equipos de la liga, no solo top)
                elif 1 <= dias_restantes <= 5:
                    if not registro["previo_enviado"] or es_prueba_inicial:
                        # Permitimos evaluar próximos, manteniendo un límite prudente para no saturar
                        print(f"🤖 Analizando próximo: {local} vs {visita}...", flush=True)
                        analisis_ia = obtener_analisis_gemini(local, visita, nombre_liga_limpio)
                        
                        etiqueta = "⭐ " if is_top else "📌 "
                        partidos_para_aviso_previo.append(
                            f"{etiqueta}<b>{local} vs {visita}</b> <i>({nombre_liga_limpio})</i>\n"
                            f"   📅 <b>Fecha:</b> {hora_local_str} (En {dias_restantes} días)\n"
                            f"   📊 Promedio Mercado: 1({p_1}) | X({p_x}) | 2({p_2})\n\n"
                            f"   📈 <b>Patrones Previos de IA:</b>\n"
                            f"   {analisis_ia}\n\n"
                            f"   👉 <a href='{url_sofascore}'>Abrir Sofascore</a>"
                        )
                        registro["previo_enviado"] = str(hoy)

                registro["ultima_cuota_1"] = p_1

        time.sleep(1)

    if alertas_volatilidad and not es_prueba_inicial:
        enviar_telegram("\n\n".join(alertas_volatilidad))

    cuerpo_mensaje_total = []

    if partidos_para_reporte_hoy:
        cuerpo_mensaje_total.append("🔥 <b>PARTIDOS DE HOY (ANÁLISIS GENERAL Y PATRONES)</b>\n\n" + "\n\n".join(partidos_para_reporte_hoy))

    if partidos_para_aviso_previo:
        # Mostramos una selección variada de próximos
        cuerpo_previo = "\n\n".join(partidos_para_aviso_previo[:4])
        cuerpo_mensaje_total.append("🗓️ <b>AGENDA: PRÓXIMOS PARTIDOS</b>\n\n" + cuerpo_previo)

    if cuerpo_mensaje_total and not es_prueba_inicial:
        titulo_rep = f"📊 <b>REPORTE DEL DÍA</b>\n<i>Hora local Sinaloa: {ahora_local.strftime('%H:%M')}</i>"
        enviar_telegram(f"{titulo_rep}\n\n" + "\n\n━━━━━━━━━━━━━━━\n\n".join(cuerpo_mensaje_total))
    elif es_prueba_inicial:
        cuerpo_prueba = "\n\n━━━━━━━━━━━━━━━\n\n".join(cuerpo_mensaje_total) if cuerpo_mensaje_total else "ℹ️ <i>No hay partidos detectados en el rango actual.</i>"
        enviar_telegram(f"🧪 <b>REPORTE DE PRUEBA (ANÁLISIS ABIERTO ACTIVO)</b>\n\n{cuerpo_prueba}")

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
