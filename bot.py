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
    return "Bot de Momios Avanzado Activo"

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1530533411")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

LIGAS = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champions_league",
    "soccer_uefa_europa_league"
]

HORARIOS_OBJETIVO = [
    (8, 0),   # 8:00 a.m.
    (16, 30)  # 4:30 p.m.
]

EQUIPOS_TOP = [
    "barcelona", "real madrid", "atletico madrid", "atlético de madrid",
    "manchester city", "arsenal", "liverpool", "manchester united", "chelsea",
    "bayern munich", "bayern münchen", "borussia dortmund", "leverkusen",
    "juventus", "inter", "ac milan", "napoli",
    "psg", "paris saint-germain", "ajax", "psv",
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
        print(f"📤 Respuesta de Telegram status_code: {r.status_code}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}", flush=True)
        return False

def obtener_analisis_gemini(local, visita, liga_nombre):
    if not GEMINI_DISPONIBLE or not GEMINI_API_KEY:
        return "<i>(Análisis de IA no disponible)</i>"
    
    prompt = (
        f"Analiza brevemente el partido de {liga_nombre}: {local} contra {visita}. "
        "Da en máximo 2 líneas una tendencia clave o recomendación directa basada en rendimiento reciente."
    )
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        time.sleep(4)
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"⚠️ Error en análisis IA para {local} vs {visita}: {e}", flush=True)
        time.sleep(5)
        
    return "<i>(Análisis omitido por protección de cuota)</i>"

def obtener_partidos_liga(sport_key):
    if not THE_ODDS_API_KEY:
        return []
    target_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={THE_ODDS_API_KEY}&regions=eu,us,uk&markets=h2h&oddsFormat=decimal"
    try:
        r = requests.get(target_url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            print(f"📥 {sport_key}: {len(data)} eventos encontrados en API.", flush=True)
            return data
        print(f"⚠️ {sport_key} respondió status {r.status_code}", flush=True)
        return []
    except Exception as e:
        print(f"❌ Error consultando The Odds API para {sport_key}: {e}", flush=True)
        return []

def ejecutar_ciclo():
    print(f"🚀 Ejecutando escaneo inteligente con IA optimizada...", flush=True)
    
    tz = ZoneInfo("America/Mazatlan")
    ahora_local = datetime.now(tz)
    hoy = ahora_local.date()

    candidatos_totales = []

    for sport_key in LIGAS:
        eventos = obtener_partidos_liga(sport_key)
        if not eventos:
            continue
            
        nombre_liga_limpio = sport_key.replace("soccer_", "").replace("_", " ").title()

        for evento in eventos:
            local = evento.get("home_team")
            visita = evento.get("away_team")
            commence_time_str = evento.get("commence_time", "")
            
            try:
                dt_utc = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone(tz)
                fecha_partido = dt_local.date()
                hora_local_str = dt_local.strftime("%H:%M hrs (%d/%b)")
            except Exception:
                continue

            dias_restantes = (fecha_partido - hoy).days
            if dias_restantes < 0 or dias_restantes > 7:
                continue

            bookmakers = evento.get("bookmakers", [])
            p_1, p_x, p_2 = 0, 0, 0
            
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
                        if "1" in precios: p_1 = precios["1"]
                        if "X" in precios: p_x = precios["X"]
                        if "2" in precios: p_2 = precios["2"]
                        break
                if p_1 > 0:
                    break

            is_top = es_equipo_top(local, visita)

            # Sistema de puntuación: Top teams primero, luego partidos de hoy, luego por días
            prioridad_top = 0 if is_top else 1
            prioridad_hoy = 0 if dias_restantes == 0 else 1
            
            candidatos_totales.append({
                "sort_key": (prioridad_top, prioridad_hoy, dias_restantes),
                "local": local,
                "visita": visita,
                "liga": nombre_liga_limpio,
                "hora": hora_local_str,
                "dias": dias_restantes,
                "p_1": p_1,
                "p_x": p_x,
                "p_2": p_2,
                "is_top": is_top
            })

    # Ordenar por relevancia global
    candidatos_totales.sort(key=lambda x: x["sort_key"])

    partidos_para_reporte = []
    llamadas_ia = 0
    LIMITE_IA = 2

    for c in candidatos_totales[:10]:
        local = c["local"]
        visita = c["visita"]
        is_top = c["is_top"]
        dias_restantes = c["dias"]
        
        analisis_ia = "<i>(Momios de mercado listados)</i>"
        
        # REGLA OPTIMIZADA: Solo se usa IA si el partido es HOY (0) o MAÑANA (1)
        if dias_restantes <= 1 and llamadas_ia < LIMITE_IA:
            analisis_ia = obtener_analisis_gemini(local, visita, c["liga"])
            llamadas_ia += 1

        etiqueta = "🔥 <b>[HOY]</b> " if dias_restantes == 0 else f"📅 <b>[En {dias_restantes} días]</b> "
        if is_top:
            etiqueta += "⭐ "

        partidos_para_reporte.append(
            f"{etiqueta}<b>{local} vs {visita}</b>\n"
            f"   🏆 <i>{c['liga']}</i> | ⏰ {c['hora']}\n"
            f"   📊 Momios: 1({c['p_1']}) | X({c['p_x']}) | 2({c['p_2']})\n"
            f"   🤖 {analisis_ia}"
        )

    titulo = f"⚽ <b>REPORTE INTELIGENTE DE MOMIOS</b>\n<i>Actualizado: {ahora_local.strftime('%d/%b %H:%M')} hrs</i>\n\n"
    
    if partidos_para_reporte:
        mensaje_final = titulo + "\n\n━━━━━━━━━━━━━━━\n\n".join(partidos_para_reporte)
    else:
        mensaje_final = titulo + "ℹ️ <i>No se encontraron partidos próximos en los siguientes 7 días.</i>"

    enviar_telegram(mensaje_final)

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
    print("🤖 Bot de Momios iniciado correctamente...", flush=True)
    tz = ZoneInfo("America/Mazatlan")
    
    try:
        print("🧪 Ejecutando prueba de inicio y envío a Telegram...", flush=True)
        ejecutar_ciclo()
    except Exception as e:
        print(f"❌ Error en la prueba inicial: {e}", flush=True)

    while True:
        ahora = datetime.now(tz)
        siguiente_objetivo = obtener_siguiente_ejecucion(tz)
        segundos_espera = (siguiente_objetivo - ahora).total_seconds()
        
        print(f"⏳ Durmiendo hasta las {siguiente_objetivo.strftime('%H:%M')}...", flush=True)
        time.sleep(segundos_espera)
        
        print(f"🌅 Ejecutando escaneo programado...", flush=True)
        try:
            ejecutar_ciclo()
        except Exception as e:
            print(f"❌ Error crítico en ciclo programado: {e}", flush=True)

hilo_bot = threading.Thread(target=monitorear, daemon=True)
hilo_bot.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run("0.0.0.0", port=port)
