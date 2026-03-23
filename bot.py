"""Bot v2 — Orquestador de fases con personalidades.

Ejecuta las fases del formulario ICP replicando comportamiento humano.

Uso:
    python bot.py

Requisitos:
    - Navegador con --remote-debugging-port=9222
    - pip install websockets python-dotenv
    - Archivo .env (ver .env.example)
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse

from dotenv import load_dotenv

from cdp_core import (
    CDPSession, ejecutar_js, obtener_ws_url, esperar_elemento,
    WafBanError, ElementoNoEncontrado, TimeoutCargaPagina,
    detectar_waf, safe_js_string, log_info,
    TIMEOUT_PAGINA, TIMEOUT_JS,
)
from humano import (
    Personalidad, EstadoRaton, fase_0, fase_1, fase_2, fase_3, fase_4,
    click_salir_nocita,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

PASO_HASTA = int(os.getenv("PASO_HASTA", "5"))
INTERVALO_REINTENTO = float(os.getenv("INTERVALO_REINTENTO_SEGUNDOS", "120"))

# Evaluación resultado
DELAY_EVALUACION_MIN = float(os.getenv("DELAY_EVALUACION_MIN", "2.0"))
DELAY_EVALUACION_MAX = float(os.getenv("DELAY_EVALUACION_MAX", "5.0"))

# WAF backoff
WAF_BACKOFF_BASE = float(os.getenv("WAF_BACKOFF_BASE_SEGUNDOS", "300"))
WAF_BACKOFF_MAX = float(os.getenv("WAF_BACKOFF_MAX_SEGUNDOS", "900"))
WAF_BACKOFF_UMBRAL_ALERTA = int(os.getenv("WAF_BACKOFF_UMBRAL_ALERTA", "3"))


# ---------------------------------------------------------------------------
# Estado de resultado
# ---------------------------------------------------------------------------

class EstadoPagina(Enum):
    NO_HAY_CITAS = "no_hay_citas"
    HAY_CITAS = "hay_citas"
    DESCONOCIDO = "desconocido"

# ---------------------------------------------------------------------------
# Utilidades (reutilizadas de v1)
# ---------------------------------------------------------------------------

import random

_intento = 0


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Intento #{_intento} — {msg}")


def intervalo_con_jitter(base: float) -> float:
    """±15% de jitter para evitar cadencia periódica."""
    return base * random.uniform(0.85, 1.15)


class BackoffController:
    """Controla intervalos de reintento con backoff exponencial."""

    def __init__(self, intervalo_base: float = 5.0, max_intervalo: float = 300.0,
                 umbral_alerta: int = 10):
        self.intervalo_base = intervalo_base
        self.max_intervalo = max_intervalo
        self.umbral_alerta = umbral_alerta
        self._errores_consecutivos = 0

    def registrar_exito(self) -> None:
        self._errores_consecutivos = 0

    def registrar_error(self, tipo: str) -> float:
        self._errores_consecutivos += 1
        return min(
            self.intervalo_base * (2 ** (self._errores_consecutivos - 1)),
            self.max_intervalo,
        )

    @property
    def errores_consecutivos(self) -> int:
        return self._errores_consecutivos

    @property
    def debe_alertar(self) -> bool:
        return self._errores_consecutivos >= self.umbral_alerta


# ---------------------------------------------------------------------------
# Limpieza de caché (reutilizada de v1)
# ---------------------------------------------------------------------------

async def limpiar_datos_navegador(cdp: CDPSession, origin: str) -> None:
    """Limpia storage del formulario sin tocar cookies ni caché HTTP.

    NO borramos la caché HTTP — un usuario real la mantiene caliente y
    borrarla fuerza la re-descarga de todos los assets (CSS/JS/imágenes),
    multiplicando las peticiones al servidor y disparando el rate limit 429.
    """
    parsed = urlparse(origin)
    clean_origin = f"{parsed.scheme}://{parsed.netloc}"
    # Solo local_storage y websql (estado de formulario).
    # Mantenemos cache_storage/service_workers/indexeddb/caché HTTP intactos.
    storage_types = "local_storage,websql"
    try:
        await cdp.send("Storage.clearDataForOrigin", {
            "origin": clean_origin,
            "storageTypes": storage_types,
        }, timeout=TIMEOUT_JS)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Evaluación de resultado (reutilizada de v1)
# ---------------------------------------------------------------------------

async def evaluar_estado_pagina(cdp: CDPSession, ids: dict) -> EstadoPagina:
    """Evalúa la página tras solicitar cita.

    Multi-señal: contenido mínimo → texto "no hay citas" → URL válida →
    texto positivo opcional.
    """
    await asyncio.sleep(random.uniform(DELAY_EVALUACION_MIN, DELAY_EVALUACION_MAX))

    # Contenido mínimo
    body_length = await ejecutar_js(cdp, "document.body.innerText.length;")
    if body_length.get("value", 0) < 50:
        log("Estado: página con contenido insuficiente (<50 chars)")
        return EstadoPagina.DESCONOCIDO

    # Texto "no hay citas"
    texto_buscar = safe_js_string(ids["texto_no_hay_citas"].lower())
    texto_check = await ejecutar_js(cdp, f"""
        document.body.innerText.toLowerCase().includes('{texto_buscar}');
    """)
    if texto_check.get("value", False):
        return EstadoPagina.NO_HAY_CITAS

    # URL coherente con el portal
    url_check = await ejecutar_js(cdp, "window.location.href;")
    current_url = url_check.get("value", "")
    if "icpplus" not in current_url and "icpplustiem" not in current_url:
        log(f"Estado: URL inesperada: {current_url}")
        return EstadoPagina.DESCONOCIDO

    # Verificación positiva opcional
    texto_positivo = ids.get("texto_hay_citas", "")
    if texto_positivo:
        texto_pos_buscar = safe_js_string(texto_positivo.lower())
        positivo_check = await ejecutar_js(cdp, f"""
            document.body.innerText.toLowerCase().includes('{texto_pos_buscar}');
        """)
        if positivo_check.get("value", False):
            log("Confirmación positiva: texto de cita disponible encontrado")
            return EstadoPagina.HAY_CITAS
        log("Estado: no se encontró texto negativo NI positivo")
        return EstadoPagina.DESCONOCIDO

    return EstadoPagina.HAY_CITAS


# ---------------------------------------------------------------------------
# Conexión al navegador
# ---------------------------------------------------------------------------

async def conectar_navegador() -> tuple:
    """Conecta al navegador via CDP y devuelve (ws, cdp)."""
    import websockets

    ws_url = await obtener_ws_url()
    log_info(f"WebSocket: {ws_url}")
    ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
    cdp = CDPSession(ws)
    await cdp.start()
    await cdp.send("Page.enable")
    return ws, cdp


# ---------------------------------------------------------------------------
# Alerta sonora
# ---------------------------------------------------------------------------

async def alerta_sonora() -> None:
    """Emite alerta sonora en bucle."""
    try:
        import winsound
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, winsound.Beep, 1000, 500)
            await loop.run_in_executor(None, winsound.Beep, 1500, 500)
            await loop.run_in_executor(None, winsound.Beep, 2000, 500)
            await asyncio.sleep(1)
    except ImportError:
        while True:
            print("\a", end="", flush=True)
            await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

async def main() -> None:
    global _intento

    # Cargar config.json
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: No se encontró {config_path}")
        sys.exit(1)

    url_inicio = config["url_inicio"]

    if not 0 <= PASO_HASTA <= 5:
        print(f"ERROR: PASO_HASTA debe ser entre 0 y 5, recibido: {PASO_HASTA}")
        sys.exit(1)

    log_info(f"=== Bot v2 — Replicación de Comportamiento Humano ===")
    log_info(f"PASO_HASTA={PASO_HASTA}")

    # Conectar al navegador
    log_info("Conectando al navegador via CDP...")
    ws, cdp = await conectar_navegador()
    log_info("Conectado. Iniciando bucle...")

    backoff = BackoffController(intervalo_base=5.0, max_intervalo=300.0, umbral_alerta=10)
    waf_backoff = BackoffController(
        intervalo_base=WAF_BACKOFF_BASE,
        max_intervalo=WAF_BACKOFF_MAX,
        umbral_alerta=WAF_BACKOFF_UMBRAL_ALERTA,
    )

    es_primera_vez = True

    while True:
        _intento += 1

        # Nueva personalidad por ciclo
        personalidad = Personalidad()
        raton = EstadoRaton()
        log(f"Personalidad del ciclo: {personalidad}")

        try:
            # Verificar conexión CDP
            if not cdp.is_alive:
                log("Conexión CDP perdida. Reconectando...")
                es_primera_vez = True
                try:
                    await ws.close()
                except Exception:
                    pass
                await asyncio.sleep(2)
                ws, cdp = await conectar_navegador()
                log_info("Reconexión exitosa.")

            # ── FASE 0: Selección de sede ─────────────────────────────────
            await fase_0(cdp, personalidad, raton, es_primera_vez, config)

            if PASO_HASTA == 0:
                log("Detenido en PASO_HASTA=0 — solo Fase 0")
                log_info("Modo depuración finalizado.")
                return

            # ── FASE 1: Selección de trámite ──────────────────────────────
            await fase_1(cdp, personalidad, raton, config)

            if PASO_HASTA == 1:
                log("Detenido en PASO_HASTA=1 — hasta Fase 1")
                log_info("Modo depuración finalizado.")
                return

            # ── FASE 2: Aviso informativo ──────────────────────────────────
            await fase_2(cdp, personalidad, raton, config)

            if PASO_HASTA == 2:
                log("Detenido en PASO_HASTA=2 — hasta Fase 2")
                log_info("Modo depuración finalizado.")
                return

            # ── FASE 3: Datos personales ───────────────────────────────────
            await fase_3(cdp, personalidad, raton, config)

            if PASO_HASTA == 3:
                log("Detenido en PASO_HASTA=3 — hasta Fase 3")
                log_info("Modo depuración finalizado.")
                return

            # ── FASE 4: Solicitar cita ─────────────────────────────────────
            await fase_4(cdp, personalidad, raton, config)

            if PASO_HASTA == 4:
                log("Detenido en PASO_HASTA=4 — hasta Fase 4")
                log_info("Modo depuración finalizado.")
                return

            # ── Evaluación de resultado ────────────────────────────────────
            log("Fases 0-4 completadas. Evaluando resultado...")

            estado = await evaluar_estado_pagina(cdp, config["ids"])

            if estado == EstadoPagina.HAY_CITAS:
                log("*** HAY CITAS DISPONIBLES ***")
                await alerta_sonora()
                return  # El usuario toma el control

            backoff.registrar_exito()
            waf_backoff.registrar_exito()

            if estado == EstadoPagina.NO_HAY_CITAS:
                log("No hay citas disponibles. Volviendo al inicio...")
                volvio = await click_salir_nocita(cdp, personalidad, raton)
                es_primera_vez = not volvio
            else:
                log("Estado desconocido. Reiniciando desde cero...")
                es_primera_vez = True

            # Limpiar caché entre ciclos
            await limpiar_datos_navegador(cdp, url_inicio)

            espera = intervalo_con_jitter(INTERVALO_REINTENTO)
            log(f"Reintentando en {espera:.0f}s...")
            await asyncio.sleep(espera)

        except WafBanError:
            es_primera_vez = True
            espera = waf_backoff.registrar_error("waf")
            minutos = espera / 60
            log(f"*** WAF DETECTADO *** Esperando {minutos:.1f} min (ban #{waf_backoff.errores_consecutivos})")
            if waf_backoff.debe_alertar:
                log("ALERTA: Baneado demasiadas veces.")
            await asyncio.sleep(espera)

        except ElementoNoEncontrado as e:
            es_primera_vez = True
            espera = backoff.registrar_error("elemento")
            log(f"Elemento no encontrado: {e}. Reiniciando en {espera:.0f}s...")
            await asyncio.sleep(espera)

        except TimeoutCargaPagina as e:
            es_primera_vez = True
            espera = backoff.registrar_error("timeout")
            log(f"Timeout: {e}. Reiniciando en {espera:.0f}s...")
            await asyncio.sleep(espera)

        except ConnectionError as e:
            es_primera_vez = True
            espera = backoff.registrar_error("conexion")
            log(f"Conexión perdida: {e}. Reconectando en {espera:.0f}s...")
            await asyncio.sleep(espera)
            try:
                try:
                    await ws.close()
                except Exception:
                    pass
                ws, cdp = await conectar_navegador()
                log_info("Reconexión exitosa.")
            except Exception as e2:
                log(f"Reconexión fallida: {e2}")

        except asyncio.TimeoutError:
            es_primera_vez = True
            espera = backoff.registrar_error("timeout")
            log(f"Timeout genérico. Reiniciando en {espera:.0f}s...")
            await asyncio.sleep(espera)

        except RuntimeError as e:
            es_primera_vez = True
            espera = backoff.registrar_error("runtime")
            log(f"Error: {e}. Reiniciando en {espera:.0f}s...")
            await asyncio.sleep(espera)

        except Exception as e:
            es_primera_vez = True
            espera = backoff.registrar_error("inesperado")
            log(f"Error inesperado: {type(e).__name__}: {e}. Reiniciando en {espera:.0f}s...")
            await asyncio.sleep(espera)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{ts}] Bot detenido por el usuario (Ctrl+C).")
