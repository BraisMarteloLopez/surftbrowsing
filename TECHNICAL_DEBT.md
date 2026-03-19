# Deuda Técnica — cita_bot

> Auditoría exhaustiva del código fuente. Fecha: 2026-03-19
> Archivo analizado: `cita_bot.py` (475 líneas), `config.json`, `.env.example`

---

## Índice

| ID | Título | Severidad | Probabilidad | Estado |
|----|--------|-----------|-------------|--------|
| TD-01 | WebSocket muerto sin reconexión | **CRÍTICA** | Alta | **Resuelto** |
| TD-02 | Falso positivo en detección de citas | **CRÍTICA** | Media | **Resuelto** |
| TD-03 | Escape de strings insuficiente en JS | Media-Alta | Baja | **Resuelto** |
| TD-04 | `click_salir()` rompe el loop | Media | Media | **Resuelto** |
| TD-05 | Selección de pestaña no determinista | Media | Baja-Media | Descartada |
| TD-06 | `asyncio.get_event_loop()` deprecado | Baja-Media | Baja | Descartada |
| TD-07 | Sin detección de CAPTCHA | Crítica | Media-Alta | Descartada |
| TD-08 | Keep-alive no genera tráfico HTTP real | Media | Alta | **Resuelto** |
| TD-09 | Intervalo fijo sin backoff adaptativo | Media (Diseño) | N/A | **Resuelto** |
| TD-10 | Sin tests automatizados | Media (Calidad) | N/A | **Resuelto** |
| TD-11 | Alerta sonora inútil en Linux/Mac | Baja | Alta en Linux | Descartada |
| TD-12 | Timeout uniforme para todas las operaciones CDP | Baja-Media | Baja | **Resuelto** |
| TD-13 | `esperar_elemento` escapa IDs redundantemente | Baja-Media | Baja | **Resuelto** |
| TD-14 | `click_salir` lanza RuntimeError en vez de tolerar fallos | Media | Media | Pendiente |
| TD-15 | `scroll_humano` se ejecuta antes de verificar que la página cargó | Media | Media-Alta | Pendiente |
| TD-16 | `asyncio.get_event_loop()` deprecado en `esperar_elemento` | Baja | Baja | Pendiente |
| TD-17 | Timeout de `esperar_elemento` hardcoded (10s) | Baja-Media | Baja | Pendiente |

---

## TD-01 — WebSocket muerto sin reconexión

**Severidad:** CRÍTICA
**Probabilidad:** Alta (cualquier inestabilidad de red, reinicio de Brave, suspensión del SO)
**Ubicación:** `cita_bot.py:97-112`, `cita_bot.py:407-408`

### Descripción

El listener `_listen()` (línea 97) es la única goroutine que consume mensajes del WebSocket. Si la conexión se corta por cualquier motivo (Brave crashea, la red cae momentáneamente, el SO entra en suspensión), el `except Exception: pass` de la línea 111 silencia el error y el listener muere.

**Nadie detecta que el listener murió.** El bot sigue en el loop principal intentando enviar comandos CDP a través de `send()` (línea 114). Cada llamada a `send()` envía el mensaje al WebSocket muerto, pero el `Future` nunca recibe respuesta porque no hay listener. Resultado: **cada operación espera `TIMEOUT_PAGINA` (15s) y lanza `TimeoutError`**. El handler de `TimeoutError` (línea 454) duerme 5s y reintenta, creando un bucle zombi:

```
[Ciclo zombi]: send() → 15s timeout → sleep 5s → send() → 15s timeout → ∞
```

El bot queda vivo en apariencia (imprime logs de timeout) pero es completamente inútil. Requiere kill manual + relanzamiento.

### Análisis de impacto

- **Escenario 1:** Brave se actualiza automáticamente y se reinicia → WebSocket muerto.
- **Escenario 2:** Laptop entra en suspensión 5 minutos → la conexión TCP del WS se cierra por timeout.
- **Escenario 3:** Router reinicia → misma consecuencia.
- En todos los casos, el bot deja de funcionar pero no lo comunica al usuario.

### Solución propuesta

1. Detectar muerte del listener: cuando `_listen()` termina, marcar la sesión como "desconectada".
2. En `send()`, verificar que la sesión está viva antes de enviar. Si no, lanzar `ConnectionError`.
3. En `main()`, capturar `ConnectionError` y ejecutar **reconexión automática**:
   - Llamar de nuevo a `obtener_ws_url()`.
   - Abrir nuevo WebSocket.
   - Crear nueva `CDPSession`.
   - Continuar el loop desde paso 0.
4. Implementar un health-check periódico (ping CDP cada N segundos) para detectar desconexión proactivamente.

### Código afectado

```python
# Línea 111-112 — silencioso y mortal
except Exception:
    pass  # listener murió sin aviso

# Línea 407-408 — conexión sin retry
async with websockets.connect(ws_url, ...) as ws:
    # Si la conexión se pierde, se sale del context manager y el bot termina
```

---

## TD-02 — Falso positivo en detección de citas

**Severidad:** CRÍTICA
**Probabilidad:** Media (cambio mínimo en el portal, carga lenta de página, página de error)
**Ubicación:** `cita_bot.py:290-297`, `config.json:16`

### Descripción

La función `hay_cita_disponible()` determina si hay cita mediante **negación de un string exacto**:

```python
result = await ejecutar_js(cdp, f"""
    document.body.innerText.includes('{texto_no_citas}');
""")
no_hay = result.get("value", False)
return not no_hay  # Si NO encuentra "no hay citas" → asume que SÍ hay
```

**Problema 1: Fragilidad ante cambios del portal.** Si el portal cambia una sola letra del mensaje ("En este momento no hay citas disponibles" sin punto final, o "No hay citas disponibles en este momento"), `includes()` devuelve `False` → el bot asume que HAY cita → **falso positivo permanente en cada ciclo**.

**Problema 2: Carga lenta / DOM incompleto.** No hay espera explícita a que el contenido del paso 5 esté renderizado. Si `ejecutar_js` se ejecuta antes de que el texto aparezca en el DOM, `includes()` devuelve `False` → falso positivo.

**Problema 3: Páginas de error.** Si el portal devuelve un error 500, una página de mantenimiento, o un redirect inesperado, el texto "no hay citas" no existe → el bot interpreta cualquier error como "hay cita".

**Problema 4: El valor por defecto de `result.get("value", False)`.** Si `ejecutar_js` devuelve un resultado inesperado (sin key "value"), el default es `False` → `not False` → `True` → falso positivo.

### Análisis de impacto

Un falso positivo dispara `alerta_sonora()` + `mantener_sesion()` (línea 445-448) que es un `asyncio.gather` **sin retorno**. El bot entra en modo alerta permanente y **deja de buscar citas**. El usuario corre al ordenador, ve que no hay cita, y tiene que matar el bot manualmente. Si está durmiendo, pierde toda la noche de búsqueda.

### Solución propuesta

1. **Validación positiva del estado de la página:** En lugar de solo buscar "no hay citas", verificar también la presencia de elementos esperados del paso 5 (ej. que exista el botón "Salir", el contenedor de resultados, etc.). Si la página no coincide con ningún estado conocido → tratar como error, no como cita.
2. **Espera explícita del contenido:** Implementar un polling breve (ej. 3 intentos, 1s entre cada uno) para verificar que `document.body.innerText` contiene contenido sustancial antes de evaluar.
3. **Búsqueda parcial / case-insensitive:** Usar `toLowerCase().includes("no hay citas disponibles")` en vez de coincidencia exacta con puntuación.
4. **Validación estructural:** Verificar que la URL actual corresponde al paso esperado del flujo.

---

## TD-03 — Escape de strings insuficiente en inyección JS

**Severidad:** Media-Alta
**Probabilidad:** Baja (requiere caracteres especiales en inputs)
**Ubicación:** `cita_bot.py:257-269`, `cita_bot.py:208-210`, `cita_bot.py:227-229`, todas las funciones `paso_formulario_*`

### Descripción

Todas las inyecciones JavaScript se construyen con f-strings y concatenación directa de valores:

```python
# Línea 265 — solo escapa comillas simples
nombre_escaped = NOMBRE.replace("'", "\\'")

# Línea 258 — NIE sin escapar
await ejecutar_js(cdp, f"""
    document.getElementById('{input_nie}').value = '{NIE}';
""")

# Línea 208 — IDs de config.json sin escapar
await ejecutar_js(cdp, f"""
    document.getElementById('{dropdown_id}').value = '{valor}';
""")
```

**Vectores de falla:**

| Input | Resultado |
|-------|-----------|
| `NIE = "X123'; alert('XSS');//"` | Ejecución JS arbitraria en el navegador |
| `NOMBRE = "O'Brien"` | Escapado correctamente (comilla simple) |
| `NOMBRE = "Test\nLine"` | JS syntax error (salto de línea dentro de string literal) |
| `NOMBRE = "Test\\Other"` | Backslash interpretado como escape JS |
| `config.json id = "'); alert(1);//"` | Ejecución JS arbitraria |

No es un riesgo de seguridad real (el usuario se atacaría a sí mismo), pero es un **punto de falla silenciosa**: un NIE o nombre con caracteres inesperados causa `RuntimeError` en `ejecutar_js` y el bot entra en el loop de error sin explicar la causa.

### Solución propuesta

Crear una función `safe_js_string(value: str) -> str` que:
1. Escape `\` → `\\`
2. Escape `'` → `\'`
3. Escape `\n` → `\\n`
4. Escape `\r` → `\\r`
5. Escape `\t` → `\\t`

Aplicar esta función a **todos** los valores interpolados en JavaScript, tanto de `.env` como de `config.json`.

---

## TD-04 — `click_salir()` falla = estado inconsistente del loop

**Severidad:** Media
**Probabilidad:** Media (el botón "Salir" puede no existir si la página cambió o cargó con error)
**Ubicación:** `cita_bot.py:300-303`, `cita_bot.py:449-452`

### Descripción

Después de detectar "no hay citas", el flujo es:

```python
# Línea 450-452
log(f"Reintentando en {INTERVALO_REINTENTO}s...")
await click_salir(cdp, ids)           # ← puede fallar
await asyncio.sleep(INTERVALO_REINTENTO)
```

Si `click_salir()` lanza `RuntimeError` (botón no encontrado) o `TimeoutError` (página no carga tras click), la excepción se propaga al handler genérico (línea 458/463) que duerme 10s y reintenta el ciclo completo.

**El problema:** el siguiente ciclo comienza con `navegar(cdp, url_inicio)` que **debería** corregir el estado. Pero hay escenarios donde esto no basta:

1. **Cookies de sesión corrompidas:** Si el portal ICP tiene estado server-side vinculado a la sesión, navegar al inicio puede no resetear correctamente. El formulario 1 puede mostrar datos del ciclo anterior.
2. **Popup o modal bloqueante:** Si al fallar `click_salir()` queda un modal JS abierto, `navegar()` puede no ejecutar la navegación correctamente.
3. **Redirección a login/expiración:** Si la sesión expiró server-side, la navegación puede redirigir a otra URL que no es el formulario esperado.

### Solución propuesta

1. Envolver `click_salir()` en su propio try/except dentro del flujo principal (no depender del handler genérico).
2. Si falla, loguear warning y continuar directamente con `navegar(url_inicio)` — no dormir 10s extra.
3. Después de `navegar()`, verificar que la URL actual coincide con `url_inicio` (validar estado).

---

## TD-08 — Keep-alive no genera tráfico HTTP al servidor

**Severidad:** Media
**Probabilidad:** Alta (la sesión del portal tiene timeout server-side)
**Ubicación:** `cita_bot.py:327-334`

### Descripción

```python
async def mantener_sesion(cdp: CDPSession) -> None:
    while True:
        try:
            await ejecutar_js(cdp, "document.title;")
        except Exception:
            pass
        await asyncio.sleep(30)
```

`document.title` es una lectura local del DOM — **no genera ninguna petición HTTP al servidor**. La sesión del portal ICP se mantiene mediante cookies HTTP con expiración controlada server-side. Si el servidor invalida la sesión tras N minutos de inactividad HTTP, este keep-alive no hace absolutamente nada.

**Consecuencia:** El usuario recibe la alerta de "CITA DISPONIBLE", corre al ordenador, y al intentar completar el formulario manualmente, la sesión ha expirado. El portal muestra un error o redirige al inicio. **La cita se pierde.**

### Solución propuesta

Reemplazar `document.title` por una operación que genere un request HTTP real:

```javascript
// Opción 1: fetch a la misma URL del portal (no navega, solo refresca sesión)
fetch(window.location.href, { method: 'HEAD', credentials: 'same-origin' });

// Opción 2: XMLHttpRequest (más compatible)
var xhr = new XMLHttpRequest();
xhr.open('HEAD', window.location.href, true);
xhr.send();
```

Esto envía un request HTTP con las cookies de sesión, manteniendo la sesión viva server-side.

---

## TD-09 — Intervalo de reintento fijo sin backoff adaptativo

**Severidad:** Media (Diseño)
**Probabilidad:** N/A (es una limitación de diseño)
**Ubicación:** `cita_bot.py:32`, `cita_bot.py:452`

### Descripción

El intervalo entre reintentos es un valor fijo configurable (`INTERVALO_REINTENTO`, default 60s). No hay adaptación al estado del portal:

1. **Si hay muchos timeouts seguidos:** probablemente el portal está congestionado. Deberían espaciarse los reintentos (backoff exponencial) para no empeorar la congestión y arriesgar un ban por IP.
2. **Si hay errores JS seguidos:** probablemente el portal cambió sus IDs. Reintentar cada 60s con los mismos IDs es inútil; el bot debería alertar tras N errores consecutivos del mismo tipo.
3. **Si todo va bien:** el intervalo de 60s puede ser excesivo. Si las citas aparecen y desaparecen en segundos, un intervalo adaptativo más corto (20-30s) tras ciclos exitosos aumentaría la probabilidad de capturar una.
4. **Sin límite de errores:** El bot reintenta indefinidamente sin importar cuántas veces falle. No hay mecanismo para alertar al usuario después de, digamos, 20 errores consecutivos.

### Solución propuesta

Implementar una estrategia de backoff con tres modos:

| Estado | Intervalo | Comportamiento |
|--------|-----------|----------------|
| Ciclo exitoso (no hay citas) | `INTERVALO_REINTENTO` (configurable) | Normal |
| Timeout | Backoff exponencial: base * 2^n (max 5 min) | Descongestionar |
| Error JS | Backoff + alerta tras N consecutivos | Detectar cambio de portal |
| Error inesperado | Backoff + alerta tras N consecutivos | Detectar problemas sistémicos |

Incluir un **contador de errores consecutivos** que dispare una alerta especial si supera un umbral configurable.

---

## TD-10 — Sin tests automatizados

**Severidad:** Media (Calidad)
**Probabilidad:** N/A (es una carencia estructural)
**Ubicación:** Todo el proyecto

### Descripción

No hay ningún test automatizado. La única forma de verificar que el código funciona es ejecutarlo contra el portal real. Esto implica:

1. **Cualquier cambio en `config.json` es no verificable** sin ejecutar manualmente contra el portal.
2. **Refactors son arriesgados** — no hay red de seguridad.
3. **La lógica de `CDPSession` no tiene tests unitarios** — el manejo de callbacks, eventos, timeouts, y la coordinación `send()`/`_listen()` solo se prueban implícitamente.
4. **La lógica de detección de citas no tiene tests** — los escenarios de falso positivo descritos en TD-02 nunca se verifican.
5. **El escape de strings no tiene tests** — los edge cases de TD-03 nunca se verifican.

### Solución propuesta

Crear tests unitarios para las capas que no dependen del portal real:

1. **`CDPSession`:** Mock del WebSocket para verificar send/receive, timeouts, muerte del listener, pre_wait_event.
2. **`hay_cita_disponible()`:** Mock de `ejecutar_js` para probar todos los escenarios (texto exacto, texto parcial, sin texto, error JS, DOM vacío).
3. **`safe_js_string()`** (nueva función de TD-03): Tests paramétricos con caracteres especiales.
4. **Validación de `config.json`:** Test que verifica que todas las keys esperadas existen.
5. **Validación de `.env`:** Test que verifica comportamiento con variables vacías, inválidas, etc.

Framework recomendado: `pytest` + `pytest-asyncio`.

---

## TD-12 — Timeout uniforme para todas las operaciones CDP

**Severidad:** Baja-Media
**Probabilidad:** Baja (solo impacta en condiciones de red degradada)
**Ubicación:** `cita_bot.py:124`, `cita_bot.py:136`, `cita_bot.py:141`

### Descripción

Todas las operaciones CDP usan `TIMEOUT_PAGINA` (default 15s) como timeout:

```python
# Línea 124 — send() genérico
return await asyncio.wait_for(fut, timeout=TIMEOUT_PAGINA)
```

Esto incluye:
- **Navegación** (`Page.navigate` + `Page.loadEventFired`): 15s es razonable.
- **Evaluación JS simple** (`document.title`, `document.body.innerText.includes(...)`): 15s es excesivo. Si una lectura DOM tarda 15s, algo está muy mal.
- **Click + carga** (`click_y_esperar_carga`): 15s es razonable.
- **Keep-alive** (`mantener_sesion`): 15s para leer el título es absurdo.

**Consecuencia:** Si el WebSocket está degradado (alto latency), operaciones triviales esperan hasta 15s antes de timeout, ralentizando enormemente cada ciclo (que tiene ~10 operaciones JS = hasta 150s de espera potencial).

### Solución propuesta

Diferenciar timeouts por tipo de operación:

```python
TIMEOUT_NAVEGACION = TIMEOUT_PAGINA  # 15s — para Page.navigate + load
TIMEOUT_JS = 5.0                     # 5s — para Runtime.evaluate simples
TIMEOUT_KEEPALIVE = 3.0              # 3s — para operaciones de keep-alive
```

Pasar `timeout` como parámetro a `send()` o usar un wrapper que seleccione el timeout según el método CDP.

---

## TD-13 — `esperar_elemento` escapa IDs redundantemente

**Severidad:** Baja-Media
**Probabilidad:** Baja (los IDs actuales de `config.json` no tienen caracteres especiales)
**Ubicación:** `cita_bot.py:300-310`, funciones `paso_formulario_1` a `paso_formulario_5`

### Descripción

`esperar_elemento()` aplica `safe_js_string()` internamente al `element_id`:

```python
async def esperar_elemento(cdp, element_id, ...):
    escaped = safe_js_string(element_id)  # escapa aquí
```

Pero cada formulario **también** escapa el mismo ID por su cuenta:

```python
dropdown_id = safe_js_string(ids["dropdown_provincia"])  # escapa aquí también
if not await esperar_elemento(cdp, ids["dropdown_provincia"]):  # y aquí otra vez dentro
```

El ID se escapa en dos sitios distintos con dos variables distintas. Funciona por casualidad porque los IDs del `config.json` no contienen caracteres especiales. Si algún día un ID tuviera una comilla simple, no habría doble-escape (porque se escapan sobre la misma fuente `ids[...]`, no uno sobre el resultado del otro), pero la redundancia genera confusión y es un punto frágil de mantenimiento.

### Solución propuesta

Definir una convención única: o `esperar_elemento` recibe el ID **ya escapado**, o lo escapa internamente y los formularios no lo escapan para esa llamada. La opción más limpia: `esperar_elemento` recibe el ID **crudo** y se responsabiliza de escaparlo. Los formularios solo escapan cuando construyen el JS de escritura/click.

---

## TD-14 — `click_salir` lanza RuntimeError en vez de tolerar fallos

**Severidad:** Media
**Probabilidad:** Media (página cargada parcialmente, sesión expirada, portal en mantenimiento)
**Ubicación:** `cita_bot.py:492-499`

### Descripción

`click_salir()` ahora incluye `esperar_elemento` que lanza `RuntimeError` si el botón no aparece en 10s:

```python
async def click_salir(cdp, ids):
    if not await esperar_elemento(cdp, ids["boton_salir_nocita"]):
        raise RuntimeError(...)  # ← explota
    await click_y_esperar_carga(...)
```

`click_salir` es una función de **limpieza/navegación** que se ejecuta después de detectar "no hay citas". Su propósito es devolver al usuario al inicio del portal. Si falla, el ciclo debería simplemente navegar al inicio directamente (`navegar(cdp, url_inicio)`). No debería ser tratado con la misma severidad que un fallo en un formulario.

Sin embargo, al lanzar `RuntimeError`, sube al handler genérico del `main()` que aplica backoff exponencial — es decir, un fallo de limpieza produce una penalización de tiempo idéntica a un fallo estructural del portal.

### Solución propuesta

`click_salir` debería ser tolerante a fallos:

```python
async def click_salir(cdp, ids):
    if not await esperar_elemento(cdp, ids["boton_salir_nocita"]):
        log("Botón Salir no encontrado, se navegará al inicio directamente")
        return False  # señal de que no se pudo salir limpiamente
    await click_y_esperar_carga(...)
    return True
```

El llamador en `main()` usaría el retorno para decidir si necesita `navegar(url_inicio)` explícitamente.

---

## TD-15 — `scroll_humano` se ejecuta antes de verificar que la página cargó

**Severidad:** Media
**Probabilidad:** Media-Alta (cualquier carga lenta del portal)
**Ubicación:** `cita_bot.py:333-353` (F1), `cita_bot.py:356-376` (F2), `cita_bot.py:379-391` (F3)

### Descripción

En los formularios 1, 2 y 3, el orden de operaciones es:

```python
await scroll_humano(cdp)                          # 1. scroll
await delay()                                      # 2. espera
if not await esperar_elemento(cdp, ids[...]):       # 3. verificar que el DOM está listo
    raise RuntimeError(...)
await ejecutar_js(cdp, ...)                        # 4. actuar
```

El problema es que `scroll_humano` (paso 1) se ejecuta **antes** de `esperar_elemento` (paso 3). Si la página aún no ha cargado completamente, estamos haciendo scroll sobre una página vacía o parcialmente renderizada. Los scrolls no fallan (JS no da error al hacer scrollBy sobre un body vacío), pero:

1. **No simulan comportamiento humano real**: un humano no hace scroll si la página no ha cargado.
2. **El delay posterior (paso 2) desperdicia tiempo**: estamos esperando después de scrollear la nada.
3. **Anti-bot detection**: un servidor que correlacione eventos de scroll con estado de renderizado podría detectar scrolls sobre contenido no cargado como señal de automatización.

### Solución propuesta

Invertir el orden: primero verificar que el elemento existe, luego hacer scroll y delay:

```python
if not await esperar_elemento(cdp, ids[...]):
    raise RuntimeError(...)
await scroll_humano(cdp)
await delay()
await ejecutar_js(cdp, ...)
```

---

## TD-16 — `asyncio.get_event_loop()` deprecado en `esperar_elemento`

**Severidad:** Baja
**Probabilidad:** Baja (funciona en Python 3.10-3.12, warning en 3.13+)
**Ubicación:** `cita_bot.py:303-304`

### Descripción

```python
inicio = asyncio.get_event_loop().time()
while (asyncio.get_event_loop().time() - inicio) < timeout:
```

`asyncio.get_event_loop()` está deprecado desde Python 3.10 y emitirá `DeprecationWarning` en 3.12+. En Python 3.13+ podría ser removido. Además, se llama dos veces por iteración del loop de polling, lo cual es innecesario.

### Solución propuesta

Usar `time.monotonic()` que es más simple, no depende del event loop, y es más legible:

```python
import time

inicio = time.monotonic()
while (time.monotonic() - inicio) < timeout:
```

Alternativa: `asyncio.get_running_loop().time()` si se quiere mantener la semántica del event loop.

---

## TD-17 — Timeout de `esperar_elemento` hardcoded (10s)

**Severidad:** Baja-Media
**Probabilidad:** Baja (10s es razonable para la mayoría de cargas)
**Ubicación:** `cita_bot.py:300`

### Descripción

```python
async def esperar_elemento(cdp, element_id, timeout: float = 10.0) -> bool:
```

El timeout por defecto es 10s, hardcoded. Todos los demás tiempos del bot son configurables vía `.env` (`DELAY_ACCION_BASE`, `DELAY_SCROLL_MIN`, `DELAY_EVALUACION_MIN`, `TIMEOUT_CARGA_PAGINA_SEGUNDOS`, etc.). Este es el único timing que no se puede ajustar sin tocar el código.

En conexiones lentas o portales congestionados, 10s podría ser insuficiente. En conexiones rápidas, 10s de espera antes de reportar error es excesivo y retrasa la detección de problemas reales.

### Solución propuesta

Añadir variable de entorno `TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS` con default 10:

```python
TIMEOUT_ESPERA_ELEMENTO = float(os.getenv("TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS", "10"))
```

Y usarla como default del parámetro:

```python
async def esperar_elemento(cdp, element_id, timeout: float = TIMEOUT_ESPERA_ELEMENTO):
```

---

## Ítems descartados

Los siguientes ítems se documentan pero se descartan del plan de trabajo:

- **TD-05 (Selección de pestaña):** Riesgo bajo, el uso esperado es con una sola pestaña.
- **TD-06 (`asyncio.get_event_loop()` deprecado):** Subsumido por TD-16 que cubre el mismo problema en `esperar_elemento`.
- **TD-07 (Detección de CAPTCHA):** Complejidad alta, fuera del alcance actual. Requeriría integración con servicios de resolución de CAPTCHA o flujo manual.
- **TD-11 (Alerta en Linux):** El target principal es Windows. Se reevaluará si hay demanda.
