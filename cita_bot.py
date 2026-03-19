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
import sys
import time
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

load_dotenv()

NIE = os.getenv("NIE", "").strip()
NOMBRE = os.getenv("NOMBRE", "").strip()
INTERVALO_REINTENTO = float(os.getenv("INTERVALO_REINTENTO_SEGUNDOS", "60"))
DELAY_ACCION = float(os.getenv("DELAY_ENTRE_ACCIONES_SEGUNDOS", "1.0"))
TIMEOUT_PAGINA = float(os.getenv("TIMEOUT_CARGA_PAGINA_SEGUNDOS", "15"))

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}/json"

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
        except Exception:
            pass

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params

        fut = asyncio.get_event_loop().create_future()
        self._callbacks[msg_id] = fut
        await self._ws.send(json.dumps(payload))
        return await asyncio.wait_for(fut, timeout=TIMEOUT_PAGINA)

    async def wait_event(self, event: str, timeout: float | None = None):
        fut = asyncio.get_event_loop().create_future()
        self._events.setdefault(event, []).append(fut)
        t = timeout if timeout is not None else TIMEOUT_PAGINA
        return await asyncio.wait_for(fut, timeout=t)

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass


async def ejecutar_js(cdp: CDPSession, expression: str) -> dict:
    """Ejecuta JavaScript en la página y devuelve el resultado."""
    result = await cdp.send("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": False,
    })
    if "exceptionDetails" in result.get("result", {}):
        raise RuntimeError(f"Error JS: {result['result']['exceptionDetails']}")
    return result.get("result", {}).get("result", {})


async def navegar(cdp: CDPSession, url: str) -> None:
    """Navega a una URL y espera a que cargue."""
    await cdp.send("Page.enable")
    await cdp.send("Page.navigate", {"url": url})
    await cdp.wait_event("Page.loadEventFired", timeout=TIMEOUT_PAGINA)


async def esperar_carga(cdp: CDPSession) -> None:
    """Espera el evento de carga de página tras una navegación."""
    try:
        await cdp.wait_event("Page.loadEventFired", timeout=TIMEOUT_PAGINA)
    except asyncio.TimeoutError:
        log("Timeout esperando carga de página, continuando...")


async def delay() -> None:
    """Pausa entre acciones para simular comportamiento humano."""
    await asyncio.sleep(DELAY_ACCION)


# ---------------------------------------------------------------------------
# Navegación de formularios
# ---------------------------------------------------------------------------

async def paso_formulario_1(cdp: CDPSession, ids: dict) -> None:
    """Formulario 1: Selección de provincia (Madrid)."""
    log("Formulario 1: seleccionando provincia Madrid")
    await delay()

    dropdown_id = ids["dropdown_provincia"]
    valor = ids["valor_madrid"]
    boton_id = ids["boton_aceptar_f1"]

    await ejecutar_js(cdp, f"""
        document.getElementById('{dropdown_id}').value = '{valor}';
        document.getElementById('{dropdown_id}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await delay()
    await ejecutar_js(cdp, f"document.getElementById('{boton_id}').click();")
    log("Formulario 1: provincia seleccionada, esperando carga...")
    await esperar_carga(cdp)


async def paso_formulario_2(cdp: CDPSession, ids: dict) -> None:
    """Formulario 2: Selección de trámite."""
    log("Formulario 2: seleccionando trámite")
    await delay()

    dropdown_id = ids["dropdown_tramite"]
    valor = ids["valor_tramite"]
    boton_id = ids["boton_aceptar_f2"]

    await ejecutar_js(cdp, f"""
        document.getElementById('{dropdown_id}').value = '{valor}';
        document.getElementById('{dropdown_id}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await delay()
    await ejecutar_js(cdp, f"document.getElementById('{boton_id}').click();")
    log("Formulario 2: trámite seleccionado, esperando carga...")
    await esperar_carga(cdp)


async def paso_formulario_3(cdp: CDPSession, ids: dict) -> None:
    """Formulario 3: Aviso informativo — click en Entrar."""
    log("Formulario 3: aceptando aviso")
    await delay()

    boton_id = ids["boton_entrar_f3"]
    await ejecutar_js(cdp, f"document.getElementById('{boton_id}').click();")
    log("Formulario 3: aviso aceptado, esperando carga...")
    await esperar_carga(cdp)


async def paso_formulario_4(cdp: CDPSession, ids: dict) -> None:
    """Formulario 4: Datos personales (NIE + nombre)."""
    log("Formulario 4: rellenando datos personales")
    await delay()

    input_nie = ids["input_nie"]
    input_nombre = ids["input_nombre"]
    boton_id = ids["boton_aceptar_f4"]

    # NIE
    await ejecutar_js(cdp, f"""
        document.getElementById('{input_nie}').value = '{NIE}';
        document.getElementById('{input_nie}').dispatchEvent(new Event('input', {{ bubbles: true }}));
    """)

    await delay()

    # Nombre — escapar comillas simples por seguridad
    nombre_escaped = NOMBRE.replace("'", "\\'")
    await ejecutar_js(cdp, f"""
        document.getElementById('{input_nombre}').value = '{nombre_escaped}';
        document.getElementById('{input_nombre}').dispatchEvent(new Event('change', {{ bubbles: true }}));
    """)

    await delay()
    await ejecutar_js(cdp, f"document.getElementById('{boton_id}').click();")
    log("Formulario 4: datos enviados, esperando carga...")
    await esperar_carga(cdp)


async def paso_formulario_5(cdp: CDPSession, ids: dict) -> None:
    """Formulario 5: Solicitar cita."""
    log("Formulario 5: solicitando cita")
    await delay()

    boton_id = ids["boton_solicitar_cita"]
    await ejecutar_js(cdp, f"document.getElementById('{boton_id}').click();")
    log("Formulario 5: cita solicitada, esperando respuesta...")
    await esperar_carga(cdp)


# ---------------------------------------------------------------------------
# Detección de disponibilidad
# ---------------------------------------------------------------------------

async def hay_cita_disponible(cdp: CDPSession, ids: dict) -> bool:
    """Comprueba si la página muestra el mensaje de 'no hay citas'."""
    texto_no_citas = ids["texto_no_hay_citas"]
    result = await ejecutar_js(cdp, f"""
        document.body.innerText.includes('{texto_no_citas}');
    """)
    no_hay = result.get("value", False)
    return not no_hay


async def click_salir(cdp: CDPSession, ids: dict) -> None:
    """Click en botón Salir de la página sin citas."""
    boton_id = ids["boton_salir_nocita"]
    await ejecutar_js(cdp, f"document.getElementById('{boton_id}').click();")
    await esperar_carga(cdp)


# ---------------------------------------------------------------------------
# Alerta sonora
# ---------------------------------------------------------------------------

async def alerta_sonora() -> None:
    """Emite alerta sonora en bucle. Usa winsound en Windows, beep del sistema en otros."""
    try:
        import winsound
        while True:
            winsound.Beep(1000, 500)
            winsound.Beep(1500, 500)
            winsound.Beep(2000, 500)
            await asyncio.sleep(1)
    except ImportError:
        # Linux/Mac: beep del sistema
        while True:
            print("\a", end="", flush=True)
            await asyncio.sleep(1)


async def mantener_sesion(cdp: CDPSession) -> None:
    """Keep-alive: lee un elemento del DOM cada 30s para evitar timeout de sesión."""
    while True:
        try:
            await ejecutar_js(cdp, "document.title;")
        except Exception:
            pass
        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

async def ciclo_completo(cdp: CDPSession, ids: dict) -> bool:
    """Ejecuta un ciclo completo de formularios. Devuelve True si hay cita."""
    await paso_formulario_1(cdp, ids)
    await paso_formulario_2(cdp, ids)
    await paso_formulario_3(cdp, ids)
    await paso_formulario_4(cdp, ids)
    await paso_formulario_5(cdp, ids)

    if await hay_cita_disponible(cdp, ids):
        return True

    log("Resultado: NO HAY CITAS")
    return False


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

    log_info(f"Configuración cargada — NIE: {NIE[:3]}*** / Nombre: {NOMBRE.split()[0]}***")
    log_info(f"Intervalo reintento: {INTERVALO_REINTENTO}s / Delay acciones: {DELAY_ACCION}s / Timeout: {TIMEOUT_PAGINA}s")

    # Conectar a Brave
    log_info("Conectando a Brave via CDP...")
    ws_url = await obtener_ws_url()
    log_info(f"WebSocket: {ws_url}")

    import websockets
    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        cdp = CDPSession(ws)
        await cdp.start()
        await cdp.send("Page.enable")

        log_info("Conectado a Brave. Iniciando bucle de búsqueda de cita...")

        while True:
            _intento += 1

            try:
                # Navegar al inicio
                log("Navegando a URL de inicio...")
                await navegar(cdp, url_inicio)
                log("Página cargada")

                # Ciclo de formularios
                cita_encontrada = await ciclo_completo(cdp, ids)

                if cita_encontrada:
                    print()
                    print("=" * 60)
                    log("*** CITA DISPONIBLE *** — Toma el control del navegador")
                    print("=" * 60)
                    print()

                    # Mantener sesión + alerta en paralelo
                    await asyncio.gather(
                        alerta_sonora(),
                        mantener_sesion(cdp),
                    )
                else:
                    log(f"Reintentando en {INTERVALO_REINTENTO}s...")
                    await click_salir(cdp, ids)
                    await asyncio.sleep(INTERVALO_REINTENTO)

            except asyncio.TimeoutError:
                log("Timeout en carga de página. Reiniciando ciclo...")
                await asyncio.sleep(5)

            except RuntimeError as e:
                log(f"Error JS: {e}")
                log("Reiniciando ciclo en 10s...")
                await asyncio.sleep(10)

            except Exception as e:
                log(f"Error inesperado: {type(e).__name__}: {e}")
                log("Reiniciando ciclo en 10s...")
                await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{ts}] Script detenido por el usuario (Ctrl+C). Brave sigue abierto.")
