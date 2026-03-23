"""Motor de comportamiento humano v2 — Primitivas + Fases.

Cada fase replica la secuencia exacta de micro-acciones que un humano
realiza en cada página del formulario ICP. Todos los tiempos son
configurables via .env y modulados por la Personalidad del ciclo.
"""

import asyncio
import os
import random
import time

from dotenv import load_dotenv

from cdp_core import (
    CDPSession, ejecutar_js, safe_js_string, css_escape_id,
    esperar_elemento, esperar_carga_pagina, detectar_waf,
    WafBanError, ElementoNoEncontrado, TimeoutCargaPagina,
    TIMEOUT_JS, TIMEOUT_PAGINA, log_info,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Configuración de tiempos (TODO de .env con defaults)
# ---------------------------------------------------------------------------

def _env_float(key: str, default: str) -> float:
    return float(os.getenv(key, default))


def _env_int(key: str, default: str) -> int:
    return int(os.getenv(key, default))


# Aterrizaje
ATERRIZAJE_PAUSA_MIN = _env_float("ATERRIZAJE_PAUSA_MIN", "1.0")
ATERRIZAJE_PAUSA_MAX = _env_float("ATERRIZAJE_PAUSA_MAX", "3.0")
ATERRIZAJE_MICRO_MOV_MIN = _env_int("ATERRIZAJE_MICRO_MOV_MIN", "1")
ATERRIZAJE_MICRO_MOV_MAX = _env_int("ATERRIZAJE_MICRO_MOV_MAX", "2")
ATERRIZAJE_MOV_RANGO_X = _env_int("ATERRIZAJE_MOV_RANGO_X", "80")
ATERRIZAJE_MOV_RANGO_Y = _env_int("ATERRIZAJE_MOV_RANGO_Y", "50")
ATERRIZAJE_MOV_DURACION_MIN = _env_float("ATERRIZAJE_MOV_DURACION_MIN", "0.2")
ATERRIZAJE_MOV_DURACION_MAX = _env_float("ATERRIZAJE_MOV_DURACION_MAX", "0.5")
ATERRIZAJE_SCROLL_PROB = _env_float("ATERRIZAJE_SCROLL_PROB", "0.30")
ATERRIZAJE_SCROLL_DIST_MIN = _env_int("ATERRIZAJE_SCROLL_DIST_MIN", "50")
ATERRIZAJE_SCROLL_DIST_MAX = _env_int("ATERRIZAJE_SCROLL_DIST_MAX", "150")

# Interacción con desplegable
PRE_INTERACCION_PAUSA_MIN = _env_float("PRE_INTERACCION_PAUSA_MIN", "0.4")
PRE_INTERACCION_PAUSA_MAX = _env_float("PRE_INTERACCION_PAUSA_MAX", "1.2")
MOUSE_TRAYECTORIA_DURACION_MIN = _env_float("MOUSE_TRAYECTORIA_DURACION_MIN", "0.3")
MOUSE_TRAYECTORIA_DURACION_MAX = _env_float("MOUSE_TRAYECTORIA_DURACION_MAX", "0.8")
MOUSE_OVERSHOOT_PROB = _env_float("MOUSE_OVERSHOOT_PROB", "0.12")
MOUSE_OVERSHOOT_DIST_MIN = _env_int("MOUSE_OVERSHOOT_DIST_MIN", "15")
MOUSE_OVERSHOOT_DIST_MAX = _env_int("MOUSE_OVERSHOOT_DIST_MAX", "40")
MOUSE_OVERSHOOT_PAUSA_MIN = _env_float("MOUSE_OVERSHOOT_PAUSA_MIN", "0.1")
MOUSE_OVERSHOOT_PAUSA_MAX = _env_float("MOUSE_OVERSHOOT_PAUSA_MAX", "0.3")
CLICK_PRESS_RELEASE_MIN_MS = _env_int("CLICK_PRESS_RELEASE_MIN", "50")
CLICK_PRESS_RELEASE_MAX_MS = _env_int("CLICK_PRESS_RELEASE_MAX", "150")

# Recorrido desplegable
DESPLEGABLE_PAUSA_APERTURA_MIN = _env_float("DESPLEGABLE_PAUSA_APERTURA_MIN", "0.3")
DESPLEGABLE_PAUSA_APERTURA_MAX = _env_float("DESPLEGABLE_PAUSA_APERTURA_MAX", "0.8")
DESPLEGABLE_SCROLL_ITER_MIN = _env_int("DESPLEGABLE_SCROLL_ITER_MIN", "1")
DESPLEGABLE_SCROLL_ITER_MAX = _env_int("DESPLEGABLE_SCROLL_ITER_MAX", "2")
DESPLEGABLE_ARROW_POR_ITER_MIN = _env_int("DESPLEGABLE_ARROW_POR_ITER_MIN", "2")
DESPLEGABLE_ARROW_POR_ITER_MAX = _env_int("DESPLEGABLE_ARROW_POR_ITER_MAX", "4")
DESPLEGABLE_ARROW_DELAY_MIN = _env_float("DESPLEGABLE_ARROW_DELAY_MIN", "0.15")
DESPLEGABLE_ARROW_DELAY_MAX = _env_float("DESPLEGABLE_ARROW_DELAY_MAX", "0.4")
DESPLEGABLE_ITER_PAUSA_MIN = _env_float("DESPLEGABLE_ITER_PAUSA_MIN", "0.4")
DESPLEGABLE_ITER_PAUSA_MAX = _env_float("DESPLEGABLE_ITER_PAUSA_MAX", "1.0")
DESPLEGABLE_NAV_DELAY_MIN = _env_float("DESPLEGABLE_NAV_DELAY_MIN", "0.1")
DESPLEGABLE_NAV_DELAY_MAX = _env_float("DESPLEGABLE_NAV_DELAY_MAX", "0.3")
DESPLEGABLE_DECISION_MIN = _env_float("DESPLEGABLE_DECISION_MIN", "0.2")
DESPLEGABLE_DECISION_MAX = _env_float("DESPLEGABLE_DECISION_MAX", "0.6")

# Transición
TRANSICION_PAUSA_MIN = _env_float("TRANSICION_PAUSA_MIN", "0.5")
TRANSICION_PAUSA_MAX = _env_float("TRANSICION_PAUSA_MAX", "1.5")
TRANSICION_IDLE_PROB = _env_float("TRANSICION_IDLE_PROB", "0.40")
TRANSICION_IDLE_RANGO = _env_int("TRANSICION_IDLE_RANGO", "20")
TRANSICION_EXTRA_PROB = _env_float("TRANSICION_EXTRA_PROB", "0.20")
TRANSICION_EXTRA_MIN = _env_float("TRANSICION_EXTRA_MIN", "0.5")
TRANSICION_EXTRA_MAX = _env_float("TRANSICION_EXTRA_MAX", "2.0")

# Focus → Click (intervalo entre focus y click en botones de envío)
FOCUS_CLICK_MIN = _env_float("FOCUS_CLICK_MIN", "0.35")
FOCUS_CLICK_MAX = _env_float("FOCUS_CLICK_MAX", "0.65")

# Fase 1 — Scroll inicial obligatorio
F1_SCROLL_INICIAL_DIST_MIN = _env_int("F1_SCROLL_INICIAL_DIST_MIN", "80")
F1_SCROLL_INICIAL_DIST_MAX = _env_int("F1_SCROLL_INICIAL_DIST_MAX", "200")

# Fase 2 — Scroll exhaustivo + botón Entrar
F2_SCROLL_DIST_MIN = _env_int("F2_SCROLL_DIST_MIN", "100")
F2_SCROLL_DIST_MAX = _env_int("F2_SCROLL_DIST_MAX", "250")
F2_SCROLL_PAUSA_MIN = _env_float("F2_SCROLL_PAUSA_MIN", "0.5")
F2_SCROLL_PAUSA_MAX = _env_float("F2_SCROLL_PAUSA_MAX", "1.5")

# Personalidad
PERSONALIDAD_FACTOR_RAPIDO = _env_float("PERSONALIDAD_FACTOR_RAPIDO", "0.6")
PERSONALIDAD_FACTOR_NORMAL = _env_float("PERSONALIDAD_FACTOR_NORMAL", "1.0")
PERSONALIDAD_FACTOR_LENTO = _env_float("PERSONALIDAD_FACTOR_LENTO", "1.5")


# ---------------------------------------------------------------------------
# Personalidad — define el perfil temporal de un ciclo
# ---------------------------------------------------------------------------

class Personalidad:
    """Perfil de comportamiento elegido aleatoriamente al inicio de cada ciclo."""

    def __init__(self):
        self.velocidad = random.choice(["rapido", "normal", "lento"])
        self.nerviosismo = random.uniform(0.0, 1.0)
        self.atencion = random.uniform(0.5, 1.0)

        factores = {
            "rapido": PERSONALIDAD_FACTOR_RAPIDO,
            "normal": PERSONALIDAD_FACTOR_NORMAL,
            "lento": PERSONALIDAD_FACTOR_LENTO,
        }
        self.factor = factores[self.velocidad]

    def delay(self, min_s: float, max_s: float) -> float:
        """Genera un delay modulado por el factor de velocidad."""
        return random.uniform(min_s * self.factor, max_s * self.factor)

    def __repr__(self) -> str:
        return (f"Personalidad(velocidad={self.velocidad}, "
                f"factor={self.factor:.1f}, nerviosismo={self.nerviosismo:.2f}, "
                f"atencion={self.atencion:.2f})")


# ---------------------------------------------------------------------------
# Estado del ratón — mantiene posición Python-side
# ---------------------------------------------------------------------------

class EstadoRaton:
    """Mantiene la posición del ratón en Python para trayectorias continuas."""

    def __init__(self):
        self.x: int = random.randint(200, 600)
        self.y: int = random.randint(150, 400)


# ---------------------------------------------------------------------------
# Primitivas de bajo nivel
# ---------------------------------------------------------------------------

async def _mover_raton(cdp: CDPSession, raton: EstadoRaton,
                       x_destino: int, y_destino: int,
                       duracion: float = 0.5) -> None:
    """Mueve el ratón con trayectoria ease-in-out y desviaciones aleatorias."""
    pasos = random.randint(15, 25)
    x_ini, y_ini = raton.x, raton.y
    pausa_por_paso = duracion / pasos

    for i in range(pasos):
        t = (i + 1) / pasos
        ease = t * t * (3 - 2 * t)  # smoothstep

        # Desviaciones excepto en el último paso
        dx = random.randint(-10, 10) if i < pasos - 1 else 0
        dy = random.randint(-7, 7) if i < pasos - 1 else 0

        x = int(x_ini + (x_destino - x_ini) * ease + dx)
        y = int(y_ini + (y_destino - y_ini) * ease + dy)

        try:
            await cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": max(0, x),
                "y": max(0, y),
            }, timeout=TIMEOUT_JS)
        except Exception:
            break

        # Más lento al inicio y final
        p = pausa_por_paso
        if i < 3 or i > pasos - 4:
            p *= 1.8
        await asyncio.sleep(p)

    raton.x = x_destino
    raton.y = y_destino


async def _mover_a_elemento(cdp: CDPSession, raton: EstadoRaton,
                            selector: str, personalidad: Personalidad) -> dict:
    """Mueve el ratón hacia un elemento con overshoot opcional.

    Returns:
        dict con {x, y} de la posición final del centro del elemento.
    """
    box = await esperar_elemento(cdp, selector)
    # Jitter en el punto de destino
    dest_x = box["x"] + random.randint(-5, 5)
    dest_y = box["y"] + random.randint(-3, 3)

    duracion = random.uniform(MOUSE_TRAYECTORIA_DURACION_MIN,
                              MOUSE_TRAYECTORIA_DURACION_MAX)

    # Overshoot
    if random.random() < MOUSE_OVERSHOOT_PROB:
        # Calcular dirección del movimiento
        dir_x = dest_x - raton.x
        dir_y = dest_y - raton.y
        dist = max(1, (dir_x ** 2 + dir_y ** 2) ** 0.5)
        overshoot_dist = random.randint(MOUSE_OVERSHOOT_DIST_MIN,
                                        MOUSE_OVERSHOOT_DIST_MAX)
        overshoot_x = dest_x + int(dir_x / dist * overshoot_dist)
        overshoot_y = dest_y + int(dir_y / dist * overshoot_dist)

        await _mover_raton(cdp, raton, overshoot_x, overshoot_y, duracion * 0.7)
        await asyncio.sleep(random.uniform(MOUSE_OVERSHOOT_PAUSA_MIN,
                                           MOUSE_OVERSHOOT_PAUSA_MAX))
        await _mover_raton(cdp, raton, dest_x, dest_y, duracion * 0.3)
    else:
        await _mover_raton(cdp, raton, dest_x, dest_y, duracion)

    return {"x": dest_x, "y": dest_y}


async def _click_nativo(cdp: CDPSession, x: int, y: int) -> None:
    """Click CDP nativo: mousePressed → pausa → mouseReleased."""
    await cdp.send("Input.dispatchMouseEvent", {
        "type": "mousePressed",
        "x": x, "y": y,
        "button": "left",
        "clickCount": 1,
    }, timeout=TIMEOUT_JS)

    await asyncio.sleep(
        random.randint(CLICK_PRESS_RELEASE_MIN_MS, CLICK_PRESS_RELEASE_MAX_MS) / 1000.0
    )

    await cdp.send("Input.dispatchMouseEvent", {
        "type": "mouseReleased",
        "x": x, "y": y,
        "button": "left",
        "clickCount": 1,
    }, timeout=TIMEOUT_JS)


async def _enviar_tecla(cdp: CDPSession, key: str) -> None:
    """Envía una tecla via CDP Input.dispatchKeyEvent."""
    await cdp.send("Input.dispatchKeyEvent", {
        "type": "keyDown",
        "key": key,
        "code": f"Arrow{key.capitalize()}" if key.startswith("Arrow") else key,
    }, timeout=TIMEOUT_JS)
    await asyncio.sleep(random.uniform(0.02, 0.05))
    await cdp.send("Input.dispatchKeyEvent", {
        "type": "keyUp",
        "key": key,
        "code": f"Arrow{key.capitalize()}" if key.startswith("Arrow") else key,
    }, timeout=TIMEOUT_JS)


async def _scroll_exploratorio(cdp: CDPSession, raton: EstadoRaton,
                               dist_min: int, dist_max: int) -> None:
    """Scroll via mouseWheel nativo con micro-movimientos entre pasos."""
    pasos = random.randint(2, 3)
    for i in range(pasos):
        distancia = random.randint(dist_min // pasos, dist_max // pasos)
        try:
            await cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": raton.x,
                "y": raton.y,
                "deltaX": 0,
                "deltaY": distancia,
            }, timeout=TIMEOUT_JS)
        except Exception:
            pass

        if i < pasos - 1:
            raton.x = max(0, raton.x + random.randint(-5, 5))
            raton.y = max(0, raton.y + random.randint(-3, 3))
            try:
                await cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved",
                    "x": raton.x,
                    "y": raton.y,
                }, timeout=TIMEOUT_JS)
            except Exception:
                pass

        await asyncio.sleep(random.uniform(0.1, 0.3))


async def _micro_movimiento(cdp: CDPSession, raton: EstadoRaton,
                            rango_x: int, rango_y: int,
                            duracion_min: float, duracion_max: float) -> None:
    """Micro-movimiento idle del ratón."""
    dest_x = max(0, raton.x + random.randint(-rango_x, rango_x))
    dest_y = max(0, raton.y + random.randint(-rango_y, rango_y))
    duracion = random.uniform(duracion_min, duracion_max)
    await _mover_raton(cdp, raton, dest_x, dest_y, duracion)


async def _movimientos_idle_durante_espera(cdp: CDPSession, raton: EstadoRaton,
                                           evento_fin: asyncio.Event) -> None:
    """Movimientos idle del ratón mientras se espera algo (carga de página)."""
    while not evento_fin.is_set():
        await asyncio.sleep(random.uniform(0.8, 2.0))
        if evento_fin.is_set():
            break
        await _micro_movimiento(cdp, raton, 30, 30, 0.15, 0.3)


# ---------------------------------------------------------------------------
# FASE 0 — Selección de sede (Madrid)
# ---------------------------------------------------------------------------

async def fase_0(cdp: CDPSession, personalidad: Personalidad,
                 raton: EstadoRaton, es_primera_vez: bool,
                 config: dict) -> None:
    """Página 0: Seleccionar provincia y pulsar Aceptar.

    Sigue la especificación de specs/pagina_0_seleccion_sede.md.
    Todos los selectores vienen de config["ids"], nada hardcodeado.
    """
    url_inicio = config["url_inicio"]
    ids = config["ids"]

    # Selectores derivados de config
    sel_dropdown = f"#{ids['dropdown_provincia']}"
    sel_boton = f"#{ids['boton_aceptar_f1']}"
    texto_provincia = config.get("provincia_objetivo", "Madrid")
    valor_provincia = ids["valor_madrid"]

    # ── PASO 1: Navegación / Retorno ──────────────────────────────────────
    if es_primera_vez:
        log_info("Fase 0: navegando a URL de inicio")
        await cdp.send("Page.enable", timeout=TIMEOUT_JS)
        load_fut = cdp.pre_wait_event("Page.loadEventFired")
        await cdp.send("Page.navigate", {"url": url_inicio}, timeout=TIMEOUT_PAGINA)
        await cdp.wait_future(load_fut, timeout=TIMEOUT_PAGINA)
    else:
        log_info("Fase 0: retorno al inicio (via botón de volver)")
        # Esperar a que la página cargue tras el click del botón de volver
        try:
            await esperar_carga_pagina(cdp, timeout=TIMEOUT_PAGINA)
        except TimeoutCargaPagina:
            # Puede que la carga ya haya ocurrido antes de que lleguemos aquí;
            # no es crítico si el elemento clave aparece a continuación.
            pass

    # Esperar elemento clave + verificar WAF
    await esperar_elemento(cdp, sel_dropdown)
    if await detectar_waf(cdp):
        raise WafBanError("WAF detectado en Página 0")

    log_info(f"Fase 0: página cargada, elemento {sel_dropdown} encontrado")

    # ── PASO 2: Aterrizaje (orientación visual) ──────────────────────────
    await asyncio.sleep(personalidad.delay(ATERRIZAJE_PAUSA_MIN, ATERRIZAJE_PAUSA_MAX))

    n_movimientos = random.randint(ATERRIZAJE_MICRO_MOV_MIN, ATERRIZAJE_MICRO_MOV_MAX)
    for _ in range(n_movimientos):
        await _micro_movimiento(cdp, raton,
                                ATERRIZAJE_MOV_RANGO_X, ATERRIZAJE_MOV_RANGO_Y,
                                ATERRIZAJE_MOV_DURACION_MIN, ATERRIZAJE_MOV_DURACION_MAX)
        await asyncio.sleep(random.uniform(0.1, 0.3))

    if random.random() < ATERRIZAJE_SCROLL_PROB:
        await _scroll_exploratorio(cdp, raton,
                                   ATERRIZAJE_SCROLL_DIST_MIN,
                                   ATERRIZAJE_SCROLL_DIST_MAX)
        await asyncio.sleep(random.uniform(0.3, 0.8))

    # ── PASO 3: Reconocimiento y apertura del desplegable ────────────────
    await asyncio.sleep(personalidad.delay(PRE_INTERACCION_PAUSA_MIN,
                                           PRE_INTERACCION_PAUSA_MAX))

    pos = await _mover_a_elemento(cdp, raton, sel_dropdown, personalidad)

    # Re-verificar presencia antes de click
    await esperar_elemento(cdp, sel_dropdown)

    # Click para dar focus al <select>
    await _click_nativo(cdp, pos["x"], pos["y"])

    # Asegurar focus programáticamente como respaldo
    dropdown_id_js = safe_js_string(ids["dropdown_provincia"])
    await ejecutar_js(cdp, f"document.getElementById('{dropdown_id_js}').focus();")

    # ── PASO 4: Recorrido humano del desplegable ─────────────────────────
    await asyncio.sleep(personalidad.delay(DESPLEGABLE_PAUSA_APERTURA_MIN,
                                           DESPLEGABLE_PAUSA_APERTURA_MAX))

    # 4b. Scroll exploratorio dentro del desplegable (ArrowDown)
    n_iter = random.randint(DESPLEGABLE_SCROLL_ITER_MIN, DESPLEGABLE_SCROLL_ITER_MAX)
    for i in range(n_iter):
        n_arrows = random.randint(DESPLEGABLE_ARROW_POR_ITER_MIN,
                                  DESPLEGABLE_ARROW_POR_ITER_MAX)
        for _ in range(n_arrows):
            await _enviar_tecla(cdp, "ArrowDown")
            await asyncio.sleep(personalidad.delay(DESPLEGABLE_ARROW_DELAY_MIN,
                                                   DESPLEGABLE_ARROW_DELAY_MAX))

        if i < n_iter - 1:
            await asyncio.sleep(personalidad.delay(DESPLEGABLE_ITER_PAUSA_MIN,
                                                   DESPLEGABLE_ITER_PAUSA_MAX))

    # 4c. Localizar la provincia objetivo recorriendo las opciones
    options_result = await ejecutar_js(cdp, f"""
        (function() {{
            var sel = document.getElementById('{dropdown_id_js}');
            if (!sel) return {{options: [], currentIndex: 0}};
            var opts = [];
            for (var i = 0; i < sel.options.length; i++) {{
                opts.push({{index: i, text: sel.options[i].textContent.trim()}});
            }}
            return {{options: opts, currentIndex: sel.selectedIndex}};
        }})();
    """)
    options_data = options_result.get("value", {})
    options_list = options_data.get("options", [])
    current_index = options_data.get("currentIndex", 0)

    # Encontrar índice de la provincia objetivo
    target_index = None
    for opt in options_list:
        if opt["text"] == texto_provincia:
            target_index = opt["index"]
            break

    if target_index is None:
        raise ElementoNoEncontrado(
            f"Opción '{texto_provincia}' no encontrada en el <select> "
            f"(opciones: {[o['text'] for o in options_list[:10]]})"
        )

    # Navegar desde la posición actual hasta la provincia con ArrowDown/ArrowUp
    pasos_necesarios = target_index - current_index
    tecla = "ArrowDown" if pasos_necesarios > 0 else "ArrowUp"

    for _ in range(abs(pasos_necesarios)):
        await _enviar_tecla(cdp, tecla)
        await asyncio.sleep(personalidad.delay(DESPLEGABLE_NAV_DELAY_MIN,
                                               DESPLEGABLE_NAV_DELAY_MAX))

    # 4d. Seleccionar — pausa de decisión
    await asyncio.sleep(personalidad.delay(DESPLEGABLE_DECISION_MIN,
                                           DESPLEGABLE_DECISION_MAX))

    # Confirmar selección con Enter (cierra el desplegable nativamente)
    await _enviar_tecla(cdp, "Enter")

    # Dispatchar eventos change/input para que el formulario reaccione
    await ejecutar_js(cdp, f"""
        (function() {{
            var sel = document.getElementById('{dropdown_id_js}');
            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            sel.dispatchEvent(new Event('input', {{bubbles: true}}));
        }})();
    """)

    # Verificación obligatoria
    verify = await ejecutar_js(cdp, f"""
        (function() {{
            var sel = document.getElementById('{dropdown_id_js}');
            var opt = sel.options[sel.selectedIndex];
            return opt ? opt.textContent.trim() : '';
        }})();
    """)
    selected_text = verify.get("value", "")

    if selected_text != texto_provincia:
        # Reintento: forzar selección por valor como fallback
        log_info(f"Fase 0: verificación falló (seleccionado: '{selected_text}'), reintentando...")
        valor_escaped = safe_js_string(valor_provincia)
        await ejecutar_js(cdp, f"""
            (function() {{
                var sel = document.getElementById('{dropdown_id_js}');
                sel.value = '{valor_escaped}';
                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                sel.dispatchEvent(new Event('input', {{bubbles: true}}));
            }})();
        """)
        # Segunda verificación
        verify2 = await ejecutar_js(cdp, f"""
            (function() {{
                var sel = document.getElementById('{dropdown_id_js}');
                var opt = sel.options[sel.selectedIndex];
                return opt ? opt.textContent.trim() : '';
            }})();
        """)
        if verify2.get("value", "") != texto_provincia:
            raise RuntimeError(
                f"No se pudo seleccionar '{texto_provincia}' tras 2 intentos"
            )

    log_info(f"Fase 0: {texto_provincia} seleccionado correctamente")

    # ── PASO 5: Transición hacia el botón ────────────────────────────────
    await asyncio.sleep(personalidad.delay(TRANSICION_PAUSA_MIN, TRANSICION_PAUSA_MAX))

    if random.random() < TRANSICION_IDLE_PROB:
        await _micro_movimiento(cdp, raton,
                                TRANSICION_IDLE_RANGO, TRANSICION_IDLE_RANGO,
                                0.15, 0.3)

    if random.random() < TRANSICION_EXTRA_PROB:
        await asyncio.sleep(personalidad.delay(TRANSICION_EXTRA_MIN,
                                               TRANSICION_EXTRA_MAX))

    # ── PASO 6: Envío (focus + click en "Aceptar") ──────────────────────
    pos_btn = await _mover_a_elemento(cdp, raton, sel_boton, personalidad)

    # Re-verificar presencia del botón
    await esperar_elemento(cdp, sel_boton)

    # Focus explícito en el botón
    boton_f0_id_js = safe_js_string(ids["boton_aceptar_f1"])
    await ejecutar_js(cdp, f"document.getElementById('{boton_f0_id_js}').focus();")

    # Pausa entre focus y click (0.35–0.65s)
    await asyncio.sleep(personalidad.delay(FOCUS_CLICK_MIN, FOCUS_CLICK_MAX))

    # Pre-registrar evento de carga ANTES del click
    load_fut = cdp.pre_wait_event("Page.loadEventFired")

    # Click nativo
    await _click_nativo(cdp, pos_btn["x"], pos_btn["y"])
    log_info("Fase 0: click en Aceptar, esperando carga de Página 1...")

    # ── PASO 7: Espera de carga (transición a Página 1) ──────────────────
    fin_carga = asyncio.Event()

    # Movimientos idle durante la espera (en paralelo)
    tarea_idle = asyncio.create_task(
        _movimientos_idle_durante_espera(cdp, raton, fin_carga)
    )

    try:
        await cdp.wait_future(load_fut, timeout=TIMEOUT_PAGINA)
    except asyncio.TimeoutError:
        fin_carga.set()
        tarea_idle.cancel()
        try:
            await tarea_idle
        except asyncio.CancelledError:
            pass
        raise TimeoutCargaPagina("Timeout esperando carga tras Aceptar en Página 0")
    finally:
        fin_carga.set()
        tarea_idle.cancel()
        try:
            await tarea_idle
        except asyncio.CancelledError:
            pass

    # Verificar WAF tras carga
    if await detectar_waf(cdp):
        raise WafBanError("WAF detectado tras envío de Página 0")

    log_info("Fase 0: completada — Página 1 cargada")


# ---------------------------------------------------------------------------
# FASE 1 — Selección de trámite
# ---------------------------------------------------------------------------

async def fase_1(cdp: CDPSession, personalidad: Personalidad,
                 raton: EstadoRaton, config: dict) -> None:
    """Página 1: Seleccionar trámite y pulsar Aceptar.

    Sigue la especificación de specs/pagina_1_seleccion_tramite.md.
    Match por prefijo (startsWith) para el texto del trámite.
    """
    ids = config["ids"]

    # Selectores — el ID tiene corchetes, necesita escape CSS
    sel_dropdown = css_escape_id(ids["dropdown_tramite"])
    sel_boton = f"#{ids['boton_aceptar_f2']}"
    tramite_prefijo = config.get("tramite_prefijo", "POLICIA TARJETA CONFLICTO UKRANIA")
    valor_tramite = ids["valor_tramite"]
    dropdown_id_js = safe_js_string(ids["dropdown_tramite"])

    # ── PASO 1: Espera de carga + seguridad ──────────────────────────────
    await esperar_elemento(cdp, sel_dropdown)
    if await detectar_waf(cdp):
        raise WafBanError("WAF detectado en Página 1")

    log_info(f"Fase 1: página cargada, elemento {sel_dropdown} encontrado")

    # ── PASO 2: Aterrizaje + scroll obligatorio ──────────────────────────
    await asyncio.sleep(personalidad.delay(ATERRIZAJE_PAUSA_MIN, ATERRIZAJE_PAUSA_MAX))

    n_movimientos = random.randint(ATERRIZAJE_MICRO_MOV_MIN, ATERRIZAJE_MICRO_MOV_MAX)
    for _ in range(n_movimientos):
        await _micro_movimiento(cdp, raton,
                                ATERRIZAJE_MOV_RANGO_X, ATERRIZAJE_MOV_RANGO_Y,
                                ATERRIZAJE_MOV_DURACION_MIN, ATERRIZAJE_MOV_DURACION_MAX)
        await asyncio.sleep(random.uniform(0.1, 0.3))

    # Scroll obligatorio (la página es más grande)
    await _scroll_exploratorio(cdp, raton,
                               F1_SCROLL_INICIAL_DIST_MIN,
                               F1_SCROLL_INICIAL_DIST_MAX)
    await asyncio.sleep(random.uniform(0.3, 0.8))

    # ── PASO 3: Reconocimiento y apertura del desplegable ────────────────
    await asyncio.sleep(personalidad.delay(PRE_INTERACCION_PAUSA_MIN,
                                           PRE_INTERACCION_PAUSA_MAX))

    pos = await _mover_a_elemento(cdp, raton, sel_dropdown, personalidad)

    # Re-verificar presencia antes de click
    await esperar_elemento(cdp, sel_dropdown)

    # Click para dar focus al <select>
    await _click_nativo(cdp, pos["x"], pos["y"])

    # Asegurar focus programáticamente como respaldo
    await ejecutar_js(cdp, f"document.getElementById('{dropdown_id_js}').focus();")

    # ── PASO 4: Recorrido humano del desplegable ─────────────────────────
    await asyncio.sleep(personalidad.delay(DESPLEGABLE_PAUSA_APERTURA_MIN,
                                           DESPLEGABLE_PAUSA_APERTURA_MAX))

    # 4b. Scroll exploratorio dentro del desplegable (ArrowDown errático)
    n_iter = random.randint(DESPLEGABLE_SCROLL_ITER_MIN, DESPLEGABLE_SCROLL_ITER_MAX)
    for i in range(n_iter):
        n_arrows = random.randint(DESPLEGABLE_ARROW_POR_ITER_MIN,
                                  DESPLEGABLE_ARROW_POR_ITER_MAX)
        for _ in range(n_arrows):
            await _enviar_tecla(cdp, "ArrowDown")
            await asyncio.sleep(personalidad.delay(DESPLEGABLE_ARROW_DELAY_MIN,
                                                   DESPLEGABLE_ARROW_DELAY_MAX))

        if i < n_iter - 1:
            await asyncio.sleep(personalidad.delay(DESPLEGABLE_ITER_PAUSA_MIN,
                                                   DESPLEGABLE_ITER_PAUSA_MAX))

    # 4c. Localizar el trámite objetivo recorriendo las opciones
    options_result = await ejecutar_js(cdp, f"""
        (function() {{
            var sel = document.getElementById('{dropdown_id_js}');
            if (!sel) return {{options: [], currentIndex: 0}};
            var opts = [];
            for (var i = 0; i < sel.options.length; i++) {{
                opts.push({{index: i, text: sel.options[i].textContent.trim()}});
            }}
            return {{options: opts, currentIndex: sel.selectedIndex}};
        }})();
    """)
    options_data = options_result.get("value", {})
    options_list = options_data.get("options", [])
    current_index = options_data.get("currentIndex", 0)

    # Encontrar índice del trámite por prefijo
    target_index = None
    for opt in options_list:
        if opt["text"].startswith(tramite_prefijo):
            target_index = opt["index"]
            break

    if target_index is None:
        raise ElementoNoEncontrado(
            f"Opción con prefijo '{tramite_prefijo}' no encontrada en el <select> "
            f"(opciones: {[o['text'][:50] for o in options_list[:10]]})"
        )

    # Navegar desde la posición actual hasta el trámite con ArrowDown/ArrowUp
    pasos_necesarios = target_index - current_index
    tecla = "ArrowDown" if pasos_necesarios > 0 else "ArrowUp"

    for _ in range(abs(pasos_necesarios)):
        await _enviar_tecla(cdp, tecla)
        await asyncio.sleep(personalidad.delay(DESPLEGABLE_NAV_DELAY_MIN,
                                               DESPLEGABLE_NAV_DELAY_MAX))

    # 4d. Seleccionar — pausa de decisión
    await asyncio.sleep(personalidad.delay(DESPLEGABLE_DECISION_MIN,
                                           DESPLEGABLE_DECISION_MAX))

    # Confirmar selección con Enter
    await _enviar_tecla(cdp, "Enter")

    # Dispatchar eventos change/input (el onchange dispara JS local, no AJAX)
    await ejecutar_js(cdp, f"""
        (function() {{
            var sel = document.getElementById('{dropdown_id_js}');
            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            sel.dispatchEvent(new Event('input', {{bubbles: true}}));
        }})();
    """)

    # Verificación obligatoria (match por prefijo)
    verify = await ejecutar_js(cdp, f"""
        (function() {{
            var sel = document.getElementById('{dropdown_id_js}');
            var opt = sel.options[sel.selectedIndex];
            return opt ? opt.textContent.trim() : '';
        }})();
    """)
    selected_text = verify.get("value", "")

    if not selected_text.startswith(tramite_prefijo):
        # Reintento: forzar selección por valor como fallback
        log_info(f"Fase 1: verificación falló (seleccionado: '{selected_text[:50]}'), reintentando...")
        valor_escaped = safe_js_string(valor_tramite)
        await ejecutar_js(cdp, f"""
            (function() {{
                var sel = document.getElementById('{dropdown_id_js}');
                sel.value = '{valor_escaped}';
                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                sel.dispatchEvent(new Event('input', {{bubbles: true}}));
            }})();
        """)
        # Segunda verificación
        verify2 = await ejecutar_js(cdp, f"""
            (function() {{
                var sel = document.getElementById('{dropdown_id_js}');
                var opt = sel.options[sel.selectedIndex];
                return opt ? opt.textContent.trim() : '';
            }})();
        """)
        if not verify2.get("value", "").startswith(tramite_prefijo):
            raise RuntimeError(
                f"No se pudo seleccionar trámite con prefijo '{tramite_prefijo}' tras 2 intentos"
            )

    log_info(f"Fase 1: trámite seleccionado correctamente ({selected_text[:60]})")

    # ── PASO 5: Transición hacia el botón ────────────────────────────────
    await asyncio.sleep(personalidad.delay(TRANSICION_PAUSA_MIN, TRANSICION_PAUSA_MAX))

    if random.random() < TRANSICION_IDLE_PROB:
        await _micro_movimiento(cdp, raton,
                                TRANSICION_IDLE_RANGO, TRANSICION_IDLE_RANGO,
                                0.15, 0.3)

    if random.random() < TRANSICION_EXTRA_PROB:
        await asyncio.sleep(personalidad.delay(TRANSICION_EXTRA_MIN,
                                               TRANSICION_EXTRA_MAX))

    # ── PASO 6: Envío (focus + click en "Aceptar") ──────────────────────
    pos_btn = await _mover_a_elemento(cdp, raton, sel_boton, personalidad)

    # Re-verificar presencia del botón
    await esperar_elemento(cdp, sel_boton)

    # Focus explícito en el botón
    boton_f1_id_js = safe_js_string(ids["boton_aceptar_f2"])
    await ejecutar_js(cdp, f"document.getElementById('{boton_f1_id_js}').focus();")

    # Pausa entre focus y click (0.35–0.65s)
    await asyncio.sleep(personalidad.delay(FOCUS_CLICK_MIN, FOCUS_CLICK_MAX))

    # Pre-registrar evento de carga ANTES del click
    load_fut = cdp.pre_wait_event("Page.loadEventFired")

    # Click nativo
    await _click_nativo(cdp, pos_btn["x"], pos_btn["y"])
    log_info("Fase 1: click en Aceptar, esperando carga de Página 2...")

    # ── PASO 7: Espera de carga (transición a Página 2) ──────────────────
    fin_carga = asyncio.Event()

    tarea_idle = asyncio.create_task(
        _movimientos_idle_durante_espera(cdp, raton, fin_carga)
    )

    try:
        await cdp.wait_future(load_fut, timeout=TIMEOUT_PAGINA)
    except asyncio.TimeoutError:
        fin_carga.set()
        tarea_idle.cancel()
        try:
            await tarea_idle
        except asyncio.CancelledError:
            pass
        raise TimeoutCargaPagina("Timeout esperando carga tras Aceptar en Página 1")
    finally:
        fin_carga.set()
        tarea_idle.cancel()
        try:
            await tarea_idle
        except asyncio.CancelledError:
            pass

    # Verificar WAF tras carga
    if await detectar_waf(cdp):
        raise WafBanError("WAF detectado tras envío de Página 1")

    log_info("Fase 1: completada — Página 2 cargada")


# ---------------------------------------------------------------------------
# FASE 2 — Aviso informativo (scroll exhaustivo + click "Entrar")
# ---------------------------------------------------------------------------

async def fase_2(cdp: CDPSession, personalidad: Personalidad,
                 raton: EstadoRaton, config: dict) -> None:
    """Página 2: Leer aviso informativo (scroll hasta abajo) y pulsar Entrar.

    La página es informativa y larga. Un humano haría scroll varias veces
    hasta agotar el contenido antes de pulsar "Entrar".
    """
    ids = config["ids"]
    sel_boton = f"#{ids['boton_entrar_f3']}"

    # ── PASO 1: Espera de carga + seguridad ──────────────────────────────
    await esperar_elemento(cdp, sel_boton)
    if await detectar_waf(cdp):
        raise WafBanError("WAF detectado en Página 2")

    log_info(f"Fase 2: página cargada, botón {sel_boton} encontrado")

    # ── PASO 2: Aterrizaje ───────────────────────────────────────────────
    await asyncio.sleep(personalidad.delay(ATERRIZAJE_PAUSA_MIN, ATERRIZAJE_PAUSA_MAX))

    n_movimientos = random.randint(ATERRIZAJE_MICRO_MOV_MIN, ATERRIZAJE_MICRO_MOV_MAX)
    for _ in range(n_movimientos):
        await _micro_movimiento(cdp, raton,
                                ATERRIZAJE_MOV_RANGO_X, ATERRIZAJE_MOV_RANGO_Y,
                                ATERRIZAJE_MOV_DURACION_MIN, ATERRIZAJE_MOV_DURACION_MAX)
        await asyncio.sleep(random.uniform(0.1, 0.3))

    # ── PASO 3: Scroll exhaustivo hasta agotar el contenido ──────────────
    log_info("Fase 2: iniciando scroll exhaustivo de la página informativa")

    while True:
        # Comprobar si queda scroll por hacer
        scroll_info = await ejecutar_js(cdp, """
            (function() {
                var st = window.pageYOffset || document.documentElement.scrollTop;
                var ch = document.documentElement.clientHeight;
                var sh = document.documentElement.scrollHeight;
                return {scrollTop: st, clientHeight: ch, scrollHeight: sh};
            })();
        """)
        info = scroll_info.get("value", {})
        scroll_top = info.get("scrollTop", 0)
        client_height = info.get("clientHeight", 0)
        scroll_height = info.get("scrollHeight", 0)

        # Si ya estamos al final (o casi), parar
        if scroll_top + client_height >= scroll_height - 5:
            break

        # Scroll hacia abajo
        await _scroll_exploratorio(cdp, raton,
                                   F2_SCROLL_DIST_MIN,
                                   F2_SCROLL_DIST_MAX)

        # Pausa de lectura entre scrolls
        await asyncio.sleep(personalidad.delay(F2_SCROLL_PAUSA_MIN, F2_SCROLL_PAUSA_MAX))

    log_info("Fase 2: scroll completado — final de página alcanzado")

    # ── PASO 4: Transición hacia el botón ────────────────────────────────
    await asyncio.sleep(personalidad.delay(TRANSICION_PAUSA_MIN, TRANSICION_PAUSA_MAX))

    if random.random() < TRANSICION_IDLE_PROB:
        await _micro_movimiento(cdp, raton,
                                TRANSICION_IDLE_RANGO, TRANSICION_IDLE_RANGO,
                                0.15, 0.3)

    # ── PASO 5: Focus + click en "Entrar" ────────────────────────────────
    pos_btn = await _mover_a_elemento(cdp, raton, sel_boton, personalidad)

    # Re-verificar presencia del botón
    await esperar_elemento(cdp, sel_boton)

    # Focus explícito en el botón
    boton_id_js = safe_js_string(ids["boton_entrar_f3"])
    await ejecutar_js(cdp, f"document.getElementById('{boton_id_js}').focus();")

    # Pausa entre focus y click (0.35–0.65s)
    await asyncio.sleep(personalidad.delay(FOCUS_CLICK_MIN, FOCUS_CLICK_MAX))

    # Pre-registrar evento de carga ANTES del click
    load_fut = cdp.pre_wait_event("Page.loadEventFired")

    # Click nativo
    await _click_nativo(cdp, pos_btn["x"], pos_btn["y"])
    log_info("Fase 2: click en Entrar, esperando carga de Página 3...")

    # ── PASO 6: Espera de carga (transición a Página 3) ──────────────────
    fin_carga = asyncio.Event()

    tarea_idle = asyncio.create_task(
        _movimientos_idle_durante_espera(cdp, raton, fin_carga)
    )

    try:
        await cdp.wait_future(load_fut, timeout=TIMEOUT_PAGINA)
    except asyncio.TimeoutError:
        fin_carga.set()
        tarea_idle.cancel()
        try:
            await tarea_idle
        except asyncio.CancelledError:
            pass
        raise TimeoutCargaPagina("Timeout esperando carga tras Entrar en Página 2")
    finally:
        fin_carga.set()
        tarea_idle.cancel()
        try:
            await tarea_idle
        except asyncio.CancelledError:
            pass

    # Verificar WAF tras carga
    if await detectar_waf(cdp):
        raise WafBanError("WAF detectado tras envío de Página 2")

    log_info("Fase 2: completada — Página 3 cargada")
