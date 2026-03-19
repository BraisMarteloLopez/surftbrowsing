# Plan de Trabajo — Resolución de Deuda Técnica

> Basado en: `TECHNICAL_DEBT.md` (2026-03-19)
> Ítems activos: TD-01, TD-02, TD-03, TD-04, TD-08, TD-09, TD-10, TD-12
> Ítems descartados: TD-05, TD-06, TD-07, TD-11

---

## Principios del plan

1. **Orden por dependencias**, no solo por severidad. Algunos fixes son prerequisito de otros.
2. **Cada fase produce un incremento funcional** que se puede probar de forma aislada.
3. **Tests se escriben en paralelo**, no al final. Cada fix incluye sus tests.
4. **Cero regresiones**: cada fase se valida contra los tests existentes antes de avanzar.

---

## Fase 1 — Infraestructura de testing (TD-10 parcial)

**Prioridad:** Primera, porque es prerequisito para validar todas las demás fases.
**Duración estimada:** Fundacional

### Tareas

1. **Instalar dependencias de testing:**
   - Añadir `pytest`, `pytest-asyncio` a un nuevo `requirements.txt` (o `requirements-dev.txt`).
   - Añadir `requirements.txt` con dependencias de producción (`websockets`, `python-dotenv`).

2. **Crear estructura de tests:**
   ```
   tests/
   ├── __init__.py
   ├── conftest.py           # Fixtures compartidas (mock WebSocket, mock CDPSession)
   ├── test_cdp_session.py   # Tests de CDPSession
   ├── test_js_helpers.py    # Tests de escape de strings y ejecución JS
   ├── test_detection.py     # Tests de detección de citas
   └── test_config.py        # Tests de validación de config
   ```

3. **Crear fixture `MockWebSocket`:**
   - Simula `websockets.WebSocketClientProtocol`.
   - Permite inyectar mensajes de respuesta y simular desconexiones.
   - Permite verificar mensajes enviados.

4. **Crear fixture `mock_cdp`:**
   - Instancia de `CDPSession` con `MockWebSocket`.
   - Con listener arrancado.
   - Helper para simular respuestas CDP a comandos específicos.

5. **Test de validación de `config.json`:**
   - Verificar que todas las keys obligatorias existen en el JSON real.
   - Verificar que los valores no están vacíos.
   - Verificar que `url_inicio` es una URL válida.

### Criterio de aceptación

- `pytest` se ejecuta y pasa sin errores (aunque haya 0 tests de lógica aún).
- Las fixtures `MockWebSocket` y `mock_cdp` permiten crear una `CDPSession` funcional en tests.
- Test de `config.json` pasa con el config actual.

---

## Fase 2 — Escape robusto de strings JS (TD-03)

**Prioridad:** Segunda, porque es una función utilitaria que las siguientes fases necesitan.
**Dependencia:** Fase 1 (tests).

### Tareas

1. **Crear función `safe_js_string(value: str) -> str`** en `cita_bot.py`:
   ```python
   def safe_js_string(value: str) -> str:
       """Escapa un string para interpolación segura dentro de un literal JS con comillas simples."""
       return (
           value
           .replace("\\", "\\\\")   # backslash primero (antes de que otros escapes lo generen)
           .replace("'", "\\'")     # comillas simples
           .replace("\n", "\\n")    # salto de línea
           .replace("\r", "\\r")    # retorno de carro
           .replace("\t", "\\t")    # tabulación
           .replace("\0", "\\0")    # null byte
       )
   ```

2. **Reemplazar todas las interpolaciones JS actuales** para usar `safe_js_string()`:
   - `paso_formulario_1()`: `valor` y `dropdown_id` → `safe_js_string(valor)`, `safe_js_string(dropdown_id)`
   - `paso_formulario_2()`: igual
   - `paso_formulario_4()`: `NIE` → `safe_js_string(NIE)`, eliminar el `replace("'", "\\'")` manual de `NOMBRE` y usar `safe_js_string(NOMBRE)`
   - `hay_cita_disponible()`: `texto_no_citas` → `safe_js_string(texto_no_citas)`
   - `click_salir()`: `boton_id` → `safe_js_string(boton_id)`
   - **Todos** los `f"document.getElementById('{x}')"` → `f"document.getElementById('{safe_js_string(x)}')"`.

3. **Tests en `tests/test_js_helpers.py`:**
   - `test_safe_js_string_simple`: input normal → sin cambios.
   - `test_safe_js_string_single_quote`: `O'Brien` → `O\\'Brien`.
   - `test_safe_js_string_backslash`: `a\\b` → `a\\\\b`.
   - `test_safe_js_string_newline`: `a\nb` → `a\\nb`.
   - `test_safe_js_string_combined`: múltiples caracteres especiales juntos.
   - `test_safe_js_string_empty`: string vacío → string vacío.
   - `test_safe_js_string_null_byte`: `a\0b` → `a\\0b`.

### Criterio de aceptación

- Todos los tests pasan.
- Ningún f-string en el código interpola valores sin pasar por `safe_js_string()`.
- El escape se aplica en el **orden correcto** (backslash primero).

---

## Fase 3 — Reconexión automática de WebSocket (TD-01)

**Prioridad:** Tercera. Es el fix más crítico, pero requiere cambios estructurales que se validan con la infraestructura de Fase 1.
**Dependencia:** Fase 1 (tests), Fase 2 (función utilitaria estable).

### Tareas

1. **Añadir estado de conexión a `CDPSession`:**
   ```python
   class CDPSession:
       def __init__(self, ws):
           ...
           self._alive = True    # ← NUEVO

       async def _listen(self):
           try:
               async for raw in self._ws:
                   ...
           except Exception as e:
               log_info(f"Listener CDP desconectado: {type(e).__name__}: {e}")
           finally:
               self._alive = False   # ← NUEVO: marcar como muerto
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

       @property
       def is_alive(self) -> bool:
           return self._alive

       async def send(self, method, params=None):
           if not self._alive:
               raise ConnectionError("Sesión CDP desconectada")
           ...  # resto igual
   ```

2. **Extraer la lógica de conexión en una función reutilizable:**
   ```python
   async def conectar_brave() -> tuple[websockets.WebSocketClientProtocol, CDPSession]:
       """Conecta a Brave y devuelve (ws, cdp) listos para usar."""
       ws_url = await obtener_ws_url()
       log_info(f"WebSocket: {ws_url}")
       ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
       cdp = CDPSession(ws)
       await cdp.start()
       await cdp.send("Page.enable")
       return ws, cdp
   ```

3. **Reestructurar `main()` con reconexión:**
   ```python
   async def main():
       ...
       ws, cdp = await conectar_brave()

       while True:
           try:
               if not cdp.is_alive:
                   log_info("Conexión CDP perdida. Reconectando...")
                   try:
                       await ws.close()
                   except Exception:
                       pass
                   await asyncio.sleep(2)
                   ws, cdp = await conectar_brave()
                   log_info("Reconexión exitosa.")

               # ... ciclo normal ...

           except ConnectionError:
               log("Conexión perdida durante el ciclo. Reconectando en 5s...")
               await asyncio.sleep(5)
               try:
                   ws, cdp = await conectar_brave()
               except ConnectionError:
                   log("Reconexión fallida. Reintentando en 15s...")
                   await asyncio.sleep(15)
   ```

4. **Tests en `tests/test_cdp_session.py`:**
   - `test_listen_sets_alive_false_on_disconnect`: Cerrar el MockWebSocket → `is_alive == False`.
   - `test_send_raises_when_disconnected`: Llamar `send()` con `_alive=False` → `ConnectionError`.
   - `test_pending_futures_resolved_on_disconnect`: Futures pendientes reciben `ConnectionError`.
   - `test_pre_wait_event_resolved_on_disconnect`: Futures de eventos pre-registrados reciben error.
   - `test_send_receive_happy_path`: Flujo normal funciona sin cambios.

### Criterio de aceptación

- El bot detecta desconexión en < 5 segundos (no espera al timeout de 15s).
- El bot se reconecta automáticamente y continúa el ciclo desde paso 0.
- Si Brave no está disponible en la reconexión, reintenta con backoff.
- Los Futures pendientes se resuelven con error (no quedan colgados).
- Todos los tests pasan.

---

## Fase 4 — Detección robusta de disponibilidad (TD-02)

**Prioridad:** Cuarta. Segundo fix más crítico, pero requiere la infraestructura de tests y el escape de strings.
**Dependencia:** Fase 1 (tests), Fase 2 (safe_js_string).

### Tareas

1. **Reemplazar `hay_cita_disponible()` por `evaluar_estado_pagina()`:**
   ```python
   class EstadoPagina:
       NO_HAY_CITAS = "no_hay_citas"
       HAY_CITAS = "hay_citas"
       ESTADO_DESCONOCIDO = "desconocido"

   async def evaluar_estado_pagina(cdp: CDPSession, ids: dict) -> str:
       """Evalúa el estado de la página tras solicitar cita.

       Verifica múltiples señales para evitar falsos positivos:
       1. Presencia del texto "no hay citas" (case-insensitive, parcial).
       2. Existencia de elementos conocidos del formulario de resultado.
       3. Contenido mínimo en el body (página no vacía/error).

       Returns:
           EstadoPagina.NO_HAY_CITAS | EstadoPagina.HAY_CITAS | EstadoPagina.ESTADO_DESCONOCIDO
       """
       # Espera breve para asegurar render completo
       await asyncio.sleep(1)

       # 1. Verificar que la página tiene contenido sustancial
       body_length = await ejecutar_js(cdp, "document.body.innerText.length;")
       if body_length.get("value", 0) < 50:
           return EstadoPagina.ESTADO_DESCONOCIDO  # Página vacía o error

       # 2. Buscar texto de "no hay citas" (case-insensitive, parcial)
       texto_check = await ejecutar_js(cdp, """
           document.body.innerText.toLowerCase().includes('no hay citas disponibles');
       """)
       if texto_check.get("value", False):
           # 3. Verificar que existe el botón "Salir" (confirma que estamos en la página correcta)
           boton_salir = safe_js_string(ids["boton_salir_nocita"])
           boton_existe = await ejecutar_js(cdp, f"""
               document.getElementById('{boton_salir}') !== null;
           """)
           if boton_existe.get("value", False):
               return EstadoPagina.NO_HAY_CITAS

       # 4. Si no encontró "no hay citas", verificar señales positivas de cita
       #    (buscar elementos del formulario de selección de fecha/hora u otros indicadores)
       url_check = await ejecutar_js(cdp, "window.location.href;")
       current_url = url_check.get("value", "")

       # Si estamos en una URL que no es del flujo esperado → estado desconocido
       if "icpplus" not in current_url and "icpplustiem" not in current_url:
           return EstadoPagina.ESTADO_DESCONOCIDO

       # Si no se encontró "no hay citas" Y la página tiene contenido → posible cita
       return EstadoPagina.HAY_CITAS
   ```

2. **Actualizar `main()` para manejar `ESTADO_DESCONOCIDO`:**
   ```python
   estado = await evaluar_estado_pagina(cdp, ids)

   if estado == EstadoPagina.HAY_CITAS:
       # ... alerta como antes ...
   elif estado == EstadoPagina.NO_HAY_CITAS:
       # ... reintentar como antes ...
   else:  # ESTADO_DESCONOCIDO
       log("ADVERTENCIA: Estado de página no reconocido. Posible error del portal.")
       log("Reiniciando ciclo en 15s...")
       await asyncio.sleep(15)
   ```

3. **Tests en `tests/test_detection.py`:**
   - `test_no_hay_citas_texto_exacto`: Texto original → `NO_HAY_CITAS`.
   - `test_no_hay_citas_sin_punto_final`: Sin punto → `NO_HAY_CITAS` (case-insensitive parcial).
   - `test_no_hay_citas_mayusculas`: "NO HAY CITAS DISPONIBLES" → `NO_HAY_CITAS`.
   - `test_hay_citas_contenido_diferente`: Contenido sin "no hay citas" + URL válida → `HAY_CITAS`.
   - `test_pagina_vacia_es_desconocido`: Body < 50 chars → `ESTADO_DESCONOCIDO`.
   - `test_pagina_error_es_desconocido`: Body con "500 Internal Server Error" → `ESTADO_DESCONOCIDO`.
   - `test_url_inesperada_es_desconocido`: URL sin "icpplus" → `ESTADO_DESCONOCIDO`.
   - `test_sin_boton_salir_es_desconocido`: Texto "no hay citas" pero sin botón Salir → revisa comportamiento.
   - `test_value_missing_from_result`: `ejecutar_js` devuelve `{}` → `ESTADO_DESCONOCIDO`.

### Criterio de aceptación

- Cero falsos positivos en los escenarios testeados.
- Estado desconocido **nunca** se trata como "hay cita" — siempre reinicia el ciclo.
- La detección tolera variaciones menores del texto del portal.
- Todos los tests pasan.

---

## Fase 5 — Resiliencia del loop principal (TD-04 + TD-08)

**Prioridad:** Quinta. Fixes complementarios que mejoran la robustez del ciclo.
**Dependencia:** Fase 3 (reconexión), Fase 4 (detección robusta).

### Tareas

#### TD-04: Manejo robusto de `click_salir()`

1. **Envolver `click_salir()` en try/except específico dentro del flujo:**
   ```python
   elif estado == EstadoPagina.NO_HAY_CITAS:
       log(f"Reintentando en {INTERVALO_REINTENTO}s...")
       try:
           await click_salir(cdp, ids)
       except (RuntimeError, asyncio.TimeoutError) as e:
           log(f"Aviso: click_salir() falló ({e}). Navegando al inicio directamente.")
           # No dormir 10s extra — el navegar() del siguiente ciclo corregirá
       await asyncio.sleep(INTERVALO_REINTENTO)
   ```

2. **Añadir verificación de URL post-navegación:**
   ```python
   # Tras navegar al inicio, verificar que estamos en la página correcta
   async def verificar_url_inicio(cdp: CDPSession, url_esperada: str) -> bool:
       result = await ejecutar_js(cdp, "window.location.href;")
       url_actual = result.get("value", "")
       return url_esperada in url_actual or url_actual.startswith(url_esperada.split("?")[0])
   ```

#### TD-08: Keep-alive con tráfico HTTP real

1. **Reemplazar `document.title` por fetch HTTP:**
   ```python
   async def mantener_sesion(cdp: CDPSession) -> None:
       """Keep-alive: genera tráfico HTTP real cada 30s para mantener sesión server-side."""
       while True:
           try:
               await ejecutar_js(cdp, """
                   fetch(window.location.href, {
                       method: 'HEAD',
                       credentials: 'same-origin'
                   }).catch(() => {});
               """)
           except Exception:
               pass
           await asyncio.sleep(30)
   ```

2. **Test (mock) para verificar que se ejecuta el JS correcto.**

### Criterio de aceptación

- `click_salir()` fallido no causa sleep de 10s extra ni propaga al handler genérico.
- El ciclo continúa limpiamente tras un `click_salir()` fallido.
- El keep-alive genera al menos un request HTTP real por intervalo.

---

## Fase 6 — Backoff adaptativo e inteligencia del loop (TD-09)

**Prioridad:** Sexta. Mejora de diseño que reduce riesgo de ban y mejora la experiencia.
**Dependencia:** Fase 5 (loop resiliente).

### Tareas

1. **Crear clase `BackoffController`:**
   ```python
   class BackoffController:
       """Controla intervalos de reintento con backoff exponencial y alertas."""

       def __init__(self, intervalo_base: float, max_intervalo: float = 300.0,
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
           """Registra un error y devuelve el intervalo de espera recomendado.

           Args:
               tipo: "timeout" | "js_error" | "desconocido" | "conexion"

           Returns:
               Segundos a esperar antes del próximo reintento.
           """
           self._errores_consecutivos += 1
           self._tipo_ultimo_error = tipo

           # Backoff exponencial: base * 2^(n-1), con cap
           intervalo = min(
               self.intervalo_base * (2 ** (self._errores_consecutivos - 1)),
               self.max_intervalo
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
   ```

2. **Integrar en `main()`:**
   ```python
   backoff = BackoffController(
       intervalo_base=5.0,        # Empieza con 5s tras primer error
       max_intervalo=300.0,       # Máximo 5 minutos entre reintentos
       umbral_alerta=10           # Alertar tras 10 errores consecutivos
   )

   while True:
       try:
           # ... ciclo normal ...
           if estado == EstadoPagina.NO_HAY_CITAS:
               backoff.registrar_exito()
               await asyncio.sleep(INTERVALO_REINTENTO)
           # ...
       except asyncio.TimeoutError:
           espera = backoff.registrar_error("timeout")
           log(f"Timeout. Reintentando en {espera:.0f}s... (error #{backoff.errores_consecutivos})")
           if backoff.debe_alertar:
               log("ALERTA: Demasiados errores consecutivos. Posible problema con el portal o la conexión.")
           await asyncio.sleep(espera)
       except RuntimeError as e:
           espera = backoff.registrar_error("js_error")
           log(f"Error JS: {e}. Reintentando en {espera:.0f}s... (error #{backoff.errores_consecutivos})")
           if backoff.debe_alertar:
               log("ALERTA: Demasiados errores JS consecutivos. Posible cambio en el portal.")
           await asyncio.sleep(espera)
   ```

3. **Tests en `tests/test_backoff.py`:**
   - `test_backoff_exponencial`: Verificar secuencia 5, 10, 20, 40, 80...
   - `test_backoff_max_cap`: Verificar que no excede `max_intervalo`.
   - `test_backoff_reset_on_success`: `registrar_exito()` resetea contador.
   - `test_alerta_umbral`: `debe_alertar` es `True` tras N errores.
   - `test_alerta_no_antes_umbral`: `debe_alertar` es `False` con < N errores.

### Criterio de aceptación

- Tras errores, los reintentos se espacian exponencialmente.
- Tras un ciclo exitoso, los intervalos vuelven a la normalidad.
- El usuario recibe alerta clara tras N errores consecutivos.
- El intervalo nunca excede `max_intervalo`.

---

## Fase 7 — Timeouts diferenciados (TD-12)

**Prioridad:** Séptima. Mejora menor pero que completa la robustez.
**Dependencia:** Fase 3 (cambios en CDPSession).

### Tareas

1. **Definir constantes de timeout diferenciadas:**
   ```python
   # En la sección de configuración
   TIMEOUT_NAVEGACION = TIMEOUT_PAGINA          # 15s — para Page.navigate + load
   TIMEOUT_JS_SIMPLE = 5.0                       # 5s — para Runtime.evaluate simples
   TIMEOUT_KEEPALIVE = 3.0                        # 3s — para lecturas de keep-alive
   ```

2. **Añadir parámetro `timeout` a `ejecutar_js()`:**
   ```python
   async def ejecutar_js(cdp: CDPSession, expression: str, timeout: float = TIMEOUT_JS_SIMPLE) -> dict:
       result = await cdp.send("Runtime.evaluate", {
           "expression": expression,
           "returnByValue": True,
           "awaitPromise": False,
       }, timeout=timeout)   # ← pasar timeout
       ...
   ```

3. **Añadir parámetro `timeout` a `CDPSession.send()`:**
   ```python
   async def send(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
       ...
       t = timeout if timeout is not None else TIMEOUT_PAGINA
       return await asyncio.wait_for(fut, timeout=t)
   ```

4. **Actualizar todas las llamadas:**
   - `navegar()`: usa `TIMEOUT_NAVEGACION` (ya es el default).
   - `click_y_esperar_carga()`: usa `TIMEOUT_NAVEGACION`.
   - `ejecutar_js()` en pasos de formulario: usa `TIMEOUT_JS_SIMPLE` (default nuevo).
   - `mantener_sesion()`: usa `TIMEOUT_KEEPALIVE`.

5. **Tests para verificar que los timeouts se aplican correctamente.**

### Criterio de aceptación

- Lecturas JS simples no esperan más de 5s.
- Keep-alive no espera más de 3s.
- Navegación mantiene 15s como antes.
- Todos los tests existentes siguen pasando.

---

## Fase 8 — Tests de integración y cobertura (TD-10 completo)

**Prioridad:** Última. Cierra la deuda de testing una vez todo el código está estabilizado.
**Dependencia:** Todas las fases anteriores.

### Tareas

1. **Test de integración end-to-end con mocks:**
   - Simular un ciclo completo (pasos 0-5) con MockWebSocket que devuelve respuestas predefinidas para cada formulario.
   - Verificar que se ejecutan los JS esperados en el orden correcto.
   - Verificar que el ciclo termina con el estado correcto.

2. **Tests de reconexión (integración):**
   - Simular desconexión a mitad de ciclo → verificar reconexión → verificar reinicio desde paso 0.

3. **Tests de backoff (integración):**
   - Simular 5 timeouts consecutivos → verificar que los intervalos crecen.
   - Simular éxito tras errores → verificar reset.

4. **Medir cobertura con `pytest-cov`:**
   - Target: >= 80% de cobertura en `cita_bot.py`.
   - Documentar líneas no cubiertas y justificar (ej. `winsound`, `asyncio.run`).

5. **Añadir `pytest` a CI si hay pipeline (opcional).**

### Criterio de aceptación

- `pytest --cov` reporta >= 80% de cobertura.
- Todos los escenarios de error documentados en `TECHNICAL_DEBT.md` tienen al menos un test.
- `pytest` se puede ejecutar sin conexión a Brave ni al portal real.

---

## Resumen del plan

| Fase | TD resueltos | Cambios principales | Archivos afectados |
|------|-------------|---------------------|-------------------|
| 1 | TD-10 (parcial) | Infraestructura de testing, fixtures | `requirements.txt`, `tests/*` |
| 2 | TD-03 | `safe_js_string()`, escape en todos los f-strings | `cita_bot.py`, `tests/test_js_helpers.py` |
| 3 | TD-01 | `_alive`, reconexión automática, `conectar_brave()` | `cita_bot.py`, `tests/test_cdp_session.py` |
| 4 | TD-02 | `evaluar_estado_pagina()`, `EstadoPagina` | `cita_bot.py`, `tests/test_detection.py` |
| 5 | TD-04, TD-08 | try/except en `click_salir`, keep-alive HTTP | `cita_bot.py` |
| 6 | TD-09 | `BackoffController` | `cita_bot.py`, `tests/test_backoff.py` |
| 7 | TD-12 | Timeouts diferenciados por operación | `cita_bot.py` |
| 8 | TD-10 (completo) | Tests de integración, cobertura >= 80% | `tests/*` |

### Orden de ejecución y dependencias

```
Fase 1 (testing infra)
  ├──→ Fase 2 (escape strings)
  │       └──→ Fase 3 (reconexión WS) ──→ Fase 7 (timeouts)
  │               └──→ Fase 4 (detección robusta)
  │                       └──→ Fase 5 (resiliencia loop)
  │                               └──→ Fase 6 (backoff)
  │                                       └──→ Fase 8 (integración + cobertura)
  └──→ (fixture base para todas las fases)
```
