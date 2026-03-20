"""Helpers CDP genéricos — CDPSession, ejecutar_js, y utilidades de bajo nivel.

Este módulo contiene la capa de comunicación con Chrome DevTools Protocol (CDP)
sin lógica de negocio del bot ni comportamiento anti-detección.
"""

import asyncio
import json
import os
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración CDP
# ---------------------------------------------------------------------------

TIMEOUT_PAGINA = float(os.getenv("TIMEOUT_CARGA_PAGINA_SEGUNDOS", "15"))

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}/json"

# Timeouts diferenciados
TIMEOUT_NAVEGACION = TIMEOUT_PAGINA  # 15s — para Page.navigate + load
TIMEOUT_JS = 5.0                     # 5s — para Runtime.evaluate simples


# ---------------------------------------------------------------------------
# Logging (mínimo, requerido por CDPSession)
# ---------------------------------------------------------------------------

def log_info(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


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


# ---------------------------------------------------------------------------
# CDP Session
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

        fut = asyncio.get_running_loop().create_future()
        self._callbacks[msg_id] = fut
        await self._ws.send(json.dumps(payload))
        t = timeout if timeout is not None else TIMEOUT_PAGINA
        return await asyncio.wait_for(fut, timeout=t)

    def pre_wait_event(self, event: str) -> asyncio.Future:
        """Pre-registra un Future para un evento ANTES de que ocurra."""
        if not self._alive:
            raise ConnectionError("Sesión CDP desconectada")
        fut = asyncio.get_running_loop().create_future()
        self._events.setdefault(event, []).append(fut)
        return fut

    async def wait_event(self, event: str, timeout: float | None = None):
        fut = asyncio.get_running_loop().create_future()
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
