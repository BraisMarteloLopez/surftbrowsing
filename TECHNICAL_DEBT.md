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

## Ítems descartados

Los siguientes ítems se documentan pero se descartan del plan de trabajo:

- **TD-05 (Selección de pestaña):** Riesgo bajo, el uso esperado es con una sola pestaña.
- **TD-06 (`asyncio.get_event_loop()` deprecado):** Funciona correctamente en el contexto actual. Se reevaluará si se migra a Python 3.13+.
- **TD-07 (Detección de CAPTCHA):** Complejidad alta, fuera del alcance actual. Requeriría integración con servicios de resolución de CAPTCHA o flujo manual.
- **TD-11 (Alerta en Linux):** El target principal es Windows. Se reevaluará si hay demanda.
