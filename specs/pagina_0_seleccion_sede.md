# Especificación — Página 0: Selección de Sede

**Estado:** Pendiente de implementación
**Archivo destino:** `humano.py` → `async def fase_0(sesion, personalidad, es_primera_vez)`

---

## Resumen

Esta página es el punto de entrada al formulario ICP. Contiene un `<select>` de provincia y un botón "Aceptar". El objetivo es seleccionar "Madrid" y avanzar.

**Elementos HTML objetivo:**
| Elemento | Selector | Tipo |
|----------|----------|------|
| Desplegable provincia | `<select id="form" name="form">` | `<select>` nativo |
| Botón aceptar | `<input id="btnAceptar" onclick="envia()" value="Aceptar" class="mf-button primary" type="button">` | `<input type="button">` |

**Valor a seleccionar:** La opción cuyo `textContent` sea `"Madrid"` (NO insertar valor directamente).

---

## Flujo de entrada

| Contexto | Cómo llegamos |
|----------|---------------|
| Primera ejecución | Navegación directa a `url_inicio` |
| Reintento (no hay citas) | Click en botón de volver dentro del flujo (NO navegación a URL) |

---

## Secuencia de micro-acciones

### PASO 1 — Navegación / Retorno

```
SI es_primera_vez:
    1a. CDP: Page.navigate(url=config.url_inicio)
    1b. ESPERA OBLIGATORIA: Page.loadEventFired (timeout=TIMEOUT_CARGA_PAGINA)
    1c. ESPERA OBLIGATORIA: waitForElement("#form", timeout=TIMEOUT_ESPERA_ELEMENTO)
    1d. SEGURIDAD: detectar_waf() → si WAF, abortar fase con WafBanError
SINO (reintento):
    1a. (El botón de volver ya nos trajo aquí desde otra fase)
    1b. ESPERA OBLIGATORIA: Page.loadEventFired (timeout=TIMEOUT_CARGA_PAGINA)
    1c. ESPERA OBLIGATORIA: waitForElement("#form", timeout=TIMEOUT_ESPERA_ELEMENTO)
    1d. SEGURIDAD: detectar_waf()
```

**Detalle de `waitForElement(selector, timeout)`:**
- Polling cada 300ms via CDP: `Runtime.evaluate` → `document.querySelector(selector)`
- Verifica que el elemento existe en DOM Y es visible (`offsetParent !== null` o `getComputedStyle().display !== 'none'`)
- Si timeout se agota → lanzar excepción `ElementoNoEncontrado`

---

### PASO 2 — Aterrizaje (orientación visual)

```
2a. DELAY: pausa de orientación
    - Rango base: uniform(1.0, 3.0)s
    - Modulado por personalidad.velocidad:
      · rapido:  × 0.6  → effective range: 0.6 - 1.8s
      · normal:  × 1.0  → effective range: 1.0 - 3.0s
      · lento:   × 1.5  → effective range: 1.5 - 4.5s

2b. ACCIÓN: micro-movimientos de ratón (simular "mirar la pantalla")
    - Cantidad: randint(1, 2) movimientos
    - Cada movimiento:
      · Destino: posición actual ± uniform(-80, 80)px en X, ± uniform(-50, 50)px en Y
      · Duración del movimiento: uniform(0.2, 0.5)s
      · Pausa tras movimiento: uniform(0.1, 0.3)s

2c. ACCIÓN OPCIONAL (30% probabilidad): scroll exploratorio
    - Dirección: hacia abajo
    - Distancia: uniform(50, 150)px
    - Velocidad: 2-3 pasos de mouseWheel con pausas de uniform(0.1, 0.3)s entre pasos
    - Pausa post-scroll: uniform(0.3, 0.8)s
```

---

### PASO 3 — Reconocimiento y apertura del desplegable

```
3a. DELAY: pausa pre-interacción
    - Rango: uniform(0.4, 1.2)s × personalidad.velocidad_factor

3b. ACCIÓN: mover ratón hacia <select id="form">
    - Obtener bounding box del elemento via CDP: DOM.getBoxModel o Runtime.evaluate
    - Punto destino: centro del bounding box ± jitter uniform(-5, 5)px
    - Trayectoria: curva ease-in-out con 15-25 puntos intermedios
    - Duración: uniform(0.3, 0.8)s
    - OVERSHOOT (10-15% probabilidad):
      · Pasar el destino en uniform(15, 40)px en la dirección del movimiento
      · Pausa de "oops": uniform(0.1, 0.3)s
      · Corrección hacia el destino real: movimiento corto uniform(0.1, 0.2)s

3c. ESPERA OBLIGATORIA: waitForElement("#form", timeout=TIMEOUT_ESPERA_ELEMENTO)
    - Verificar que el <select> sigue presente y es interactuable

3d. ACCIÓN: click para dar focus al desplegable
    - Secuencia CDP nativa:
      1. Input.dispatchMouseEvent(type="mousePressed", button="left", clickCount=1)
      2. DELAY: uniform(50, 150)ms
      3. Input.dispatchMouseEvent(type="mouseReleased", button="left", clickCount=1)
    - Post-click: el <select> debe tener focus (verificar via document.activeElement)
```

---

### PASO 4 — Recorrido humano del desplegable

```
4a. DELAY: pausa tras apertura
    - Rango: uniform(0.3, 0.8)s × personalidad.velocidad_factor
    - Simula: "acabo de abrir el desplegable, miro las opciones"

4b. ACCIÓN: scroll dentro del desplegable (1-2 veces)
    - Iteraciones: randint(1, 2)
    - Por cada iteración:
      · Método: dispatchar eventos de teclado ArrowDown (2-4 veces por iteración)
        para recorrer opciones de forma nativa
      · DELAY entre cada ArrowDown: uniform(0.15, 0.4)s (simular lectura de cada opción)
      · DELAY entre iteraciones de scroll: uniform(0.4, 1.0)s (pausa de "lectura de grupo")

4c. ACCIÓN: localizar "Madrid" recorriendo las opciones
    - Estrategia: NO usar .value = "Madrid" ni .selectedIndex directo
    - Método implementación:
      1. Via JS: obtener todas las options del <select>
         ```js
         Array.from(document.querySelector('#form').options)
              .map((o, i) => ({index: i, text: o.textContent.trim()}))
         ```
      2. Identificar el índice de "Madrid"
      3. Desde la posición actual del scroll del desplegable,
         navegar con ArrowDown/ArrowUp hasta llegar a "Madrid"
      4. Cada paso de navegación:
         · DELAY: uniform(0.1, 0.3)s (lectura de cada opción que pasa)
    - SEGURIDAD: si "Madrid" no se encuentra → lanzar excepción

4d. ACCIÓN: seleccionar "Madrid"
    - DELAY de "decisión": uniform(0.2, 0.6)s × personalidad.velocidad_factor
    - Confirmar selección: tecla Enter o click en la opción
    - Post-selección: dispatchar eventos nativos para que el formulario reaccione:
      · Event: 'change' en el <select>
      · Event: 'input' en el <select>
    - VERIFICACIÓN OBLIGATORIA:
      ```js
      document.querySelector('#form').value  // debe contener el valor de Madrid
      document.querySelector('#form').selectedOptions[0].textContent.trim() === "Madrid"
      ```
      Si la verificación falla → reintentar selección (max 2 reintentos)
```

---

### PASO 5 — Transición hacia el botón

```
5a. DELAY: pausa post-selección
    - Rango: uniform(0.5, 1.5)s × personalidad.velocidad_factor
    - Simula: "he seleccionado Madrid, miro que se haya actualizado"

5b. ACCIÓN OPCIONAL (40% probabilidad): micro-movimiento idle
    - Desplazamiento: posición actual ± uniform(-20, 20)px en X/Y
    - Duración: uniform(0.15, 0.3)s
    - Simula: mano que se mueve sin propósito

5c. DELAY OPCIONAL (20% probabilidad): pausa extra
    - Rango: uniform(0.5, 2.0)s
    - Simula: distracción momentánea, relectura
```

---

### PASO 6 — Envío (click en "Aceptar")

```
6a. ACCIÓN: mover ratón hacia <input id="btnAceptar">
    - Obtener bounding box del botón via CDP
    - Punto destino: centro ± jitter uniform(-3, 3)px
    - Trayectoria: curva ease-in-out, 15-25 puntos intermedios
    - Duración: uniform(0.3, 0.7)s
    - OVERSHOOT (10-15% probabilidad):
      · Exceso: uniform(10, 30)px
      · Pausa: uniform(0.1, 0.2)s
      · Corrección: uniform(0.1, 0.2)s

6b. ESPERA OBLIGATORIA: waitForElement("#btnAceptar", timeout=TIMEOUT_ESPERA_ELEMENTO)
    - Verificar que el botón existe, es visible y no está disabled

6c. DELAY: hesitación pre-click
    - Rango: uniform(0.3, 0.8)s × personalidad.velocidad_factor
    - Simula: "¿todo correcto? voy a darle"

6d. ACCIÓN: click nativo en el botón
    - Secuencia CDP:
      1. Input.dispatchMouseEvent(type="mousePressed", button="left", clickCount=1)
      2. DELAY: uniform(50, 150)ms  ← tiempo que el dedo tarda en soltar el botón
      3. Input.dispatchMouseEvent(type="mouseReleased", button="left", clickCount=1)
    - NO llamar a onclick="envia()" directamente. El click nativo lo disparará.
```

---

### PASO 7 — Espera de carga (transición a Página 1)

```
7a. ESPERA OBLIGATORIA: Page.loadEventFired
    - timeout=TIMEOUT_CARGA_PAGINA
    - Si timeout → lanzar excepción TimeoutCargaPagina

7b. ESPERA OBLIGATORIA: waitForElement del primer elemento clave de Página 1
    - (Selector a definir cuando se especifique Página 1)
    - timeout=TIMEOUT_ESPERA_ELEMENTO

7c. ACCIÓN: movimientos idle durante la espera
    - Mientras se espera 7a/7b, ejecutar en paralelo:
      · Cada uniform(0.8, 2.0)s: micro-movimiento de ratón ± uniform(-30, 30)px
      · Simula: "estoy mirando la pantalla esperando que cargue"
    - Se cancela cuando 7a+7b se resuelven

7d. SEGURIDAD: detectar_waf()
    - Tras la carga, verificar que no estamos en una página de bloqueo WAF
    - Si WAF detectado → WafBanError
```

---

## Configuración de tiempos (`.env`)

**IMPORTANTE:** Todos los tiempos son configurables via `.env`. Ningún valor de timing
va hardcodeado en el código. Las variables de `.env` definen los rangos base; la
personalidad del ciclo los modula multiplicativamente.

### Variables de timing para Página 0

```env
# === TIMEOUTS DE SEGURIDAD (ya existentes en v1) ===
TIMEOUT_CARGA_PAGINA_SEGUNDOS=15        # Max espera para Page.loadEventFired
TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS=10     # Max espera para waitForElement
WAIT_ELEMENT_POLL_MS=300                # Intervalo de polling en waitForElement

# === ATERRIZAJE ===
ATERRIZAJE_PAUSA_MIN=1.0               # Pausa de orientación visual (min)
ATERRIZAJE_PAUSA_MAX=3.0               # Pausa de orientación visual (max)
ATERRIZAJE_MICRO_MOV_MIN=1             # Micro-movimientos de ratón (min cantidad)
ATERRIZAJE_MICRO_MOV_MAX=2             # Micro-movimientos de ratón (max cantidad)
ATERRIZAJE_MOV_RANGO_X=80              # Rango ± px en X para micro-movimientos
ATERRIZAJE_MOV_RANGO_Y=50              # Rango ± px en Y para micro-movimientos
ATERRIZAJE_MOV_DURACION_MIN=0.2        # Duración de cada micro-movimiento (min)
ATERRIZAJE_MOV_DURACION_MAX=0.5        # Duración de cada micro-movimiento (max)
ATERRIZAJE_SCROLL_PROB=0.30            # Probabilidad de scroll exploratorio
ATERRIZAJE_SCROLL_DIST_MIN=50          # Distancia scroll exploratorio (min px)
ATERRIZAJE_SCROLL_DIST_MAX=150         # Distancia scroll exploratorio (max px)

# === INTERACCIÓN CON DESPLEGABLE ===
PRE_INTERACCION_PAUSA_MIN=0.4          # Pausa antes de moverse al elemento (min)
PRE_INTERACCION_PAUSA_MAX=1.2          # Pausa antes de moverse al elemento (max)
MOUSE_TRAYECTORIA_DURACION_MIN=0.3     # Duración movimiento ratón al objetivo (min)
MOUSE_TRAYECTORIA_DURACION_MAX=0.8     # Duración movimiento ratón al objetivo (max)
MOUSE_OVERSHOOT_PROB=0.12              # Probabilidad de overshoot (10-15%)
MOUSE_OVERSHOOT_DIST_MIN=15            # Distancia de overshoot (min px)
MOUSE_OVERSHOOT_DIST_MAX=40            # Distancia de overshoot (max px)
MOUSE_OVERSHOOT_PAUSA_MIN=0.1          # Pausa tras overshoot (min)
MOUSE_OVERSHOOT_PAUSA_MAX=0.3          # Pausa tras overshoot (max)
CLICK_PRESS_RELEASE_MIN=50             # Delay mousePressed→mouseReleased (min ms)
CLICK_PRESS_RELEASE_MAX=150            # Delay mousePressed→mouseReleased (max ms)

# === RECORRIDO DESPLEGABLE ===
DESPLEGABLE_PAUSA_APERTURA_MIN=0.3     # Pausa tras abrir desplegable (min)
DESPLEGABLE_PAUSA_APERTURA_MAX=0.8     # Pausa tras abrir desplegable (max)
DESPLEGABLE_SCROLL_ITER_MIN=1          # Iteraciones de scroll dentro del select (min)
DESPLEGABLE_SCROLL_ITER_MAX=2          # Iteraciones de scroll dentro del select (max)
DESPLEGABLE_ARROW_POR_ITER_MIN=2       # ArrowDown por iteración (min)
DESPLEGABLE_ARROW_POR_ITER_MAX=4       # ArrowDown por iteración (max)
DESPLEGABLE_ARROW_DELAY_MIN=0.15       # Delay entre cada ArrowDown (min)
DESPLEGABLE_ARROW_DELAY_MAX=0.4        # Delay entre cada ArrowDown (max)
DESPLEGABLE_ITER_PAUSA_MIN=0.4         # Pausa entre iteraciones de scroll (min)
DESPLEGABLE_ITER_PAUSA_MAX=1.0         # Pausa entre iteraciones de scroll (max)
DESPLEGABLE_NAV_DELAY_MIN=0.1          # Delay navegando hacia Madrid (min)
DESPLEGABLE_NAV_DELAY_MAX=0.3          # Delay navegando hacia Madrid (max)
DESPLEGABLE_DECISION_MIN=0.2           # Pausa de "decisión" al encontrar Madrid (min)
DESPLEGABLE_DECISION_MAX=0.6           # Pausa de "decisión" al encontrar Madrid (max)

# === TRANSICIÓN ===
TRANSICION_PAUSA_MIN=0.5               # Pausa post-selección (min)
TRANSICION_PAUSA_MAX=1.5               # Pausa post-selección (max)
TRANSICION_IDLE_PROB=0.40              # Probabilidad de micro-movimiento idle
TRANSICION_IDLE_RANGO=20               # Rango ± px del micro-movimiento idle
TRANSICION_EXTRA_PROB=0.20             # Probabilidad de pausa extra (distracción)
TRANSICION_EXTRA_MIN=0.5               # Pausa extra (min)
TRANSICION_EXTRA_MAX=2.0               # Pausa extra (max)

# === ENVÍO ===
ENVIO_HESITACION_MIN=0.3               # Hesitación pre-click en botón (min)
ENVIO_HESITACION_MAX=0.8               # Hesitación pre-click en botón (max)

# === PERSONALIDAD ===
PERSONALIDAD_FACTOR_RAPIDO=0.6         # Multiplicador de tiempos para perfil rápido
PERSONALIDAD_FACTOR_NORMAL=1.0         # Multiplicador de tiempos para perfil normal
PERSONALIDAD_FACTOR_LENTO=1.5          # Multiplicador de tiempos para perfil lento
```

**Uso en código:**
```python
# Ejemplo: pausa de aterrizaje modulada por personalidad
base_min = float(os.getenv("ATERRIZAJE_PAUSA_MIN", "1.0"))
base_max = float(os.getenv("ATERRIZAJE_PAUSA_MAX", "3.0"))
factor = personalidad.velocidad_factor  # 0.6 | 1.0 | 1.5
await random_delay(base_min * factor, base_max * factor)
```

---

## Funciones de seguridad transversales

Estas funciones se usan en TODOS los pasos y aplican a todas las páginas:

### `waitForElement(selector, timeout)`
```
- Polling: cada WAIT_ELEMENT_POLL_MS ejecutar via CDP:
    document.querySelector(selector)
- Condiciones de "encontrado":
    1. Elemento existe en DOM (no es null)
    2. Elemento es visible: offsetParent !== null || getComputedStyle(el).display !== 'none'
    3. Elemento es interactuable: !el.disabled (para inputs/buttons)
- timeout: TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS
- Si timeout agotado: raise ElementoNoEncontrado(selector, timeout)
- Retorna: coordenadas del bounding box del elemento
```

### `waitForPageLoad(timeout)`
```
- Escuchar evento CDP: Page.loadEventFired
- timeout: TIMEOUT_CARGA_PAGINA_SEGUNDOS
- Si timeout: raise TimeoutCargaPagina()
```

### `detectar_waf()`
```
- Tras cada carga de página, ejecutar:
    document.title + document.body.innerText
- Buscar patrones de bloqueo WAF (reutilizar lógica de old_comportamiento_humano.py)
- Si detectado: raise WafBanError()
```

### `random_delay(min_s, max_s)`
```
- Implementación: asyncio.sleep(random.uniform(min_s, max_s))
- NUNCA usar delays fijos
- SIEMPRE modular por personalidad.velocidad_factor cuando corresponda
- min_s y max_s provienen SIEMPRE de variables .env
```

---

## Modulación por personalidad

Cada ciclo del bot genera una `Personalidad` aleatoria. Los delays de esta página
se modulan multiplicando los rangos .env por el factor de velocidad:

| Personalidad | `velocidad_factor` (de .env) | Efecto |
|-------------|-------------------|--------|
| `rapido`    | `PERSONALIDAD_FACTOR_RAPIDO` (default 0.6) | Delays más cortos, menos acciones opcionales |
| `normal`    | `PERSONALIDAD_FACTOR_NORMAL` (default 1.0) | Rangos tal cual están en .env |
| `lento`     | `PERSONALIDAD_FACTOR_LENTO` (default 1.5)  | Delays más largos, más pausas de lectura |

**Adicionalmente:**
- `personalidad.nerviosismo` (0.0-1.0): si > 0.7, aumentar probabilidad de micro-correcciones
- `personalidad.atencion` (0.5-1.0): modula duración de pausas de "lectura"

---

## Diagrama de tiempos (estimación por personalidad, con defaults de .env)

| Paso | Rápido (×0.6) | Normal (×1.0) | Lento (×1.5) |
|------|--------|--------|-------|
| 2. Aterrizaje | 0.6 - 1.8s | 1.0 - 3.0s | 1.5 - 4.5s |
| 3. Reconocimiento desplegable | 0.5 - 1.2s | 0.7 - 2.0s | 1.0 - 3.0s |
| 4. Recorrido desplegable | 1.5 - 3.0s | 2.5 - 5.0s | 3.5 - 7.0s |
| 5. Transición | 0.3 - 0.9s | 0.5 - 1.5s | 0.8 - 2.3s |
| 6. Envío | 0.5 - 1.0s | 0.6 - 1.5s | 0.9 - 2.0s |
| 7. Espera carga | (depende del servidor) | — | — |
| **TOTAL (sin carga)** | **~3.4 - 7.9s** | **~5.3 - 13.0s** | **~7.7 - 18.8s** |

*Todos estos tiempos cambian si modificas los valores en `.env`.*

---

## Errores y recuperación

| Error | Causa | Acción |
|-------|-------|--------|
| `ElementoNoEncontrado("#form")` | Página no cargó bien | Reintentar navegación (max 2) |
| `ElementoNoEncontrado("#btnAceptar")` | Botón no presente | Reintentar navegación (max 2) |
| `TimeoutCargaPagina` | Servidor lento/caído | Esperar y reintentar ciclo completo |
| `WafBanError` | WAF nos bloqueó | Activar BackoffController (espera exponencial) |
| Verificación Madrid falla | Select no tomó el valor | Reintentar selección (max 2 dentro de la fase) |

---

## Notas de implementación

1. **Todos los eventos de ratón y teclado** deben ser CDP nativos (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`), NO JavaScript `dispatchEvent()`.
2. **El `<select>` se manipula con navegación por teclado** (ArrowDown/ArrowUp/Enter) después del focus, NO con `.value = "..."`.
3. **La verificación post-selección es obligatoria** — nunca asumir que la selección fue exitosa.
4. **Las esperas por elementos son obligatorias antes de cada interacción** — nunca interactuar con un elemento sin verificar su presencia.
5. **Los delays opcionales usan probabilidad**, no condiciones deterministas — cada ejecución es diferente.
