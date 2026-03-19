"""
Bot de cita previa extranjería — POLICÍA TARJETA CONFLICTO UCRANIA (Madrid)

Automatiza la navegación del portal ICP mediante Chrome DevTools Protocol (CDP)
sobre Brave Browser. Cuando detecta cita disponible, emite alerta sonora y
mantiene la sesión activa para que el usuario complete manualmente.

Requisitos:
    - Brave lanzado con: brave.exe --remote-debugging-port=9222
    - pip install websockets python-dotenv
    - Archivo .env con NIE y NOMBRE (ver .env.example)
"""

import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv

from cdp_helpers import (
    CDPSession, ejecutar_js, safe_js_string, obtener_ws_url,
    log_info, TIMEOUT_PAGINA, TIMEOUT_NAVEGACION, TIMEOUT_JS,
    CDP_PORT, CDP_URL,
)

from comportamiento_humano import (
    WafBanError, SimuladorHumano,
    mover_raton, movimiento_raton_aleatorio, mover_raton_a_elemento,
    scroll_humano, delay, pausa_entre_pasos, pausa_extra_aleatoria,
    intervalo_con_jitter, detectar_waf, limpiar_datos_navegador,
    DELAY_ACCION_BASE, DELAY_ACCION_VARIANZA,
    DELAY_SCROLL_MIN, DELAY_SCROLL_MAX,
    DELAY_EVALUACION_MIN, DELAY_EVALUACION_MAX,
    PAUSA_ENTRE_PASOS_MIN, PAUSA_ENTRE_PASOS_MAX,
    WAF_BACKOFF_BASE, WAF_BACKOFF_MAX, WAF_BACKOFF_UMBRAL_ALERTA,
)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

load_dotenv()

NIE = os.getenv("NIE", "").strip()
NOMBRE = os.getenv("NOMBRE", "").strip()
PASO_HASTA = int(os.getenv("PASO_HASTA", "5"))
INTERVALO_REINTENTO = float(os.getenv("INTERVALO_REINTENTO_SEGUNDOS", "120"))

# Timeout para esperar que un elemento aparezca en el DOM
TIMEOUT_ESPERA_ELEMENTO = float(os.getenv("TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS", "10"))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

class EstadoPagina(Enum):
    """Resultado de evaluar la página tras solicitar cita."""
    NO_HAY_CITAS = "no_hay_citas"
    HAY_CITAS = "hay_citas"
    DESCONOCIDO = "desconocido"
    WAF_BANEADO = "waf_baneado"


class BackoffController:
    """Controla intervalos de reintento con backoff exponencial y alertas."""

    def __init__(self, intervalo_base: float = 5.0, max_intervalo: float = 300.0,
                 umbral_alerta: int = 10):
        self.intervalo_base = intervalo_base
        self.max_intervalo = max_intervalo
        self.umbral_alerta = umbral_alerta
        self._errores_consecutivos = 0
        self._tipo_ultimo_error: str | None = None

    def registrar_exito(self) -> None:
        """Resetea contadores tras un ciclo exitoso (sin errores)."""
        self._errores_consecutivos = 0
        self._tipo_ultimo_error = None

    def registrar_error(self, tipo: str) -> float:
        """Registra un error y devuelve el intervalo de espera recomendado."""
        self._errores_consecutivos += 1
        self._tipo_ultimo_error = tipo
        intervalo = min(
            self.intervalo_base * (2 ** (self._errores_consecutivos - 1)),
            self.max_intervalo,
        )
        return intervalo

    @property
    def errores_consecutivos(self) -> int:
        return self._errores_consecutivos

    @property
    def debe_alertar(self) -> bool:
        """True si los errores consecutivos superan el umbral."""
        return self._errores_consecutivos >= self.umbral_alerta

    @property
    def tipo_ultimo_error(self) -> str | None:
        return self._tipo_ultimo_error


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_intento = 0


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Intento #{_intento} — {msg}")



async def navegar(cdp: CDPSession, url: str) -> None:
    """Navega a una URL y espera a que cargue."""
    await cdp.send("Page.enable", timeout=TIMEOUT_JS)
    # Pre-registrar el Future ANTES de navegar para evitar race condition
    load_fut = cdp.pre_wait_event("Page.loadEventFired")
    await cdp.send("Page.navigate", {"url": url}, timeout=TIMEOUT_NAVEGACION)
    await cdp.wait_future(load_fut, timeout=TIMEOUT_NAVEGACION)


async def verificar_url(cdp: CDPSession, url_esperada: str) -> bool:
    """Verifica que la URL actual corresponde a la esperada."""
    result = await ejecutar_js(cdp, "window.location.href;")
    url_actual = result.get("value", "")
    base_esperada = url_esperada.split("?")[0]
    ok = base_esperada in url_actual or "icpplus" in url_actual
    if not ok:
        log_info(f"URL esperada: {url_esperada}")
        log_info(f"URL actual:   {url_actual}")
    return ok


async def esperar_elemento(cdp: CDPSession, element_id: str, timeout: float = TIMEOUT_ESPERA_ELEMENTO) -> bool:
    """Espera hasta que un elemento exista en el DOM (polling cada 0.5s).

    Recibe el ID crudo (sin escapar). El escape se aplica internamente.
    """
    escaped = safe_js_string(element_id)
    inicio = time.monotonic()
    while (time.monotonic() - inicio) < timeout:
        result = await ejecutar_js(cdp, f"document.getElementById('{escaped}') !== null;")
        if result.get("value", False):
            return True
        await asyncio.sleep(0.5)
    log(f"Timeout esperando elemento #{element_id} ({timeout}s)")
    return False


async def click_y_esperar_carga(cdp: CDPSession, js_click: str) -> None:
    """Pre-registra el evento de carga, hace click, y espera la carga."""
    load_fut = cdp.pre_wait_event("Page.loadEventFired")
    await ejecutar_js(cdp, js_click)
    try:
        await cdp.wait_future(load_fut, timeout=TIMEOUT_NAVEGACION)
    except asyncio.TimeoutError:
        log("Timeout esperando carga de página, continuando...")
    # Detectar ban WAF tras cada carga de página
    if await detectar_waf(cdp):
        raise WafBanError("WAF ha bloqueado la petición")


# ---------------------------------------------------------------------------
# Navegación de formularios
# ---------------------------------------------------------------------------

async def paso_formulario_1(humano: SimuladorHumano, ids: dict) -> None:
    """Formulario 1: Selección de provincia (Madrid)."""
    cdp = humano.cdp
    log("Formulario 1: seleccionando provincia Madrid")

    dropdown_id = safe_js_string(ids["dropdown_provincia"])
    valor = safe_js_string(ids["valor_madrid"])
    boton_id = safe_js_string(ids["boton_aceptar_f1"])

    if not await esperar_elemento(cdp, ids["dropdown_provincia"]):
        raise RuntimeError(f"Elemento #{ids['dropdown_provincia']} no apareció tras carga de página")

    await humano.movimiento_idle()
    await humano.scroll()
    await humano.delay_activo()
    await humano.pausa_extra()

    # Mover ratón al dropdown antes de interactuar
    await humano.mover_a_elemento(ids["dropdown_provincia"])
    await ejecutar_js(cdp, f"""
        document.getElementById('{dropdown_id}').value = '{valor}';
        document.getElementById('{dropdown_id}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await humano.delay_activo()
    await humano.mover_a_elemento(ids["boton_aceptar_f1"])
    await humano.pausa_extra()
    log("Formulario 1: provincia seleccionada, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_2(humano: SimuladorHumano, ids: dict) -> None:
    """Formulario 2: Selección de trámite."""
    cdp = humano.cdp
    log("Formulario 2: seleccionando trámite")

    dropdown_id = safe_js_string(ids["dropdown_tramite"])
    valor = safe_js_string(ids["valor_tramite"])
    boton_id = safe_js_string(ids["boton_aceptar_f2"])

    if not await esperar_elemento(cdp, ids["dropdown_tramite"]):
        raise RuntimeError(f"Elemento #{ids['dropdown_tramite']} no apareció tras carga de página")

    await humano.movimiento_idle()
    await humano.scroll()
    await humano.delay_activo()

    await humano.mover_a_elemento(ids["dropdown_tramite"])
    await humano.pausa_extra()
    await ejecutar_js(cdp, f"""
        document.getElementById('{dropdown_id}').value = '{valor}';
        document.getElementById('{dropdown_id}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await humano.delay_activo()
    await humano.mover_a_elemento(ids["boton_aceptar_f2"])
    log("Formulario 2: trámite seleccionado, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_3(humano: SimuladorHumano, ids: dict) -> None:
    """Formulario 3: Aviso informativo — click en Entrar."""
    cdp = humano.cdp
    log("Formulario 3: aceptando aviso")

    boton_id = safe_js_string(ids["boton_entrar_f3"])

    if not await esperar_elemento(cdp, ids["boton_entrar_f3"]):
        raise RuntimeError(f"Elemento #{ids['boton_entrar_f3']} no apareció tras carga de página")

    await humano.movimiento_idle()
    await humano.scroll()
    await humano.delay_activo()
    await humano.pausa_extra()

    await humano.mover_a_elemento(ids["boton_entrar_f3"])
    log("Formulario 3: aviso aceptado, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def _rellenar_campo_nie(cdp: CDPSession, input_nie: str) -> None:
    """Rellena el campo NIE con movimiento de ratón y focus previo."""
    nie_escaped = safe_js_string(NIE)
    await ejecutar_js(cdp, f"""
        document.getElementById('{input_nie}').value = '{nie_escaped}';
        document.getElementById('{input_nie}').dispatchEvent(new Event('input', {{ bubbles: true }}));
    """)


async def _rellenar_campo_nombre(cdp: CDPSession, input_nombre: str) -> None:
    """Rellena el campo nombre con movimiento de ratón y focus previo."""
    nombre_escaped = safe_js_string(NOMBRE)
    await ejecutar_js(cdp, f"""
        document.getElementById('{input_nombre}').value = '{nombre_escaped}';
        document.getElementById('{input_nombre}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)


async def paso_formulario_4(humano: SimuladorHumano, ids: dict) -> None:
    """Formulario 4: Datos personales (NIE + nombre).

    El orden de rellenado de campos se aleatoriza: a veces NIE primero,
    a veces nombre primero. Un humano no siempre rellena los campos
    en el mismo orden.
    """
    cdp = humano.cdp
    log("Formulario 4: rellenando datos personales")
    await humano.delay_activo()

    input_nie = safe_js_string(ids["input_nie"])
    input_nombre = safe_js_string(ids["input_nombre"])
    boton_id = safe_js_string(ids["boton_aceptar_f4"])

    # Esperar a que el formulario esté disponible tras la carga
    if not await esperar_elemento(cdp, ids["input_nie"]):
        raise RuntimeError(f"Elemento #{ids['input_nie']} no apareció tras carga de página")

    await humano.movimiento_idle()
    await humano.pausa_extra()

    # Orden aleatorio: a veces NIE primero, a veces nombre primero
    if random.random() < 0.5:
        # NIE → Nombre (orden original)
        await humano.mover_a_elemento(ids["input_nie"])
        await _rellenar_campo_nie(cdp, input_nie)
        await humano.delay_activo()
        await humano.mover_a_elemento(ids["input_nombre"])
        await humano.pausa_extra()
        await _rellenar_campo_nombre(cdp, input_nombre)
    else:
        # Nombre → NIE (orden invertido)
        await humano.mover_a_elemento(ids["input_nombre"])
        await _rellenar_campo_nombre(cdp, input_nombre)
        await humano.delay_activo()
        await humano.mover_a_elemento(ids["input_nie"])
        await humano.pausa_extra()
        await _rellenar_campo_nie(cdp, input_nie)

    await humano.delay_activo()
    await humano.mover_a_elemento(ids["boton_aceptar_f4"])
    log("Formulario 4: datos enviados, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_5(humano: SimuladorHumano, ids: dict) -> None:
    """Formulario 5: Solicitar cita."""
    cdp = humano.cdp
    log("Formulario 5: solicitando cita")
    await humano.delay_activo()

    boton_id = safe_js_string(ids["boton_solicitar_cita"])

    if not await esperar_elemento(cdp, ids["boton_solicitar_cita"]):
        raise RuntimeError(f"Elemento #{ids['boton_solicitar_cita']} no apareció tras carga de página")

    await humano.movimiento_idle()
    await humano.pausa_extra()
    await humano.mover_a_elemento(ids["boton_solicitar_cita"])

    log("Formulario 5: cita solicitada, esperando respuesta...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


# ---------------------------------------------------------------------------
# Detección de disponibilidad
# ---------------------------------------------------------------------------

async def evaluar_estado_pagina(cdp: CDPSession, ids: dict) -> EstadoPagina:
    """Evalúa el estado de la página tras solicitar cita.

    Verifica múltiples señales para evitar falsos positivos:
    1. Presencia del texto "no hay citas" (case-insensitive, parcial).
    2. Contenido mínimo en el body (página no vacía/error).
    3. URL coherente con el flujo del portal.
    4. (Opcional) Presencia de texto positivo "hay citas" para confirmar.
    """
    # 1. Espera aleatoria para simular lectura humana tras carga
    await asyncio.sleep(random.uniform(DELAY_EVALUACION_MIN, DELAY_EVALUACION_MAX))

    # 2. Verificar que la página tiene contenido sustancial
    body_length = await ejecutar_js(cdp, "document.body.innerText.length;")
    if body_length.get("value", 0) < 50:
        log("Estado: página con contenido insuficiente (<50 chars)")
        return EstadoPagina.DESCONOCIDO

    # 3. Buscar texto de "no hay citas" (case-insensitive, parcial)
    texto_buscar = safe_js_string(ids["texto_no_hay_citas"].lower())
    texto_check = await ejecutar_js(cdp, f"""
        document.body.innerText.toLowerCase().includes('{texto_buscar}');
    """)
    if texto_check.get("value", False):
        # El texto "no hay citas" es la señal definitiva del estado.
        # El botón Salir puede tardar en renderizarse o haber cambiado de ID;
        # click_salir() ya maneja su ausencia con fallback graceful.
        return EstadoPagina.NO_HAY_CITAS

    # 5. Verificar que la URL pertenece al flujo del portal
    url_check = await ejecutar_js(cdp, "window.location.href;")
    current_url = url_check.get("value", "")
    if "icpplus" not in current_url and "icpplustiem" not in current_url:
        log(f"Estado: URL inesperada: {current_url}")
        return EstadoPagina.DESCONOCIDO

    # 6. Verificación positiva opcional: confirmar con texto de cita disponible
    texto_positivo = ids.get("texto_hay_citas", "")
    if texto_positivo:
        texto_pos_buscar = safe_js_string(texto_positivo.lower())
        positivo_check = await ejecutar_js(cdp, f"""
            document.body.innerText.toLowerCase().includes('{texto_pos_buscar}');
        """)
        if positivo_check.get("value", False):
            log("Confirmación positiva: texto de cita disponible encontrado")
            return EstadoPagina.HAY_CITAS
        # Texto positivo configurado pero no encontrado → estado incierto
        log("Estado: no se encontró texto negativo NI positivo")
        return EstadoPagina.DESCONOCIDO

    # 7. Sin verificación positiva configurada: asumir cita disponible
    return EstadoPagina.HAY_CITAS


async def click_salir(cdp: CDPSession, ids: dict) -> bool:
    """Click en botón Salir. Devuelve True si tuvo éxito, False si no pudo."""
    boton_id = safe_js_string(ids["boton_salir_nocita"])

    if not await esperar_elemento(cdp, ids["boton_salir_nocita"]):
        log("Botón Salir no encontrado, se navegará al inicio directamente")
        return False

    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")
    return True


# ---------------------------------------------------------------------------
# Alerta sonora
# ---------------------------------------------------------------------------

async def alerta_sonora() -> None:
    """Emite alerta sonora en bucle. Usa winsound en Windows, beep del sistema en otros."""
    try:
        import winsound
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, winsound.Beep, 1000, 500)
            await loop.run_in_executor(None, winsound.Beep, 1500, 500)
            await loop.run_in_executor(None, winsound.Beep, 2000, 500)
            await asyncio.sleep(1)
    except ImportError:
        # Linux/Mac: beep del sistema
        while True:
            print("\a", end="", flush=True)
            await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

async def ciclo_completo(cdp: CDPSession, ids: dict,
                         paso_hasta: int = 5) -> EstadoPagina | None:
    """Ejecuta formularios desde el paso 0 hasta paso_hasta (inclusive).

    Crea un SimuladorHumano que mantiene el estado del ratón entre pasos.
    Devuelve EstadoPagina con el resultado, o None si se detuvo antes
    del paso 5 (modo depuración).
    """
    humano = SimuladorHumano(cdp)

    pasos = [
        (1, paso_formulario_1),
        (2, paso_formulario_2),
        (3, paso_formulario_3),
        (4, paso_formulario_4),
        (5, paso_formulario_5),
    ]

    for num, fn in pasos:
        if num > paso_hasta:
            log(f"Detenido en paso {paso_hasta} (PASO_HASTA={paso_hasta})")
            return None
        await fn(humano, ids)
        # Pausa entre formularios para simular lectura humana
        if num < paso_hasta and num < 5:
            await humano.pausa_lectura()

    # Detectar ban WAF antes de evaluar resultado
    if await detectar_waf(cdp):
        return EstadoPagina.WAF_BANEADO

    estado = await evaluar_estado_pagina(cdp, ids)
    return estado


async def conectar_brave() -> tuple:
    """Conecta a Brave via CDP y devuelve (ws, cdp) listos para usar."""
    import websockets

    ws_url = await obtener_ws_url()
    log_info(f"WebSocket: {ws_url}")
    ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
    cdp = CDPSession(ws)
    await cdp.start()
    await cdp.send("Page.enable")
    return ws, cdp


async def main() -> None:
    global _intento

    # Validar configuración
    if not NIE:
        print("ERROR: Falta la variable NIE en el archivo .env")
        print("Crea un archivo .env con tu NIE. Ver .env.example")
        sys.exit(1)
    if not NOMBRE:
        print("ERROR: Falta la variable NOMBRE en el archivo .env")
        print("Crea un archivo .env con tu nombre completo. Ver .env.example")
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
    ids = config["ids"]

    if not 0 <= PASO_HASTA <= 5:
        print(f"ERROR: PASO_HASTA debe ser entre 0 y 5, recibido: {PASO_HASTA}")
        sys.exit(1)

    log_info(f"Configuración cargada — NIE: {NIE[:3]}*** / Nombre: {NOMBRE.split()[0]}***")
    log_info(f"Intervalo reintento: {INTERVALO_REINTENTO}s / Delay acciones: {DELAY_ACCION_BASE}s+[0-{DELAY_ACCION_VARIANZA*100:.0f}%] / Timeout: {TIMEOUT_PAGINA}s")
    if PASO_HASTA < 5:
        log_info(f"Modo depuración: ejecutando pasos 0-{PASO_HASTA} y deteniendo (no entra en bucle)")

    # Conectar a Brave
    log_info("Conectando a Brave via CDP...")
    ws, cdp = await conectar_brave()
    log_info("Conectado a Brave. Iniciando bucle de búsqueda de cita...")

    backoff = BackoffController(
        intervalo_base=5.0,
        max_intervalo=300.0,
        umbral_alerta=10,
    )
    waf_backoff = BackoffController(
        intervalo_base=WAF_BACKOFF_BASE,
        max_intervalo=WAF_BACKOFF_MAX,
        umbral_alerta=WAF_BACKOFF_UMBRAL_ALERTA,
    )

    skip_navegacion = False

    while True:
        _intento += 1

        try:
            # Verificar conexión CDP antes de cada ciclo
            if not cdp.is_alive:
                log("Conexión CDP perdida. Reconectando...")
                skip_navegacion = False
                try:
                    await ws.close()
                except Exception:
                    pass
                await asyncio.sleep(2)
                ws, cdp = await conectar_brave()
                log_info("Reconexión exitosa.")

            # Paso 0: Navegar al inicio (se salta si Salir ya nos devolvió)
            if skip_navegacion:
                log("Reutilizando sesión del portal (sin navegación extra)")
                skip_navegacion = False
            else:
                log("Navegando a URL de inicio...")
                await navegar(cdp, url_inicio)

                # Detectar ban WAF antes de continuar
                if await detectar_waf(cdp):
                    espera = waf_backoff.registrar_error("waf")
                    minutos = espera / 60
                    log(f"*** WAF DETECTADO *** Baneado por el firewall del portal.")
                    log(f"Esperando {minutos:.1f} minutos antes de reintentar... (ban #{waf_backoff.errores_consecutivos})")
                    if waf_backoff.debe_alertar:
                        log("ALERTA: Baneado demasiadas veces. Considera aumentar INTERVALO_REINTENTO_SEGUNDOS.")
                    await asyncio.sleep(espera)
                    continue

                # Verificar que la navegación llegó al destino correcto
                if not await verificar_url(cdp, url_inicio):
                    log("ADVERTENCIA: URL post-navegación no coincide con el inicio.")
                    espera = backoff.registrar_error("navegacion")
                    log(f"Reiniciando ciclo en {espera:.0f}s...")
                    await asyncio.sleep(espera)
                    continue

                log("Página cargada")

            if PASO_HASTA == 0:
                log("Detenido en paso 0 (PASO_HASTA=0) — solo navegación")
                log_info("Modo depuración finalizado.")
                return

            # Pasos 1-5: Formularios
            resultado = await ciclo_completo(cdp, ids, PASO_HASTA)

            if resultado is None:
                # Modo depuración: se detuvo antes del paso 5
                log_info("Modo depuración finalizado.")
                return

            if resultado == EstadoPagina.WAF_BANEADO:
                skip_navegacion = False
                espera = waf_backoff.registrar_error("waf")
                minutos = espera / 60
                log(f"*** WAF DETECTADO *** Baneado durante el flujo de formularios.")
                log(f"Esperando {minutos:.1f} minutos antes de reintentar... (ban #{waf_backoff.errores_consecutivos})")
                if waf_backoff.debe_alertar:
                    log("ALERTA: Baneado demasiadas veces. Considera aumentar INTERVALO_REINTENTO_SEGUNDOS.")
                await asyncio.sleep(espera)
                continue

            if resultado == EstadoPagina.HAY_CITAS:
                backoff.registrar_exito()
                waf_backoff.registrar_exito()
                print()
                print("=" * 60)
                log("*** CITA DISPONIBLE *** — Toma el control del navegador")
                print("=" * 60)
                print()

                # Solo alerta sonora — sin keep-alive para no generar tráfico
                await alerta_sonora()
            elif resultado == EstadoPagina.NO_HAY_CITAS:
                backoff.registrar_exito()
                waf_backoff.registrar_exito()
                log("Resultado: NO HAY CITAS")
                if await click_salir(cdp, ids):
                    skip_navegacion = True
                # Limpiar caché y storage antes del siguiente ciclo
                await limpiar_datos_navegador(cdp, url_inicio)
                espera = intervalo_con_jitter(INTERVALO_REINTENTO)
                log(f"Reintentando en {espera:.0f}s...")
                await asyncio.sleep(espera)
            else:
                # EstadoPagina.DESCONOCIDO
                espera = backoff.registrar_error("desconocido")
                log(f"ADVERTENCIA: Estado de página no reconocido. (error #{backoff.errores_consecutivos})")
                if backoff.debe_alertar:
                    log("ALERTA: Demasiados estados desconocidos. Posible cambio en el portal.")
                log(f"Reiniciando ciclo en {espera:.0f}s...")
                await asyncio.sleep(espera)

        except WafBanError:
            skip_navegacion = False
            espera = waf_backoff.registrar_error("waf")
            minutos = espera / 60
            log(f"*** WAF DETECTADO *** Baneado durante navegación de formularios.")
            log(f"Esperando {minutos:.1f} minutos antes de reintentar... (ban #{waf_backoff.errores_consecutivos})")
            if waf_backoff.debe_alertar:
                log("ALERTA: Baneado demasiadas veces. Considera aumentar INTERVALO_REINTENTO_SEGUNDOS.")
            await asyncio.sleep(espera)

        except ConnectionError as e:
            skip_navegacion = False
            espera = backoff.registrar_error("conexion")
            log(f"Conexión perdida: {e}. Reconectando en {espera:.0f}s... (error #{backoff.errores_consecutivos})")
            if backoff.debe_alertar:
                log("ALERTA: Demasiados errores de conexión consecutivos.")
            await asyncio.sleep(espera)
            try:
                try:
                    await ws.close()
                except Exception:
                    pass
                ws, cdp = await conectar_brave()
                log_info("Reconexión exitosa.")
            except Exception as e2:
                log(f"Reconexión fallida: {e2}. Se reintentará en el próximo ciclo.")

        except asyncio.TimeoutError:
            skip_navegacion = False
            espera = backoff.registrar_error("timeout")
            log(f"Timeout en carga de página. Reiniciando en {espera:.0f}s... (error #{backoff.errores_consecutivos})")
            if backoff.debe_alertar:
                log("ALERTA: Demasiados timeouts consecutivos. Posible congestión del portal.")
            await asyncio.sleep(espera)

        except RuntimeError as e:
            skip_navegacion = False
            espera = backoff.registrar_error("js_error")
            log(f"Error JS: {e}. Reiniciando en {espera:.0f}s... (error #{backoff.errores_consecutivos})")
            if backoff.debe_alertar:
                log("ALERTA: Demasiados errores JS consecutivos. Posible cambio en el portal.")
            await asyncio.sleep(espera)

        except Exception as e:
            skip_navegacion = False
            espera = backoff.registrar_error("inesperado")
            log(f"Error inesperado: {type(e).__name__}: {e}. Reiniciando en {espera:.0f}s... (error #{backoff.errores_consecutivos})")
            if backoff.debe_alertar:
                log("ALERTA: Demasiados errores inesperados consecutivos.")
            await asyncio.sleep(espera)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{ts}] Script detenido por el usuario (Ctrl+C). Brave sigue abierto.")
