"""Capa CDP v2 — CDPSession, ejecutar_js, y utilidades de bajo nivel.

Reutiliza la lógica validada de old_cdp_helpers.py sin cambios funcionales.
Único punto de contacto con Chrome DevTools Protocol via WebSocket.
"""

import asyncio
import json
import os
import time
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración CDP
# ---------------------------------------------------------------------------

TIMEOUT_PAGINA = float(os.getenv("TIMEOUT_CARGA_PAGINA_SEGUNDOS", "15"))
TIMEOUT_ESPERA_ELEMENTO = float(os.getenv("TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS", "10"))
WAIT_ELEMENT_POLL_S = float(os.getenv("WAIT_ELEMENT_POLL_MS", "300")) / 1000.0

CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
CDP_URL = f"http://localhost:{CDP_PORT}/json"

TIMEOUT_JS = 5.0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_info(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def safe_js_string(value: str) -> str:
    """Escapa un string para interpolación segura dentro de un literal JS."""
    return (
        value
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )


def css_escape_id(raw_id: str) -> str:
    """Escapa un ID para uso en selector CSS.

    Ejemplo: 'tramiteGrupo[0]' → '#tramiteGrupo\\[0\\]'
    """
    escaped = raw_id.replace("[", "\\[").replace("]", "\\]")
    return f"#{escaped}"


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
            f"No se pudo conectar al navegador en localhost:{CDP_PORT}.\n"
            f"Lanza el navegador con: --remote-debugging-port={CDP_PORT}\n"
            f"Error: {e}"
        )

    for tab in tabs:
        if tab.get("type") == "page":
            ws_url = tab.get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url

    raise ConnectionError(
        "Navegador con CDP activo pero sin pestañas abiertas.\n"
        "Abre al menos una pestaña."
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


# ---------------------------------------------------------------------------
# Ejecución de JavaScript
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Esperas de seguridad (v2 — mejoradas)
# ---------------------------------------------------------------------------

class ElementoNoEncontrado(Exception):
    """El elemento no apareció en el DOM dentro del timeout."""
    pass


class TimeoutCargaPagina(Exception):
    """La página no terminó de cargar dentro del timeout."""
    pass


async def esperar_elemento(cdp: CDPSession, selector: str,
                           timeout: float | None = None) -> dict:
    """Espera hasta que un elemento exista en DOM, sea visible e interactuable.

    Args:
        selector: Selector CSS (e.g. "#form", "#btnAceptar")
        timeout: Segundos máximos de espera (default: TIMEOUT_ESPERA_ELEMENTO)

    Returns:
        dict con {x, y, width, height} del bounding box del elemento.

    Raises:
        ElementoNoEncontrado si el timeout se agota.
    """
    if timeout is None:
        timeout = TIMEOUT_ESPERA_ELEMENTO
    escaped = safe_js_string(selector)

    inicio = time.monotonic()
    while (time.monotonic() - inicio) < timeout:
        result = await ejecutar_js(cdp, f"""
            (function() {{
                var el = document.querySelector('{escaped}');
                if (!el) return null;
                var style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return null;
                if (el.disabled) return null;
                var rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return null;
                return {{
                    x: Math.floor(rect.left + rect.width / 2),
                    y: Math.floor(rect.top + rect.height / 2),
                    width: Math.floor(rect.width),
                    height: Math.floor(rect.height)
                }};
            }})();
        """)
        val = result.get("value")
        if val and isinstance(val, dict) and "x" in val:
            return val
        await asyncio.sleep(WAIT_ELEMENT_POLL_S)

    raise ElementoNoEncontrado(
        f"Elemento '{selector}' no encontrado tras {timeout}s"
    )


async def esperar_carga_pagina(cdp: CDPSession,
                               timeout: float | None = None) -> None:
    """Espera Page.loadEventFired con timeout configurable.

    Raises:
        TimeoutCargaPagina si el timeout se agota.
    """
    if timeout is None:
        timeout = TIMEOUT_PAGINA
    try:
        await cdp.wait_event("Page.loadEventFired", timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutCargaPagina(f"Página no cargó en {timeout}s")


# ---------------------------------------------------------------------------
# Detección WAF (reutilizada de v1 — validada)
# ---------------------------------------------------------------------------

class WafBanError(Exception):
    """Excepción lanzada cuando se detecta un bloqueo WAF."""
    pass


async def detectar_waf(cdp: CDPSession) -> bool:
    """Detecta si la página actual es un bloqueo WAF o rate limit (429)."""
    try:
        result = await ejecutar_js(
            cdp,
            "({title: document.title, body: document.body.innerText});",
        )
        obj = result.get("value", result)
        if isinstance(obj, dict):
            titulo = (obj.get("title") or "").lower()
            texto_lower = (obj.get("body") or "").lower()
        else:
            titulo = ""
            texto_lower = str(obj).lower()

        # F5 BIG-IP WAF
        if ("the requested url was rejected" in texto_lower
                and "your support id is" in texto_lower):
            return True

        # HTTP 429 Too Many Requests
        if "429" in titulo and "too many" in titulo:
            return True
        if "too many requests" in texto_lower:
            return True

        return False
    except Exception:
        return False
