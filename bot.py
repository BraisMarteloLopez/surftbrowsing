"""Bot v2 — Orquestador de fases con personalidades.

Ejecuta las fases del formulario ICP replicando comportamiento humano.
Actualmente implementa solo la Fase 0 (selección de sede).

Uso:
    python bot.py

Requisitos:
    - Navegador con --remote-debugging-port=9222
    - pip install websockets python-dotenv
    - Archivo .env con NIE y NOMBRE (ver .env.example)
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv

from cdp_core import (
    CDPSession, ejecutar_js, obtener_ws_url, esperar_elemento,
    WafBanError, ElementoNoEncontrado, TimeoutCargaPagina,
    detectar_waf, log_info,
    TIMEOUT_PAGINA, TIMEOUT_JS,
)
from humano import (
    Personalidad, EstadoRaton, fase_0, fase_1, fase_2, fase_3,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

NIE = os.getenv("NIE", "").strip()
NOMBRE = os.getenv("NOMBRE", "").strip()
PASO_HASTA = int(os.getenv("PASO_HASTA", "5"))
INTERVALO_REINTENTO = float(os.getenv("INTERVALO_REINTENTO_SEGUNDOS", "120"))

# WAF backoff
WAF_BACKOFF_BASE = float(os.getenv("WAF_BACKOFF_BASE_SEGUNDOS", "300"))
WAF_BACKOFF_MAX = float(os.getenv("WAF_BACKOFF_MAX_SEGUNDOS", "900"))
WAF_BACKOFF_UMBRAL_ALERTA = int(os.getenv("WAF_BACKOFF_UMBRAL_ALERTA", "3"))

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
    """Limpia caché HTTP y storage sin tocar cookies."""
    parsed = urlparse(origin)
    clean_origin = f"{parsed.scheme}://{parsed.netloc}"
    storage_types = (
        "appcache,cache_storage,indexeddb,"
        "local_storage,service_workers,websql"
    )
    try:
        await cdp.send("Storage.clearDataForOrigin", {
            "origin": clean_origin,
            "storageTypes": storage_types,
        }, timeout=TIMEOUT_JS)
    except Exception:
        pass
    try:
        await cdp.send("Network.enable", timeout=TIMEOUT_JS)
        await cdp.send("Network.clearBrowserCache", timeout=TIMEOUT_JS)
    except Exception:
        pass


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

    # Validar configuración mínima
    if not NIE:
        print("ERROR: Falta la variable NIE en .env")
        sys.exit(1)
    if not NOMBRE:
        print("ERROR: Falta la variable NOMBRE en .env")
        sys.exit(1)

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
    log_info(f"NIE: {NIE[:3]}*** / Nombre: {NOMBRE.split()[0]}***")
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

            # ── FASE 4: TODO (no implementada aún) ────────────────────────
            log("Fases 0-3 completadas. Fase 4 pendiente de implementación.")
            log("Simulando resultado: NO_HAY_CITAS → volviendo al inicio")

            # Click en "Salir"/"Aceptar" para volver al inicio (reutilizar lógica v1)
            # Por ahora, navegamos de nuevo
            es_primera_vez = True

            backoff.registrar_exito()
            waf_backoff.registrar_exito()

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
