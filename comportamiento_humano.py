"""Comportamiento humano simulado y defensas anti-detección.

Contiene toda la lógica que hace que el bot se comporte de forma más humana:
movimientos de ratón, delays, scroll, pausas aleatorias, detección WAF,
y limpieza de caché. Separado del flujo de formularios para facilitar
la evolución independiente de ambas capas.
"""

import asyncio
import os
import random
from urllib.parse import urlparse

from dotenv import load_dotenv

from cdp_helpers import (
    CDPSession, ejecutar_js, safe_js_string, TIMEOUT_JS,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración de delays (desde .env)
# ---------------------------------------------------------------------------

# Acciones de formulario (click, select, etc.)
DELAY_ACCION_BASE = float(os.getenv("DELAY_ACCION_BASE", "2.0"))
DELAY_ACCION_VARIANZA = max(float(os.getenv("DELAY_ACCION_VARIANZA", "0.8")), 0.0)

# Scroll humano entre pasos de scroll
DELAY_SCROLL_MIN = float(os.getenv("DELAY_SCROLL_MIN", "0.8"))
DELAY_SCROLL_MAX = float(os.getenv("DELAY_SCROLL_MAX", "2.0"))

# Lectura de página antes de evaluar resultado
DELAY_EVALUACION_MIN = float(os.getenv("DELAY_EVALUACION_MIN", "2.0"))
DELAY_EVALUACION_MAX = float(os.getenv("DELAY_EVALUACION_MAX", "5.0"))

# Pausa entre pasos de formulario (simula lectura/pensamiento)
PAUSA_ENTRE_PASOS_MIN = float(os.getenv("PAUSA_ENTRE_PASOS_MIN", "2.0"))
PAUSA_ENTRE_PASOS_MAX = float(os.getenv("PAUSA_ENTRE_PASOS_MAX", "5.0"))

# WAF backoff
WAF_BACKOFF_BASE = float(os.getenv("WAF_BACKOFF_BASE_SEGUNDOS", "300"))
WAF_BACKOFF_MAX = float(os.getenv("WAF_BACKOFF_MAX_SEGUNDOS", "900"))
WAF_BACKOFF_UMBRAL_ALERTA = int(os.getenv("WAF_BACKOFF_UMBRAL_ALERTA", "3"))


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

class WafBanError(Exception):
    """Excepción lanzada cuando se detecta un bloqueo WAF."""
    pass


# ---------------------------------------------------------------------------
# PLAN: Detección de eventos focus/blur en formularios
# ---------------------------------------------------------------------------
# Muchos portales web (incluido ICP) pueden tener listeners de focus/blur
# en campos de formulario para tracking de comportamiento del usuario.
# Un bot que solo hace .value = "X" nunca dispara estos eventos, lo cual
# es detectable.
#
# Implementación futura en 3 fases:
#
# Fase 1 — Auditoría de event listeners (sin cambios funcionales):
#   - Antes de interactuar con un campo, ejecutar JS para listar sus listeners:
#       getEventListeners(document.getElementById('campo'))
#     Nota: getEventListeners solo está disponible en consola de DevTools,
#     no en Runtime.evaluate. Alternativa viable:
#       cdp.send("DOMDebugger.getEventListeners", {"objectId": ...})
#   - Logear qué campos tienen focus, blur, input, change, keydown, keyup.
#   - Esto permite entender qué eventos espera el portal sin cambiar nada.
#
# Fase 2 — Simulación de focus/blur para campos con listeners:
#   - Para cada campo que tenga listeners de focus:
#       1. mover_raton_a_elemento(cdp, campo_id)
#       2. cdp.send("Input.dispatchMouseEvent", type="mousePressed", ...)
#       3. El click activa focus de forma natural.
#       4. Pausa de lectura/escritura (delay humanizado).
#       5. Rellenar campo con Input.dispatchKeyEvent (char a char).
#       6. Tab o click en siguiente campo → dispara blur del anterior.
#   - Para campos SIN listeners de focus: mantener el enfoque actual
#     (.value = ... + dispatchEvent) que es más rápido y suficiente.
#
# Fase 3 — Simulación de Tab entre campos:
#   - Detectar el tabindex natural del formulario.
#   - En lugar de click directo, usar Input.dispatchKeyEvent con key="Tab"
#     para navegar entre campos como haría un usuario con teclado.
#   - Alternar aleatoriamente entre Tab y click para variar el patrón.
#   - Incluir shift+Tab ocasional (corregir → volver atrás).
#
# Prioridad: Fase 1 es de bajo riesgo y alta información. Implementar
# primero para tomar decisiones informadas sobre Fases 2 y 3.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Movimiento de ratón
# ---------------------------------------------------------------------------

async def mover_raton(cdp: CDPSession, x_destino: int, y_destino: int,
                      pasos: int | None = None) -> None:
    """Mueve el ratón desde su posición actual hasta (x_destino, y_destino).

    Simula una trayectoria humana con múltiples puntos intermedios,
    velocidad variable (más rápido en el medio, más lento al inicio/final),
    y pequeñas desviaciones aleatorias del camino recto.

    Solo genera eventos mouseMoved — nunca hace click.
    """
    if pasos is None:
        pasos = random.randint(5, 12)

    # Obtener posición actual del ratón (o empezar desde un punto aleatorio)
    result = await ejecutar_js(cdp, """
        (function() {
            var pos = window.__mouse_pos || {x: Math.floor(Math.random() * 800) + 100, y: Math.floor(Math.random() * 400) + 100};
            return pos;
        })();
    """)
    pos = result.get("value", {})
    x_actual = pos.get("x", random.randint(100, 800))
    y_actual = pos.get("y", random.randint(100, 400))

    for i in range(pasos):
        # Progreso no lineal: ease-in-out (más lento al inicio/final)
        t = (i + 1) / pasos
        ease = t * t * (3 - 2 * t)  # smoothstep

        # Punto intermedio con desviación aleatoria del camino recto
        desviacion_x = random.randint(-15, 15) if i < pasos - 1 else 0
        desviacion_y = random.randint(-10, 10) if i < pasos - 1 else 0

        x = int(x_actual + (x_destino - x_actual) * ease + desviacion_x)
        y = int(y_actual + (y_destino - y_actual) * ease + desviacion_y)

        try:
            await cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": max(0, x),
                "y": max(0, y),
            }, timeout=TIMEOUT_JS)
        except Exception:
            return  # Si falla, no es crítico

        # Pausa variable entre movimientos (más corta en el medio de la trayectoria)
        pausa = random.uniform(0.01, 0.04)
        if i < 2 or i > pasos - 3:
            pausa *= 2  # Más lento al inicio/final
        await asyncio.sleep(pausa)

    # Guardar posición final para la siguiente llamada
    await ejecutar_js(cdp, f"window.__mouse_pos = {{x: {x_destino}, y: {y_destino}}};")


async def movimiento_raton_aleatorio(cdp: CDPSession) -> None:
    """Realiza 1-3 movimientos de ratón aleatorios por la página visible.

    Simula a un humano que mueve el ratón mientras lee/piensa.
    Los destinos son puntos aleatorios dentro del viewport.
    """
    movimientos = random.randint(1, 3)
    for _ in range(movimientos):
        # Obtener dimensiones del viewport
        result = await ejecutar_js(cdp, "[window.innerWidth, window.innerHeight];")
        dims = result.get("value", [1024, 768])
        if isinstance(dims, list) and len(dims) == 2:
            ancho, alto = dims
        else:
            ancho, alto = 1024, 768

        # Destino aleatorio con margen del viewport
        x = random.randint(int(ancho * 0.1), int(ancho * 0.9))
        y = random.randint(int(alto * 0.1), int(alto * 0.8))

        await mover_raton(cdp, x, y)
        # Pausa de "lectura" entre movimientos
        await asyncio.sleep(random.uniform(0.3, 1.0))


async def mover_raton_a_elemento(cdp: CDPSession, element_id: str) -> None:
    """Mueve el ratón hacia la posición de un elemento del DOM.

    Obtiene las coordenadas del centro del elemento via getBoundingClientRect
    y mueve el ratón hasta ahí con trayectoria humana.
    """
    escaped = safe_js_string(element_id)
    result = await ejecutar_js(cdp, f"""
        (function() {{
            var el = document.getElementById('{escaped}');
            if (!el) return null;
            var rect = el.getBoundingClientRect();
            return {{
                x: Math.floor(rect.left + rect.width / 2 + (Math.random() * 10 - 5)),
                y: Math.floor(rect.top + rect.height / 2 + (Math.random() * 6 - 3))
            }};
        }})();
    """)
    pos = result.get("value")
    if pos and isinstance(pos, dict) and "x" in pos and "y" in pos:
        await mover_raton(cdp, pos["x"], pos["y"])


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------

async def scroll_humano(cdp: CDPSession) -> None:
    """Simula scroll humano hacia abajo: 2-4 pasos con distancia y delay aleatorios."""
    pasos = random.randint(2, 4)
    for _ in range(pasos):
        distancia = random.randint(100, 300)
        await ejecutar_js(cdp, f"window.scrollBy({{ top: {distancia}, behavior: 'smooth' }});")
        await asyncio.sleep(random.uniform(DELAY_SCROLL_MIN, DELAY_SCROLL_MAX))


# ---------------------------------------------------------------------------
# Delays y pausas
# ---------------------------------------------------------------------------

async def delay() -> None:
    """Pausa aleatoria entre acciones para simular comportamiento humano."""
    extra = DELAY_ACCION_BASE * random.uniform(0, DELAY_ACCION_VARIANZA)
    await asyncio.sleep(DELAY_ACCION_BASE + extra)


async def pausa_entre_pasos() -> None:
    """Pausa más larga entre pasos de formulario para simular lectura/pensamiento."""
    await asyncio.sleep(random.uniform(PAUSA_ENTRE_PASOS_MIN, PAUSA_ENTRE_PASOS_MAX))


async def pausa_extra_aleatoria() -> None:
    """Con un 30% de probabilidad, añade una pausa extra de 1-4s.

    Simula momentos en los que un humano se distrae, relee, o duda.
    """
    if random.random() < 0.3:
        await asyncio.sleep(random.uniform(1.0, 4.0))


def intervalo_con_jitter(base: float) -> float:
    """Aplica ±15% de jitter a un intervalo para evitar cadencia periódica."""
    return base * random.uniform(0.85, 1.15)


# ---------------------------------------------------------------------------
# Detección WAF
# ---------------------------------------------------------------------------

async def detectar_waf(cdp: CDPSession) -> bool:
    """Detecta si la página actual es un bloqueo de WAF (F5 BIG-IP, etc.).

    Requiere AMBAS condiciones para evitar falsos positivos:
    1. "The requested URL was rejected" (mensaje principal del WAF)
    2. "Your support ID is" (identificador de sesión del WAF)

    Ambos textos son exclusivos de la página de rechazo WAF y no aparecen
    en ninguna página legítima del portal ICP (ni formularios, ni citas,
    ni errores del portal).
    """
    try:
        result = await ejecutar_js(cdp, "document.body.innerText;")
        texto = result.get("value", "")
        if not texto:
            return False
        texto_lower = texto.lower()
        return (
            "the requested url was rejected" in texto_lower
            and "your support id is" in texto_lower
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Limpieza de datos del navegador
# ---------------------------------------------------------------------------

async def limpiar_datos_navegador(cdp: CDPSession, origin: str) -> None:
    """Limpia caché HTTP y storage del navegador para un origin, sin tocar cookies.

    Usa CDP Storage.clearDataForOrigin para borrar:
    - Caché HTTP (appcache, cache_storage)
    - localStorage, sessionStorage, IndexedDB, WebSQL
    - Service workers

    NO borra cookies para no perder la sesión activa.
    """
    parsed = urlparse(origin)
    clean_origin = f"{parsed.scheme}://{parsed.netloc}"

    storage_types = (
        "appcache,"
        "cache_storage,"
        "indexeddb,"
        "local_storage,"
        "service_workers,"
        "websql"
    )

    try:
        await cdp.send("Storage.clearDataForOrigin", {
            "origin": clean_origin,
            "storageTypes": storage_types,
        }, timeout=TIMEOUT_JS)
    except Exception:
        pass  # No es crítico, el caller loguea si necesita

    # Limpiar también la caché HTTP global del navegador
    try:
        await cdp.send("Network.enable", timeout=TIMEOUT_JS)
        await cdp.send("Network.clearBrowserCache", timeout=TIMEOUT_JS)
    except Exception:
        pass  # No es crítico
