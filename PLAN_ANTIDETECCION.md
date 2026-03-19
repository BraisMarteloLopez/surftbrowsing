# Plan: Sistema de Anti-Detección Desacoplado

> **Estado: COMPLETADO** — Todas las 6 fases implementadas y testeadas (151 tests, 100% pasando)

## Problema actual

1. **Movimientos de ratón discretos**: `mover_raton()` ejecuta una trayectoria punto-a-punto en ~0.3-0.5s y termina. Durante los `delay()` y `pausa_entre_pasos()` (2-5s cada uno) el ratón está **completamente quieto** — un humano real nunca deja el ratón inmóvil durante 5 segundos mientras "lee" una página.

2. **Anti-detección acoplada al flujo de formularios**: Las funciones `paso_formulario_1-5` intercalan directamente llamadas a `movimiento_raton_aleatorio()`, `delay()`, `pausa_extra_aleatoria()`, `mover_raton_a_elemento()`, `scroll_humano()`. Esto hace que:
   - Cada cambio en la estrategia anti-detección requiere editar 5 funciones de formulario.
   - No se puede reutilizar la lógica anti-detección en otro contexto.
   - Es difícil testear el flujo de formulario sin mockear 6+ funciones de anti-detección.
   - No hay forma de hacer que el ratón se mueva **durante** una pausa — son operaciones secuenciales.

3. **Patrones predecibles**: Los formularios siempre siguen el mismo patrón: `mouse_aleatorio → scroll → delay → mouse_a_elemento → acción → delay → mouse_a_botón → click`. Un sistema anti-bot puede detectar esta secuencia repetitiva.

---

## Arquitectura propuesta

```
cita_bot.py              ← Flujo de formularios (orquestación pura)
    │
    ├── comportamiento_humano.py  ← Motor anti-detección (módulo nuevo)
    │       ├── class SimuladorHumano    ← Coordinador principal
    │       ├── class MovimientoRaton    ← Trayectorias + movimiento de fondo
    │       ├── class TemporizadorHumano ← Delays con actividad concurrente
    │       └── class ScrollSimulador    ← Scroll humanizado
    │
    └── cdp_helpers.py           ← Funciones CDP puras (ejecutar_js, navegar, etc.)
```

---

## Fase 0 — Extraer helpers CDP (base para todo lo demás) ✅ COMPLETADA

**Objetivo**: Mover funciones CDP genéricas que no son ni anti-detección ni formulario a su propio módulo. Esto reduce el acoplamiento base.

**Acciones**:
1. Crear `cdp_helpers.py` con:
   - `CDPSession` (clase completa, ~130 líneas)
   - `ejecutar_js()`
   - `safe_js_string()`
   - `obtener_ws_url()`
   - `TIMEOUT_JS`, `TIMEOUT_NAVEGACION`, `CDP_PORT`, `CDP_URL`
2. En `cita_bot.py`: `from cdp_helpers import CDPSession, ejecutar_js, safe_js_string, ...`
3. Actualizar imports en tests existentes.
4. **Criterio de éxito**: 120 tests pasan sin cambios funcionales.

**Riesgo**: Bajo. Es refactoring puro sin cambios de comportamiento.

---

## Fase 1 — Extraer módulo `comportamiento_humano.py` ✅ COMPLETADA

**Objetivo**: Mover toda la lógica anti-detección a un módulo independiente, manteniendo la API secuencial actual (sin cambios de comportamiento todavía).

**Acciones**:
1. Crear `comportamiento_humano.py` con todas las funciones anti-detección:
   - `mover_raton()`, `movimiento_raton_aleatorio()`, `mover_raton_a_elemento()`
   - `scroll_humano()`
   - `delay()`, `pausa_entre_pasos()`, `pausa_extra_aleatoria()`
   - `intervalo_con_jitter()`
   - Todas las constantes de delay (`DELAY_ACCION_BASE`, `DELAY_SCROLL_MIN`, etc.)
2. Mover `detectar_waf()`, `WafBanError`, `limpiar_datos_navegador()` al mismo módulo (son defensivas, no de formulario).
3. En `cita_bot.py`: importar todo desde `comportamiento_humano`.
4. Mover tests correspondientes a `tests/test_comportamiento.py`.
5. **Criterio de éxito**: Misma cantidad de tests, todos pasan, cobertura igual.

**Riesgo**: Bajo. Refactoring de organización, misma API.

---

## Fase 2 — Clase `SimuladorHumano` con estado persistente ✅ COMPLETADA

**Objetivo**: Encapsular el estado del ratón y el viewport en una clase que los formularios usen como contexto, eliminando el estado global en `window.__mouse_pos`.

**Diseño**:
```python
class SimuladorHumano:
    def __init__(self, cdp: CDPSession):
        self.cdp = cdp
        self.mouse_x: int = random.randint(100, 800)
        self.mouse_y: int = random.randint(100, 400)
        self.viewport: tuple[int, int] = (1024, 768)
        self._tarea_fondo: asyncio.Task | None = None

    async def actualizar_viewport(self) -> None:
        """Lee dimensiones reales del viewport via CDP."""

    async def mover_a(self, x: int, y: int) -> None:
        """Trayectoria curva hacia destino. Actualiza self.mouse_x/y."""

    async def mover_a_elemento(self, element_id: str) -> None:
        """Obtiene posición del elemento y llama mover_a()."""

    async def movimiento_idle(self) -> None:
        """1-3 movimientos aleatorios por el viewport."""

    async def scroll(self) -> None:
        """Scroll humanizado 2-4 pasos."""

    async def delay_activo(self, base: float, varianza: float = 0.8) -> None:
        """⭐ CLAVE: Espera humanizada CON movimiento de fondo."""
        # Ver Fase 3 para implementación

    async def pausa_lectura(self) -> None:
        """Pausa entre pasos con movimiento de fondo."""

    async def pausa_extra(self, probabilidad: float = 0.3) -> None:
        """Pausa aleatoria con probabilidad configurable."""
```

**Acciones**:
1. Implementar `SimuladorHumano` con los métodos que replican la API actual.
2. Refactorizar `paso_formulario_1-5` para recibir `SimuladorHumano` en vez de llamar funciones sueltas:
   ```python
   # Antes:
   async def paso_formulario_1(cdp, ids):
       await movimiento_raton_aleatorio(cdp)
       await scroll_humano(cdp)
       await delay()
       ...

   # Después:
   async def paso_formulario_1(humano: SimuladorHumano, ids: dict):
       await humano.movimiento_idle()
       await humano.scroll()
       await humano.delay_activo(DELAY_ACCION_BASE)
       ...
   ```
3. `ciclo_completo()` crea `SimuladorHumano(cdp)` y lo pasa a cada paso.
4. **Criterio de éxito**: Tests actualizados, misma funcionalidad, estado del ratón persiste entre pasos.

**Riesgo**: Medio. Cambia la firma de las funciones de formulario. Los tests se simplifican (un solo mock de `SimuladorHumano`).

---

## Fase 3 — Movimiento de ratón concurrente durante pausas ✅ COMPLETADA

**Objetivo**: El ratón se mueve suavemente **durante** los delays, no solo antes/después. Esta es la mejora clave que el usuario pide.

**Concepto**: `delay_activo()` lanza movimiento de ratón como tarea de fondo y espera a que el delay termine. El ratón se mueve en un patrón de "lectura" (izquierda→derecha, arriba→abajo, con micro-pausas) mientras el bot "espera".

**Diseño de `delay_activo()`**:
```python
async def delay_activo(self, duracion: float) -> None:
    """Espera `duracion` segundos mientras mueve el ratón de fondo.

    El movimiento de fondo simula lectura: trayectorias suaves,
    pausas irregulares, micro-correcciones. Se cancela automáticamente
    cuando el delay termina.
    """
    tarea_raton = asyncio.create_task(self._movimiento_lectura(duracion))
    try:
        await asyncio.sleep(duracion)
    finally:
        tarea_raton.cancel()
        try:
            await tarea_raton
        except asyncio.CancelledError:
            pass

async def _movimiento_lectura(self, duracion: float) -> None:
    """Movimiento continuo que simula ojos + mano durante lectura.

    Patrones posibles (se elige uno aleatoriamente):
    1. Lectura horizontal: zigzag lento izquierda-derecha, bajando poco a poco
    2. Exploración: movimientos suaves entre zonas de interés de la página
    3. Reposo activo: micro-movimientos en una zona reducida (±20px)
    4. Drift: movimiento muy lento en una dirección con correcciones
    """
    patron = random.choice(["lectura", "exploracion", "reposo", "drift"])
    inicio = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - inicio < duracion:
        if patron == "reposo":
            # Micro-movimientos cerca de la posición actual
            dx = random.randint(-20, 20)
            dy = random.randint(-15, 15)
            destino_x = max(0, self.mouse_x + dx)
            destino_y = max(0, self.mouse_y + dy)
            await self.mover_a(destino_x, destino_y, pasos=random.randint(2, 4))
            await asyncio.sleep(random.uniform(0.5, 2.0))

        elif patron == "lectura":
            # Barrido horizontal simulando lectura de texto
            ancho = self.viewport[0]
            x_inicio = int(ancho * 0.15)
            x_fin = int(ancho * random.uniform(0.6, 0.85))
            y_base = self.mouse_y
            # Una "línea de lectura"
            await self.mover_a(x_inicio, y_base, pasos=random.randint(3, 6))
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await self.mover_a(x_fin, y_base + random.randint(-5, 5),
                               pasos=random.randint(8, 15))
            await asyncio.sleep(random.uniform(0.2, 0.6))
            # Bajar a "siguiente línea"
            self.mouse_y += random.randint(15, 30)

        elif patron == "exploracion":
            x = random.randint(int(self.viewport[0] * 0.1),
                               int(self.viewport[0] * 0.9))
            y = random.randint(int(self.viewport[1] * 0.1),
                               int(self.viewport[1] * 0.8))
            await self.mover_a(x, y, pasos=random.randint(5, 10))
            await asyncio.sleep(random.uniform(0.8, 2.5))

        elif patron == "drift":
            # Movimiento muy lento en una dirección
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
```

**Acciones**:
1. Implementar `_movimiento_lectura()` con los 4 patrones.
2. Reemplazar cada `await delay()` en formularios por `await humano.delay_activo(DELAY_ACCION_BASE)`.
3. Reemplazar `pausa_entre_pasos()` en `ciclo_completo()` por `await humano.delay_activo(random.uniform(PAUSA_MIN, PAUSA_MAX))`.
4. Tests: verificar que movimiento de fondo se cancela limpiamente, que no interfiere con acciones posteriores.
5. **Criterio de éxito**: Durante un delay de 3s, se generan >10 eventos `mouseMoved` distribuidos a lo largo de esos 3s (no concentrados al inicio).

**Riesgo**: Medio-alto. Concurrencia con `asyncio.create_task` requiere cuidado con la cancelación y el estado compartido del ratón. El movimiento de fondo NO debe interferir con el `mover_a_elemento()` que viene después.

**Mitigación**: `delay_activo()` siempre cancela la tarea de fondo antes de retornar. La posición del ratón queda actualizada en `self.mouse_x/y`, así que `mover_a_elemento()` parte de una posición realista.

---

## Fase 4 — Variabilidad de secuencia en formularios ✅ COMPLETADA

**Objetivo**: Romper el patrón repetitivo `mouse_idle → scroll → delay → mouse_elemento → acción` que es idéntico en todos los formularios.

**Diseño de `secuencia_pre_accion()`**:
```python
async def secuencia_pre_accion(self, element_id: str | None = None) -> None:
    """Ejecuta una secuencia pre-acción con orden variable.

    Elige aleatoriamente entre varias combinaciones de acciones
    preparatorias, de modo que no todos los pasos del formulario
    tengan exactamente el mismo patrón temporal.
    """
    acciones_posibles = [
        ("idle", lambda: self.movimiento_idle()),
        ("scroll", lambda: self.scroll()),
        ("delay", lambda: self.delay_activo(DELAY_ACCION_BASE)),
        ("pausa", lambda: self.pausa_extra(0.3)),
    ]

    # Elegir 2-4 acciones aleatorias (siempre incluir al menos un delay)
    seleccion = random.sample(acciones_posibles, k=random.randint(2, 4))
    if not any(nombre == "delay" for nombre, _ in seleccion):
        seleccion.append(("delay", lambda: self.delay_activo(DELAY_ACCION_BASE)))
    random.shuffle(seleccion)

    for nombre, accion in seleccion:
        await accion()

    # Mover al elemento objetivo si se especificó
    if element_id:
        await self.mover_a_elemento(element_id)
```

**Acciones**:
1. Implementar `secuencia_pre_accion()` en `SimuladorHumano`.
2. Simplificar formularios:
   ```python
   # Antes (5-8 líneas de anti-detección por formulario):
   await humano.movimiento_idle()
   await humano.scroll()
   await humano.delay_activo(DELAY_ACCION_BASE)
   await humano.pausa_extra()
   await humano.mover_a_elemento(ids["dropdown"])

   # Después (1 línea):
   await humano.secuencia_pre_accion(element_id=ids["dropdown"])
   ```
3. **Criterio de éxito**: Cada ejecución del bot produce una secuencia temporal diferente. Tests verifican que `secuencia_pre_accion` siempre incluye al menos un delay.

**Riesgo**: Bajo. Encapsula lógica existente.

---

## Fase 5 — Scroll con movimiento de ratón integrado ✅ COMPLETADA

**Objetivo**: El scroll actual usa `window.scrollBy()` via JS, que no deja rastro de cursor. Un humano mueve la rueda del ratón (generando eventos `Input.dispatchMouseEvent` con `type: "mouseWheel"`) o arrastra la barra de scroll.

**Acciones**:
1. Reemplazar `ejecutar_js("window.scrollBy(...)")` por eventos CDP nativos:
   ```python
   await cdp.send("Input.dispatchMouseEvent", {
       "type": "mouseWheel",
       "x": self.mouse_x,
       "y": self.mouse_y,
       "deltaX": 0,
       "deltaY": distancia,  # 100-300
   })
   ```
2. Añadir micro-movimientos del ratón durante el scroll (el ratón no está perfectamente quieto mientras se hace scroll con la rueda).
3. **Criterio de éxito**: Scroll genera eventos `mouseWheel` en vez de JS `scrollBy`.

**Riesgo**: Bajo. `Input.dispatchMouseEvent` con `mouseWheel` está bien documentado en CDP.

---

## Resumen de fases y dependencias

```
Fase 0: Extraer cdp_helpers.py                              ✅
  │
  ▼
Fase 1: Extraer comportamiento_humano.py (funciones sueltas) ✅
  │
  ▼
Fase 2: Clase SimuladorHumano (encapsular estado)            ✅
  │
  ├──▶ Fase 3: delay_activo() con movimiento concurrente     ✅ ← CAMBIO CLAVE
  │
  ├──▶ Fase 4: secuencia_pre_accion() variable               ✅
  │
  └──▶ Fase 5: Scroll nativo via mouseWheel                  ✅
```

**Todas las fases completadas.** Tests pasaron de 120 a 151 durante la implementación.

---

## Estimación de complejidad por fase

| Fase | Archivos nuevos | Archivos editados | Tests nuevos | Tipo |
|------|-----------------|-------------------|--------------|------|
| 0    | `cdp_helpers.py` | `cita_bot.py`, tests | 0 (mover existentes) | Refactoring |
| 1    | `comportamiento_humano.py` | `cita_bot.py`, tests | 0 (mover existentes) | Refactoring |
| 2    | — | `comportamiento_humano.py`, `cita_bot.py`, tests | ~10 | Refactoring + nueva API |
| 3    | — | `comportamiento_humano.py`, tests | ~8 | Funcionalidad nueva |
| 4    | — | `comportamiento_humano.py`, `cita_bot.py`, tests | ~5 | Funcionalidad nueva |
| 5    | — | `comportamiento_humano.py`, tests | ~4 | Funcionalidad nueva |
