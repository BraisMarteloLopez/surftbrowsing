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
import urllib.request
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

load_dotenv()

NIE = os.getenv("NIE", "").strip()
NOMBRE = os.getenv("NOMBRE", "").strip()
PASO_HASTA = int(os.getenv("PASO_HASTA", "5"))
INTERVALO_REINTENTO = float(os.getenv("INTERVALO_REINTENTO_SEGUNDOS", "60"))
TIMEOUT_PAGINA = float(os.getenv("TIMEOUT_CARGA_PAGINA_SEGUNDOS", "15"))

# Delays configurables: cada uno con base + varianza aditiva
# Acciones de formulario (click, select, etc.)
DELAY_ACCION_BASE = float(os.getenv("DELAY_ACCION_BASE", "1.0"))
DELAY_ACCION_VARIANZA = max(float(os.getenv("DELAY_ACCION_VARIANZA", "0.5")), 0.0)

# Scroll humano entre pasos de scroll
DELAY_SCROLL_MIN = float(os.getenv("DELAY_SCROLL_MIN", "0.4"))
DELAY_SCROLL_MAX = float(os.getenv("DELAY_SCROLL_MAX", "1.2"))

# Lectura de página antes de evaluar resultado
DELAY_EVALUACION_MIN = float(os.getenv("DELAY_EVALUACION_MIN", "1.0"))
DELAY_EVALUACION_MAX = float(os.getenv("DELAY_EVALUACION_MAX", "3.0"))

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}/json"

# Timeouts diferenciados
TIMEOUT_NAVEGACION = TIMEOUT_PAGINA  # 15s — para Page.navigate + load
TIMEOUT_JS = 5.0                     # 5s — para Runtime.evaluate simples


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def safe_js_string(value: str) -> str:
    """Escapa un string para interpolación segura dentro de un literal JS con comillas simples."""
    return (
        value
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )


class EstadoPagina(Enum):
    """Resultado de evaluar la página tras solicitar cita."""
    NO_HAY_CITAS = "no_hay_citas"
    HAY_CITAS = "hay_citas"
    DESCONOCIDO = "desconocido"


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


def log_info(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

async def obtener_ws_url() -> str:
    """Obtiene la URL WebSocket de la primera pestaña de tipo 'page'."""
    try:
        with urllib.request.urlopen(CDP_URL, timeout=5) as resp:
            tabs = json.loads(resp.read())
    except Exception as e:
        raise ConnectionError(
            f"No se pudo conectar a Brave en localhost:{CDP_PORT}.\n"
            f"Asegúrate de lanzar Brave con: brave.exe --remote-debugging-port={CDP_PORT}\n"
            f"Error: {e}"
        )

    for tab in tabs:
        if tab.get("type") == "page":
            ws_url = tab.get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url

    raise ConnectionError(
        "Brave está corriendo con CDP pero no se encontró ninguna pestaña abierta.\n"
        "Abre al menos una pestaña en Brave."
    )


class CDPSession:
    """Sesión CDP sobre WebSocket."""

    def __init__(self, ws):
        self._ws = ws
        self._id = 0
        self._callbacks: dict[int, asyncio.Future] = {}
        self._events: dict[str, list[asyncio.Future]] = {}
        self._listener_task = None
        self._alive = True

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def start(self):
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._callbacks.pop(msg["id"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif "method" in msg:
                    method = msg["method"]
                    if method in self._events:
                        for fut in self._events.pop(method):
                            if not fut.done():
                                fut.set_result(msg)
        except Exception as e:
            log_info(f"Listener CDP desconectado: {type(e).__name__}: {e}")
        finally:
            self._alive = False
            # Resolver todos los Futures pendientes con error
            for fut in self._callbacks.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Sesión CDP desconectada"))
            self._callbacks.clear()
            for futs in self._events.values():
                for fut in futs:
                    if not fut.done():
                        fut.set_exception(ConnectionError("Sesión CDP desconectada"))
            self._events.clear()

    async def send(self, method: str, params: dict | None = None,
                   timeout: float | None = None) -> dict:
        if not self._alive:
            raise ConnectionError("Sesión CDP desconectada")
        self._id += 1
        msg_id = self._id
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params

        fut = asyncio.get_event_loop().create_future()
        self._callbacks[msg_id] = fut
        await self._ws.send(json.dumps(payload))
        t = timeout if timeout is not None else TIMEOUT_PAGINA
        return await asyncio.wait_for(fut, timeout=t)

    def pre_wait_event(self, event: str) -> asyncio.Future:
        """Pre-registra un Future para un evento ANTES de que ocurra."""
        if not self._alive:
            raise ConnectionError("Sesión CDP desconectada")
        fut = asyncio.get_event_loop().create_future()
        self._events.setdefault(event, []).append(fut)
        return fut

    async def wait_event(self, event: str, timeout: float | None = None):
        fut = asyncio.get_event_loop().create_future()
        self._events.setdefault(event, []).append(fut)
        t = timeout if timeout is not None else TIMEOUT_PAGINA
        return await asyncio.wait_for(fut, timeout=t)

    async def wait_future(self, fut: asyncio.Future, timeout: float | None = None):
        """Espera un Future pre-registrado con pre_wait_event."""
        t = timeout if timeout is not None else TIMEOUT_PAGINA
        return await asyncio.wait_for(fut, timeout=t)

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass


async def ejecutar_js(cdp: CDPSession, expression: str,
                      timeout: float = TIMEOUT_JS) -> dict:
    """Ejecuta JavaScript en la página y devuelve el resultado."""
    result = await cdp.send("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": False,
    }, timeout=timeout)
    if "exceptionDetails" in result.get("result", {}):
        raise RuntimeError(f"Error JS: {result['result']['exceptionDetails']}")
    return result.get("result", {}).get("result", {})


async def scroll_humano(cdp: CDPSession, pasos: int = 3) -> None:
    """Simula scroll humano hacia abajo: N pasos con distancia y delay aleatorios."""
    for _ in range(pasos):
        distancia = random.randint(100, 300)
        await ejecutar_js(cdp, f"window.scrollBy({{ top: {distancia}, behavior: 'smooth' }});")
        await asyncio.sleep(random.uniform(DELAY_SCROLL_MIN, DELAY_SCROLL_MAX))


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


async def esperar_elemento(cdp: CDPSession, element_id: str, timeout: float = 10.0) -> bool:
    """Espera hasta que un elemento exista en el DOM (polling cada 0.5s).

    Recibe el ID crudo (sin escapar). El escape se aplica internamente.
    """
    escaped = safe_js_string(element_id)
    inicio = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - inicio) < timeout:
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


async def delay() -> None:
    """Pausa aleatoria entre acciones para simular comportamiento humano."""
    extra = DELAY_ACCION_BASE * random.uniform(0, DELAY_ACCION_VARIANZA)
    await asyncio.sleep(DELAY_ACCION_BASE + extra)


# ---------------------------------------------------------------------------
# Navegación de formularios
# ---------------------------------------------------------------------------

async def paso_formulario_1(cdp: CDPSession, ids: dict) -> None:
    """Formulario 1: Selección de provincia (Madrid)."""
    log("Formulario 1: seleccionando provincia Madrid")

    dropdown_id = safe_js_string(ids["dropdown_provincia"])
    valor = safe_js_string(ids["valor_madrid"])
    boton_id = safe_js_string(ids["boton_aceptar_f1"])

    if not await esperar_elemento(cdp, ids["dropdown_provincia"]):
        raise RuntimeError(f"Elemento #{ids['dropdown_provincia']} no apareció tras carga de página")

    await scroll_humano(cdp)
    await delay()

    await ejecutar_js(cdp, f"""
        document.getElementById('{dropdown_id}').value = '{valor}';
        document.getElementById('{dropdown_id}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await delay()
    log("Formulario 1: provincia seleccionada, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_2(cdp: CDPSession, ids: dict) -> None:
    """Formulario 2: Selección de trámite."""
    log("Formulario 2: seleccionando trámite")

    dropdown_id = safe_js_string(ids["dropdown_tramite"])
    valor = safe_js_string(ids["valor_tramite"])
    boton_id = safe_js_string(ids["boton_aceptar_f2"])

    if not await esperar_elemento(cdp, ids["dropdown_tramite"]):
        raise RuntimeError(f"Elemento #{ids['dropdown_tramite']} no apareció tras carga de página")

    await scroll_humano(cdp)
    await delay()

    await ejecutar_js(cdp, f"""
        document.getElementById('{dropdown_id}').value = '{valor}';
        document.getElementById('{dropdown_id}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await delay()
    log("Formulario 2: trámite seleccionado, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_3(cdp: CDPSession, ids: dict) -> None:
    """Formulario 3: Aviso informativo — click en Entrar."""
    log("Formulario 3: aceptando aviso")

    boton_id = safe_js_string(ids["boton_entrar_f3"])

    if not await esperar_elemento(cdp, ids["boton_entrar_f3"]):
        raise RuntimeError(f"Elemento #{ids['boton_entrar_f3']} no apareció tras carga de página")

    await scroll_humano(cdp)
    await delay()

    log("Formulario 3: aviso aceptado, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_4(cdp: CDPSession, ids: dict) -> None:
    """Formulario 4: Datos personales (NIE + nombre)."""
    log("Formulario 4: rellenando datos personales")
    await delay()

    input_nie = safe_js_string(ids["input_nie"])
    input_nombre = safe_js_string(ids["input_nombre"])
    boton_id = safe_js_string(ids["boton_aceptar_f4"])

    # Esperar a que el formulario esté disponible tras la carga
    if not await esperar_elemento(cdp, ids["input_nie"]):
        raise RuntimeError(f"Elemento #{ids['input_nie']} no apareció tras carga de página")

    # NIE
    nie_escaped = safe_js_string(NIE)
    await ejecutar_js(cdp, f"""
        document.getElementById('{input_nie}').value = '{nie_escaped}';
        document.getElementById('{input_nie}').dispatchEvent(new Event('input', {{ bubbles: true }}));
    """)

    await delay()

    # Nombre
    nombre_escaped = safe_js_string(NOMBRE)
    await ejecutar_js(cdp, f"""
        document.getElementById('{input_nombre}').value = '{nombre_escaped}';
        document.getElementById('{input_nombre}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await delay()
    log("Formulario 4: datos enviados, esperando carga...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


async def paso_formulario_5(cdp: CDPSession, ids: dict) -> None:
    """Formulario 5: Solicitar cita."""
    log("Formulario 5: solicitando cita")
    await delay()

    boton_id = safe_js_string(ids["boton_solicitar_cita"])

    if not await esperar_elemento(cdp, ids["boton_solicitar_cita"]):
        raise RuntimeError(f"Elemento #{ids['boton_solicitar_cita']} no apareció tras carga de página")

    log("Formulario 5: cita solicitada, esperando respuesta...")
    await click_y_esperar_carga(cdp, f"document.getElementById('{boton_id}').click();")


# ---------------------------------------------------------------------------
# Detección de disponibilidad
# ---------------------------------------------------------------------------

async def evaluar_estado_pagina(cdp: CDPSession, ids: dict) -> EstadoPagina:
    """Evalúa el estado de la página tras solicitar cita.

    Verifica múltiples señales para evitar falsos positivos:
    1. Presencia del texto "no hay citas" (case-insensitive, parcial).
    2. Existencia de elementos conocidos (botón Salir).
    3. Contenido mínimo en el body (página no vacía/error).
    4. URL coherente con el flujo del portal.
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
        # 4. Confirmar que el botón Salir existe (estamos en la página correcta)
        boton_salir = safe_js_string(ids["boton_salir_nocita"])
        boton_existe = await ejecutar_js(cdp, f"""
            document.getElementById('{boton_salir}') !== null;
        """)
        if boton_existe.get("value", False):
            return EstadoPagina.NO_HAY_CITAS
        # Texto presente pero sin botón Salir → estado incierto
        log("Estado: texto 'no hay citas' encontrado pero sin botón Salir")
        return EstadoPagina.DESCONOCIDO

    # 5. Verificar que la URL pertenece al flujo del portal
    url_check = await ejecutar_js(cdp, "window.location.href;")
    current_url = url_check.get("value", "")
    if "icpplus" not in current_url and "icpplustiem" not in current_url:
        log(f"Estado: URL inesperada: {current_url}")
        return EstadoPagina.DESCONOCIDO

    # 6. No se encontró "no hay citas" + URL válida + contenido sustancial → posible cita
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
        loop = asyncio.get_event_loop()
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


def intervalo_con_jitter(base: float) -> float:
    """Aplica ±15% de jitter a un intervalo para evitar cadencia periódica."""
    return base * random.uniform(0.85, 1.15)


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

async def ciclo_completo(cdp: CDPSession, ids: dict,
                         paso_hasta: int = 5) -> EstadoPagina | None:
    """Ejecuta formularios desde el paso 0 hasta paso_hasta (inclusive).

    Devuelve EstadoPagina con el resultado, o None si se detuvo antes
    del paso 5 (modo depuración).
    """
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
        await fn(cdp, ids)

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

            if resultado == EstadoPagina.HAY_CITAS:
                backoff.registrar_exito()
                print()
                print("=" * 60)
                log("*** CITA DISPONIBLE *** — Toma el control del navegador")
                print("=" * 60)
                print()

                # Solo alerta sonora — sin keep-alive para no generar tráfico
                await alerta_sonora()
            elif resultado == EstadoPagina.NO_HAY_CITAS:
                backoff.registrar_exito()
                log("Resultado: NO HAY CITAS")
                if await click_salir(cdp, ids):
                    skip_navegacion = True
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
