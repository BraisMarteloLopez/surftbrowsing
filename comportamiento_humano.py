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
    """Simula scroll humano hacia abajo con eventos mouseWheel nativos.

    Usa Input.dispatchMouseEvent con type mouseWheel en vez de JS scrollBy,
    lo cual genera rastro de cursor real en el navegador. Incluye
    micro-movimientos del ratón entre pasos de scroll.
    """
    pasos = random.randint(2, 4)
    # Posición aproximada del ratón (sin estado persistente en standalone)
    x = random.randint(300, 700)
    y = random.randint(200, 500)

    for i in range(pasos):
        distancia = random.randint(100, 300)
        try:
            await cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": 0,
                "deltaY": distancia,
            }, timeout=TIMEOUT_JS)
        except Exception:
            pass

        # Micro-movimiento entre pasos de scroll
        if i < pasos - 1:
            x += random.randint(-8, 8)
            y += random.randint(-5, 5)
            try:
                await cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved",
                    "x": max(0, x),
                    "y": max(0, y),
                }, timeout=TIMEOUT_JS)
            except Exception:
                pass

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
# Clase SimuladorHumano — estado encapsulado para formularios
# ---------------------------------------------------------------------------

class SimuladorHumano:
    """Encapsula el estado del ratón y viewport para simular comportamiento humano.

    Reemplaza el estado global en window.__mouse_pos por estado Python-side.
    Los formularios reciben una instancia en vez de llamar funciones sueltas.
    """

    def __init__(self, cdp: CDPSession):
        self.cdp = cdp
        self.mouse_x: int = random.randint(100, 800)
        self.mouse_y: int = random.randint(100, 400)
        self.viewport: tuple[int, int] = (1024, 768)

    async def actualizar_viewport(self) -> None:
        """Lee dimensiones reales del viewport via CDP."""
        result = await ejecutar_js(self.cdp, "[window.innerWidth, window.innerHeight];")
        dims = result.get("value", [1024, 768])
        if isinstance(dims, list) and len(dims) == 2:
            self.viewport = (dims[0], dims[1])

    async def mover_a(self, x_destino: int, y_destino: int,
                      pasos: int | None = None) -> None:
        """Trayectoria curva hacia destino. Actualiza self.mouse_x/y.

        Usa smoothstep easing con desviaciones aleatorias para simular
        movimiento humano. Estado del ratón se mantiene en Python.
        """
        if pasos is None:
            pasos = random.randint(5, 12)

        x_actual = self.mouse_x
        y_actual = self.mouse_y

        for i in range(pasos):
            t = (i + 1) / pasos
            ease = t * t * (3 - 2 * t)  # smoothstep

            desviacion_x = random.randint(-15, 15) if i < pasos - 1 else 0
            desviacion_y = random.randint(-10, 10) if i < pasos - 1 else 0

            x = int(x_actual + (x_destino - x_actual) * ease + desviacion_x)
            y = int(y_actual + (y_destino - y_actual) * ease + desviacion_y)

            try:
                await self.cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved",
                    "x": max(0, x),
                    "y": max(0, y),
                }, timeout=TIMEOUT_JS)
            except Exception:
                break

            pausa = random.uniform(0.01, 0.04)
            if i < 2 or i > pasos - 3:
                pausa *= 2
            await asyncio.sleep(pausa)

        self.mouse_x = x_destino
        self.mouse_y = y_destino

    async def _obtener_posicion_elemento(self, element_id: str) -> dict | None:
        """Obtiene posición central del elemento con variación aleatoria."""
        escaped = safe_js_string(element_id)
        result = await ejecutar_js(self.cdp, f"""
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
            return pos
        return None

    async def mover_a_elemento(self, element_id: str) -> None:
        """Obtiene posición del elemento y mueve el ratón hasta él."""
        pos = await self._obtener_posicion_elemento(element_id)
        if pos:
            await self.mover_a(pos["x"], pos["y"])

    async def click_elemento(self, element_id: str) -> None:
        """Mueve el ratón al elemento, hace click CDP nativo, y pausa como un humano.

        El click CDP (mousePressed + mouseReleased) genera eventos con
        isTrusted=true, incluyendo focus nativo en el elemento. La pausa
        posterior simula el tiempo que un humano tarda en leer el campo
        antes de interactuar con él.
        """
        pos = await self._obtener_posicion_elemento(element_id)
        if not pos:
            return

        await self.mover_a(pos["x"], pos["y"])

        # Click CDP nativo: mousePressed + mouseReleased = focus isTrusted
        try:
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": pos["x"], "y": pos["y"],
                "button": "left",
                "clickCount": 1,
            }, timeout=TIMEOUT_JS)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": pos["x"], "y": pos["y"],
                "button": "left",
                "clickCount": 1,
            }, timeout=TIMEOUT_JS)
        except Exception:
            pass

        # Pausa humana: tiempo mirando el campo tras hacer focus
        await asyncio.sleep(random.uniform(0.4, 1.2))

    async def movimiento_idle(self) -> None:
        """1-3 movimientos aleatorios por el viewport (simula lectura)."""
        await self.actualizar_viewport()
        ancho, alto = self.viewport
        movimientos = random.randint(1, 3)
        for _ in range(movimientos):
            x = random.randint(int(ancho * 0.1), int(ancho * 0.9))
            y = random.randint(int(alto * 0.1), int(alto * 0.8))
            await self.mover_a(x, y)
            await asyncio.sleep(random.uniform(0.3, 1.0))

    async def scroll(self) -> None:
        """Scroll humanizado 2-4 pasos via eventos mouseWheel nativos.

        Usa la posición actual del ratón para generar eventos mouseWheel
        realistas. Incluye micro-movimientos entre pasos de scroll,
        como haría un humano que no mantiene la mano perfectamente quieta.
        """
        pasos = random.randint(2, 4)
        for i in range(pasos):
            distancia = random.randint(100, 300)
            try:
                await self.cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseWheel",
                    "x": self.mouse_x,
                    "y": self.mouse_y,
                    "deltaX": 0,
                    "deltaY": distancia,
                }, timeout=TIMEOUT_JS)
            except Exception:
                pass

            # Micro-movimiento entre pasos de scroll
            if i < pasos - 1:
                self.mouse_x += random.randint(-8, 8)
                self.mouse_y += random.randint(-5, 5)
                self.mouse_x = max(0, self.mouse_x)
                self.mouse_y = max(0, self.mouse_y)
                try:
                    await self.cdp.send("Input.dispatchMouseEvent", {
                        "type": "mouseMoved",
                        "x": self.mouse_x,
                        "y": self.mouse_y,
                    }, timeout=TIMEOUT_JS)
                except Exception:
                    pass

            await asyncio.sleep(random.uniform(DELAY_SCROLL_MIN, DELAY_SCROLL_MAX))

    async def delay_activo(self, base: float = DELAY_ACCION_BASE,
                           varianza: float = DELAY_ACCION_VARIANZA) -> None:
        """Espera humanizada CON movimiento de ratón de fondo.

        Lanza _movimiento_lectura como tarea concurrente que mueve el ratón
        suavemente mientras el delay transcurre. La tarea se cancela
        automáticamente cuando el delay termina.
        """
        extra = base * random.uniform(0, varianza)
        duracion = base + extra
        tarea_raton = asyncio.create_task(self._movimiento_lectura(duracion))
        try:
            await asyncio.sleep(duracion)
        finally:
            tarea_raton.cancel()
            try:
                await tarea_raton
            except asyncio.CancelledError:
                pass

    async def pausa_lectura(self) -> None:
        """Pausa entre pasos de formulario con movimiento de fondo."""
        duracion = random.uniform(PAUSA_ENTRE_PASOS_MIN, PAUSA_ENTRE_PASOS_MAX)
        tarea_raton = asyncio.create_task(self._movimiento_lectura(duracion))
        try:
            await asyncio.sleep(duracion)
        finally:
            tarea_raton.cancel()
            try:
                await tarea_raton
            except asyncio.CancelledError:
                pass

    async def pausa_extra(self, probabilidad: float = 0.3) -> None:
        """Con probabilidad dada, añade una pausa extra de 1-4s con movimiento."""
        if random.random() < probabilidad:
            duracion = random.uniform(1.0, 4.0)
            tarea_raton = asyncio.create_task(self._movimiento_lectura(duracion))
            try:
                await asyncio.sleep(duracion)
            finally:
                tarea_raton.cancel()
                try:
                    await tarea_raton
                except asyncio.CancelledError:
                    pass

    # --- Secuencia pre-acción con orden variable ---

    async def secuencia_pre_accion(self, element_id: str | None = None,
                                   focus: bool = False) -> None:
        """Ejecuta una secuencia pre-acción con orden variable.

        Elige aleatoriamente entre varias combinaciones de acciones
        preparatorias, de modo que no todos los pasos del formulario
        tengan exactamente el mismo patrón temporal.

        Siempre incluye al menos un delay_activo. Si se especifica
        element_id, mueve el ratón al elemento al final. Si focus=True,
        hace click CDP nativo sobre el elemento (genera focus isTrusted=true
        con pausa humana). Usar focus=True solo para inputs/selects, NO
        para botones que ejecuten navegación.
        """
        acciones_posibles = [
            ("idle", lambda: self.movimiento_idle()),
            ("scroll", lambda: self.scroll()),
            ("delay", lambda: self.delay_activo()),
            ("pausa", lambda: self.pausa_extra()),
        ]

        seleccion = random.sample(acciones_posibles, k=random.randint(2, 4))
        if not any(nombre == "delay" for nombre, _ in seleccion):
            seleccion.append(("delay", lambda: self.delay_activo()))
        random.shuffle(seleccion)

        for _nombre, accion in seleccion:
            await accion()

        if element_id:
            if focus:
                await self.click_elemento(element_id)
            else:
                await self.mover_a_elemento(element_id)

    # --- Movimiento de fondo durante pausas ---

    async def _movimiento_lectura(self, duracion: float) -> None:
        """Movimiento continuo que simula ojos + mano durante lectura.

        Patrones posibles (se elige uno aleatoriamente):
        1. Reposo activo: micro-movimientos en una zona reducida (±20px)
        2. Lectura horizontal: zigzag lento izquierda-derecha, bajando poco a poco
        3. Exploración: movimientos suaves entre zonas de interés de la página
        4. Drift: movimiento muy lento en una dirección con correcciones
        """
        patron = random.choice(["reposo", "lectura", "exploracion", "drift"])
        loop = asyncio.get_event_loop()
        inicio = loop.time()

        while loop.time() - inicio < duracion:
            if patron == "reposo":
                dx = random.randint(-20, 20)
                dy = random.randint(-15, 15)
                destino_x = max(0, self.mouse_x + dx)
                destino_y = max(0, self.mouse_y + dy)
                await self.mover_a(destino_x, destino_y, pasos=random.randint(2, 4))
                await asyncio.sleep(random.uniform(0.5, 2.0))

            elif patron == "lectura":
                ancho = self.viewport[0]
                x_inicio = int(ancho * 0.15)
                x_fin = int(ancho * random.uniform(0.6, 0.85))
                y_base = self.mouse_y
                await self.mover_a(x_inicio, y_base, pasos=random.randint(3, 6))
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await self.mover_a(x_fin, y_base + random.randint(-5, 5),
                                   pasos=random.randint(8, 15))
                await asyncio.sleep(random.uniform(0.2, 0.6))
                self.mouse_y += random.randint(15, 30)

            elif patron == "exploracion":
                x = random.randint(int(self.viewport[0] * 0.1),
                                   int(self.viewport[0] * 0.9))
                y = random.randint(int(self.viewport[1] * 0.1),
                                   int(self.viewport[1] * 0.8))
                await self.mover_a(x, y, pasos=random.randint(5, 10))
                await asyncio.sleep(random.uniform(0.8, 2.5))

            elif patron == "drift":
                dx = random.uniform(-0.5, 0.5)
                dy = random.uniform(-0.3, 0.3)
                for _ in range(random.randint(5, 15)):
                    self.mouse_x = max(0, int(self.mouse_x + dx * 10))
                    self.mouse_y = max(0, int(self.mouse_y + dy * 10))
                    try:
                        await self.cdp.send("Input.dispatchMouseEvent", {
                            "type": "mouseMoved",
                            "x": self.mouse_x,
                            "y": self.mouse_y,
                        }, timeout=TIMEOUT_JS)
                    except Exception:
                        return
                    await asyncio.sleep(random.uniform(0.1, 0.4))


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
