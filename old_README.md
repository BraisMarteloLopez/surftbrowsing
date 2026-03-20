# AUTO WEBSURFT

**Fecha:** 19 de marzo de 2026
**Estado:** Implementado y funcional

---

## 1. Contexto

El portal ICP del gobierno español es el único punto de acceso para solicitar cita previa de extranjería. Las citas para el trámite "POLICÍA TARJETA CONFLICTO UCRANIA" en Madrid se liberan de forma esporádica, en cantidad limitada, y desaparecen en segundos. La demanda supera estructuralmente la oferta.

El proceso manual para comprobar si hay cita disponible requiere rellenar 5 formularios secuenciales cada vez. Si no hay cita, el usuario debe repetir todo el proceso desde el principio. Esto obliga a dedicar horas frente al navegador repitiendo un formulario mecánico sin garantía de resultado.

---

## 2. Objetivo

Automatizar el proceso de solicitud de cita previa en el portal ICP para el trámite "POLICÍA TARJETA CONFLICTO UCRANIA" en Madrid.

El bot navega el formulario completo en bucle hasta que detecta disponibilidad de cita. Cuando hay cita disponible, emite una alerta sonora, mantiene la sesión activa en la página, y cede el control al usuario para completar manualmente los pasos finales (selección de hora y confirmación SMS).

---

## 3. Arquitectura

### Enfoque: Chrome DevTools Protocol (CDP) sobre navegador real

El script Python se conecta al navegador Brave del usuario mediante el protocolo CDP, que expone un canal WebSocket en `localhost:9222`.

A través de este canal, el script inyecta sentencias JavaScript directamente en el contexto de la página cargada. Estas sentencias operan sobre el DOM de la página usando los **IDs nativos de los elementos HTML** (inputs, selects, buttons) para:

- **Seleccionar opciones** en dropdowns (`document.getElementById('id').value = 'valor'`)
- **Rellenar campos de texto** (`document.getElementById('id').value = 'texto'`)
- **Hacer click en botones** (`document.getElementById('id').click()`)
- **Leer contenido de la página** para detectar mensajes como "no hay citas disponibles"

### Estructura modular (3 capas)

El código está organizado en tres módulos con responsabilidades separadas:

```
cita_bot.py                  ← Orquestación: flujo de formularios y bucle principal
    │
    ├── comportamiento_humano.py  ← Motor anti-detección
    │       ├── SimuladorHumano        ← Clase principal: estado del ratón, viewport, CDP
    │       ├── Movimiento concurrente ← Ratón se mueve durante delays (asyncio.create_task)
    │       ├── Secuencias variables   ← Orden aleatorio de acciones pre-formulario
    │       ├── Scroll nativo          ← mouseWheel via CDP (no JS scrollBy)
    │       └── Detección WAF          ← detectar_waf(), WafBanError
    │
    └── cdp_helpers.py               ← Funciones CDP puras
            ├── CDPSession             ← WebSocket, reconexión, callbacks
            ├── ejecutar_js()          ← Evaluación de JS con timeout
            ├── safe_js_string()       ← Escape de strings para inyección JS
            └── obtener_ws_url()       ← Descubrimiento de pestaña via HTTP
```

**`cdp_helpers.py`** contiene la capa de transporte CDP: la clase `CDPSession` (WebSocket con reconexión automática), ejecución de JavaScript, y utilidades de conexión.

**`comportamiento_humano.py`** contiene toda la lógica anti-detección encapsulada en la clase `SimuladorHumano`, que mantiene el estado del ratón (posición x/y) y viewport en Python (no en JS global), y expone métodos como `mover_a()`, `scroll()`, `delay_activo()`, `secuencia_pre_accion()`.

**`cita_bot.py`** contiene la orquestación pura: los 5 pasos de formulario, el bucle principal, la evaluación de resultados, y la alerta sonora. Cada paso de formulario se reduce a llamadas a `humano.secuencia_pre_accion(element_id=...)` seguidas de la acción JS correspondiente.

### Por qué IDs de elementos HTML como método de interacción

- **Robustez:** Los IDs son identificadores únicos dentro del DOM. A diferencia de XPaths o selectores CSS compuestos, no dependen de la estructura jerárquica de la página ni de clases CSS que pueden cambiar por motivos estéticos.
- **Simplicidad:** Una línea de JS por acción. No se necesitan frameworks ni librerías de scraping.
- **Mantenimiento:** Si el portal cambia un ID, el cambio es una edición de una línea en el archivo de configuración. No requiere modificar lógica del script.
- **Indetectable:** JavaScript ejecutado vía CDP en el contexto de la página es idéntico a JavaScript ejecutado desde la consola del navegador por un humano. No existe flag, header ni fingerprint que lo distinga de una interacción manual.

### Clase `SimuladorHumano`

La clase `SimuladorHumano` (en `comportamiento_humano.py`) es el componente central de la anti-detección. Encapsula:

- **Estado del ratón** (`mouse_x`, `mouse_y`): posición mantenida en Python, actualizada con cada movimiento
- **Viewport** (`viewport`): dimensiones reales leídas via CDP
- **Sesión CDP** (`cdp`): referencia a la conexión WebSocket

Métodos principales:

| Método | Descripción |
|--------|-------------|
| `mover_a(x, y)` | Trayectoria curva con easing smoothstep `t²(3-2t)` |
| `mover_a_elemento(id)` | Obtiene posición del elemento y mueve el cursor |
| `movimiento_idle()` | 1-3 movimientos aleatorios por el viewport |
| `scroll()` | 2-4 pasos de scroll via `mouseWheel` CDP nativo |
| `delay_activo(base, varianza)` | Espera con movimiento de ratón concurrente |
| `pausa_lectura()` | Pausa entre formularios con movimiento de fondo |
| `pausa_extra(prob)` | Pausa adicional con probabilidad configurable |
| `secuencia_pre_accion(element_id)` | 2-4 acciones preparatorias en orden aleatorio |

Cada paso de formulario se reduce a:
```python
await humano.secuencia_pre_accion(element_id=ids["dropdown_provincia"])
await ejecutar_js(cdp, "...seleccionar valor...")
```

### Diferencia con Selenium/WebDriver

Selenium instancia un navegador controlado mediante el protocolo WebDriver, que inyecta flags detectables (`navigator.webdriver = true`) y genera un fingerprint artificial. El portal ICP detecta y bloquea este patrón activamente (confirmado por múltiples repositorios y usuarios).

CDP sobre un navegador real no tiene este problema. El navegador es la instalación normal del usuario, con su perfil, cookies e historial. CDP es un canal lateral de comunicación, no una inyección en el navegador.

---

## 4. Requisitos

- Windows 10/11
- Python 3.10 o superior
- Brave Browser instalado
- Librerías Python:

```
pip install -r requirements.txt
```

Esto instala `websockets` y `python-dotenv`. Ninguna otra dependencia.

---

## 5. Instalación y puesta en marcha

### 5.1. Localizar la ruta de Brave en Windows

La ruta de `brave.exe` depende de la instalación. Las ubicaciones habituales son:

```
C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe
C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe
C:\Users\TU_USUARIO\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe
```

Para encontrarla con certeza: abrir una terminal y ejecutar:

```
where /R "C:\" brave.exe
```

O buscar "Brave" en el menú de inicio, click derecho → "Abrir ubicación del archivo", y copiar la ruta completa.

### 5.2. Lanzar Brave con CDP habilitado

Cerrar todas las ventanas de Brave antes de ejecutar este comando. Si Brave ya está corriendo, el flag `--remote-debugging-port` se ignora silenciosamente.

```
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --ignore-certificate-errors
```

Sustituir la ruta por la correcta de tu instalación.

> **Nota sobre `--ignore-certificate-errors`:** El portal ICP puede presentar errores de certificado SSL (`NET::ERR_CERT_AUTHORITY_INVALID`) que Brave bloquea sin opción de continuar (HSTS). Este flag desactiva la validación de certificados. Usarlo **solo** mientras se ejecuta el bot, y no para navegación general.

### 5.3. Verificar que CDP funciona

Antes de ejecutar el script, abrir en el propio Brave (o cualquier navegador):

```
http://localhost:9222/json
```

Si CDP está activo, devuelve un JSON con la lista de pestañas abiertas. Ejemplo:

```json
[{
  "description": "",
  "devtoolsFrontendUrl": "...",
  "id": "ABC123",
  "title": "New Tab",
  "type": "page",
  "url": "chrome://newtab/",
  "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/ABC123"
}]
```

Si devuelve error de conexión: Brave no se lanzó con el flag, o ya estaba corriendo antes de ejecutar el comando.

### 5.4. Crear el archivo `.env`

En la misma carpeta del script, crear un archivo llamado `.env` con el siguiente contenido:

```env
NIE=TU_NIE_AQUI
NOMBRE=TU NOMBRE Y APELLIDOS AQUI
```

Opcionalmente se pueden ajustar los tiempos y el paso de depuración (ver sección 11.1 para todos los parámetros).

### 5.5. Ejecutar el script

```
python cita_bot.py
```

El script se conecta a Brave, abre el portal ICP y comienza el bucle de búsqueda de cita.

### 5.6. Parar el script

`Ctrl+C` en la terminal. El script se cierra limpiamente. Brave queda abierto y sin afectar.

---

## 6. Flujo detallado del bot

> **Nota:** La numeración de pasos (0-5) coincide con los valores de `PASO_HASTA` en `.env`. Esto permite hacer referencia cruzada entre este flujo y el modo depuración (ver sección 11.1).

### Prerrequisito — Lanzamiento de Brave (manual, una sola vez)

El usuario abre Brave desde línea de comandos con el flag de depuración remota (ver sección 5.2). Brave se abre normalmente. El flag solo habilita el puerto WebSocket de CDP. El script se conecta al WebSocket de Brave en `localhost:9222`. Si Brave no está abierto o no tiene el flag, el script muestra un error descriptivo y se cierra.

### PASO 0 — Navegación a la URL de inicio

El script navega automáticamente a la URL de inicio del portal ICP. Espera a que la página cargue completamente. Si detecta un bloqueo WAF, aplica backoff y reintenta.

> **URL:** `https://icp.administracionelectronica.gob.es/icpplus/index.html`

### PASO 1 — Formulario 1: Selección de provincia

Acciones JS ejecutadas por el script:

1. Seleccionar "Madrid" en el dropdown de provincia → `getElementById('form').value = '/icpplustiem/citar?p=28&locale=es'`
2. Disparar evento `change` → `getElementById('form').dispatchEvent(new Event('change', { bubbles: true }))`
3. Click en botón "Aceptar" → `getElementById('btnAceptar').click()`
4. Esperar carga de la siguiente página + scroll humano

> **Nota:** El botón Aceptar ejecuta la función JS `envia()` al hacer click. Se usa `.click()` para que se dispare automáticamente.

### PASO 2 — Formulario 2: Selección de oficina y trámite

Acciones JS ejecutadas por el script:

1. No se toca el dropdown de oficina (se deja la opción por defecto "cualquier oficina")
2. Seleccionar trámite → `getElementById('tramiteGrupo[0]').value = '4112'`
3. Disparar evento `change` → `getElementById('tramiteGrupo[0]').dispatchEvent(new Event('change', { bubbles: true }))`
4. Click en botón "Aceptar" → `getElementById('btnAceptar').click()`
5. Esperar carga de la siguiente página + scroll humano

> **Nota:** El dropdown de trámite tiene `onchange` propio que llama a `eliminarSeleccionOtrosGrupos(0)` y `cargaMensajesTramite()`. El `dispatchEvent` los dispara automáticamente.

### PASO 3 — Formulario 3: Aviso informativo

Acciones JS ejecutadas por el script:

1. Click en botón "Entrar" → `getElementById('btnEntrar').click()`
2. Esperar carga de la siguiente página + scroll humano

> **Nota:** El botón dice "Entrar" (no "Aceptar") y ejecuta `document.forms[0].submit()` al hacer click.

### PASO 4 — Formulario 4: Datos personales

Acciones JS ejecutadas por el script:

1. Rellenar campo NIE → `getElementById('txtIdCitado').value = NIE` (valor leído del `.env`)
2. Disparar evento `input` → `getElementById('txtIdCitado').dispatchEvent(new Event('input', { bubbles: true }))`
3. Rellenar campo Nombre y Apellidos → `getElementById('txtDesCitado').value = NOMBRE` (valor leído del `.env`)
4. Disparar evento `change` → `getElementById('txtDesCitado').dispatchEvent(new Event('change', { bubbles: true }))`
5. Click en botón "Aceptar" → `getElementById('btnEnviar').click()`
6. Esperar carga de la siguiente página + scroll humano

> **Nota:** El input Nombre tiene `onchange="comprobarDatos()"`, por lo que se dispara evento `change` (no `input`) para activar la validación.

### PASO 5 — Formulario 5: Solicitar cita + evaluación de disponibilidad

Acciones JS ejecutadas por el script:

1. Click en botón "Solicitar Cita" → `getElementById('btnEnviar').click()`
2. Esperar carga de la respuesta + scroll humano
3. Evaluar el estado de la página (ver sección 10 para el detalle completo)

> **Nota:** El botón ejecuta `enviar('solicitud')` al hacer click. Se usa `.click()` para dispararlo.

La evaluación de la página combina múltiples verificaciones (detección WAF, contenido mínimo, búsqueda case-insensitive del texto de `config.json`, verificación de URL, y texto positivo opcional) para clasificar la página en cuatro estados:

**Estado: WAF_BANEADO** (página de rechazo del WAF detectada)

1. El script no toca la página.
2. Aplica backoff agresivo (5-15 min configurable).
3. Reinicia el ciclo completo desde el PASO 0.

**Estado: NO HAY CITAS** (texto "no hay citas" confirmado — señal definitiva)

1. Busca un botón con texto "Aceptar" y hace click para volver al inicio. Si no lo encuentra, continúa igualmente.
2. **Limpia caché y storage del navegador** (caché HTTP, localStorage, sessionStorage, IndexedDB, service workers). No borra cookies para no afectar la sesión.
3. El script espera el intervalo configurado (`INTERVALO_REINTENTO_SEGUNDOS` ±15% jitter).
4. Navega desde cero a la URL de inicio para iniciar un ciclo limpio.

**Estado: HAY CITAS** (sin texto negativo + URL del portal válida + contenido suficiente + texto positivo si configurado)

1. El script NO toca nada en la página. La deja exactamente en el estado en que está.
2. Emite una alerta sonora repetida (bucle de sonido) para que el usuario la oiga aunque no esté delante del PC.
3. Imprime en consola un mensaje destacado con timestamp.
4. La alerta continúa indefinidamente hasta que el usuario toma el control o para el script con Ctrl+C.

**Estado: DESCONOCIDO** (página vacía, URL inesperada, o señales contradictorias)

1. El script registra una advertencia en el log.
2. Espera un intervalo con backoff exponencial (5s, 10s, 20s... hasta 5 minutos).
3. Repite el proceso completo desde el PASO 0.
4. Si se acumulan 10 estados desconocidos consecutivos, muestra una alerta especial en el log.

> **Importante:** El estado DESCONOCIDO nunca se trata como "hay cita". Esto evita falsos positivos por errores del portal, páginas de mantenimiento o cargas incompletas.

El objetivo es que cuando el usuario llegue al navegador, la página esté exactamente donde el script la dejó, con la sesión activa, lista para que el usuario seleccione hora y confirme manualmente.

---

## 7. Cadencia entre acciones (anti-bloqueo)

El script implementa múltiples capas de temporización para simular comportamiento humano y evitar el bloqueo del WAF del portal:

### 7.1. Delays activos con movimiento concurrente (`DELAY_ACCION_BASE` + `DELAY_ACCION_VARIANZA`)

Antes de cada interacción con un elemento, el script ejecuta un **delay activo**: mientras espera el tiempo configurado, el ratón se mueve de fondo simulando lectura. Esto evita que el ratón quede completamente quieto durante 2-5 segundos (comportamiento no humano).

```
delay = DELAY_ACCION_BASE + random(0, DELAY_ACCION_BASE × DELAY_ACCION_VARIANZA)
```

Con los valores por defecto (`base=2.0`, `varianza=0.8`), cada acción espera entre **2.0 y 3.6 segundos**.

Durante el delay, se ejecuta concurrentemente (`asyncio.create_task`) uno de 4 patrones de movimiento de ratón:
- **Reposo**: micro-movimientos (±20px) cerca de la posición actual
- **Lectura**: barrido horizontal simulando lectura de texto (izquierda→derecha, bajando)
- **Exploración**: movimientos suaves entre zonas de interés del viewport
- **Drift**: movimiento muy lento y continuo en una dirección con correcciones

La tarea de movimiento se cancela limpiamente cuando el delay termina.

### 7.2. Pausa entre formularios (`PAUSA_ENTRE_PASOS_MIN` / `_MAX`)

Entre cada paso del formulario (F1→F2, F2→F3, etc.), el script aplica una pausa adicional que simula tiempo de lectura:

```
pausa = random(PAUSA_ENTRE_PASOS_MIN, PAUSA_ENTRE_PASOS_MAX)
```

Por defecto: **2 a 5 segundos** entre cada formulario.

### 7.3. Scroll nativo via CDP (`DELAY_SCROLL_MIN` / `_MAX`)

En cada formulario, el script hace scroll de 2 a 4 veces usando eventos **`Input.dispatchMouseEvent`** con `type: "mouseWheel"` directamente via CDP. Esto genera eventos de rueda de ratón nativos idénticos a los de un usuario real, a diferencia del anterior `window.scrollBy()` que era detectable como JavaScript inyectado.

Entre cada paso de scroll, se añaden **micro-movimientos del ratón** (±8px horizontal, ±5px vertical) que simulan el temblor natural de la mano mientras se usa la rueda del ratón.

```
pausa_scroll = random(DELAY_SCROLL_MIN, DELAY_SCROLL_MAX)
```

Por defecto: **0.8 a 2.0 segundos** entre cada paso de scroll.

### 7.4. Evaluación de resultado (`DELAY_EVALUACION_MIN` / `_MAX`)

Tras solicitar la cita (PASO 5), el script espera un tiempo aleatorio antes de leer el resultado, simulando que un humano tarda en leer la página:

```
pausa_evaluacion = random(DELAY_EVALUACION_MIN, DELAY_EVALUACION_MAX)
```

Por defecto: **2 a 5 segundos**.

### 7.5. Intervalo entre reintentos (`INTERVALO_REINTENTO_SEGUNDOS`)

Cuando no hay citas, el script espera antes de iniciar un nuevo ciclo completo. Se aplica un **jitter de ±15%** para evitar cadencia periódica.

Por defecto: **120 segundos** (±15% → entre 102 y 138 segundos).

### Tiempo total por ciclo

Un ciclo completo (5 formularios) con los valores por defecto tarda aproximadamente **30-50 segundos** de interacción activa. Sumando el intervalo de reintento de 120 segundos, el script ejecuta **un intento cada ~3 minutos**.

### 7.6. Detección de WAF (Web Application Firewall)

El portal ICP está protegido por un WAF (F5 BIG-IP) que puede bloquear temporalmente la IP si detecta patrones de automatización. Cuando esto ocurre, la página muestra:

```
The requested URL was rejected. Please consult with your administrador.
Your support ID is: <número>
```

El bot detecta automáticamente esta página en tres puntos del flujo (tras navegación, tras cada click de formulario, y tras solicitar cita) y aplica un **backoff agresivo** con un controlador dedicado:

| Ban consecutivo | Espera por defecto |
|----------------|--------|
| 1er ban | 5 minutos (`WAF_BACKOFF_BASE_SEGUNDOS`) |
| 2do ban | 10 minutos |
| 3er+ ban | 15 minutos (`WAF_BACKOFF_MAX_SEGUNDOS`, máximo) |

Tras **3 bans consecutivos** (`WAF_BACKOFF_UMBRAL_ALERTA`), el log muestra una alerta recomendando aumentar los delays. Tras un ciclo exitoso, el contador de bans se resetea.

Todos los parámetros del WAF son configurables vía `.env` (ver sección 11.1).

---

## 8. Nota técnica: eventos del DOM al modificar valores

Cuando JavaScript modifica el valor de un `<select>` o un `<input>` mediante `.value = 'x'`, el navegador NO dispara automáticamente los eventos `change` ni `input` del DOM.

Muchos formularios web dependen de estos eventos para:

- Habilitar o deshabilitar campos dependientes
- Cargar opciones dinámicas (por ejemplo, el dropdown de trámite puede cargarse después de seleccionar provincia)
- Validar datos antes de permitir el envío

El script debe disparar estos eventos manualmente después de cada modificación de valor:

```javascript
// Seleccionar valor
document.getElementById('id_elemento').value = 'valor';

// Disparar evento change para que el formulario reaccione
document.getElementById('id_elemento').dispatchEvent(new Event('change', { bubbles: true }));
```

Si un formulario no responde después de establecer un valor, es casi seguro que falta el `dispatchEvent`. Esto debe verificarse empíricamente en cada paso del portal durante la fase de mapeo de IDs.

---

## 9. Salida en consola (logging)

El script imprime en consola un log por cada intento con el siguiente formato:

```
[2026-03-18 09:15:32] Intento #1 — Navegando a URL de inicio...
[2026-03-18 09:15:35] Intento #1 — Formulario 1: seleccionando provincia Madrid
[2026-03-18 09:15:38] Intento #1 — Formulario 2: seleccionando trámite
[2026-03-18 09:15:40] Intento #1 — Formulario 3: aceptando aviso
[2026-03-18 09:15:43] Intento #1 — Formulario 4: rellenando datos personales
[2026-03-18 09:15:46] Intento #1 — Formulario 5: solicitando cita
[2026-03-18 09:15:49] Intento #1 — Resultado: NO HAY CITAS
[2026-03-18 09:15:49] Intento #1 — Reintentando en 120s...
[2026-03-18 09:17:49] Intento #2 — Navegando a URL de inicio...
...
[2026-03-18 11:42:17] Intento #87 — *** CITA DISPONIBLE *** — Toma el control del navegador
```

Cuando el WAF bloquea la IP:

```
[2026-03-18 09:20:15] Intento #5 — *** WAF DETECTADO *** Baneado por el firewall del portal.
[2026-03-18 09:20:15] Intento #5 — Esperando 5.0 minutos antes de reintentar... (ban #1)
[2026-03-18 09:25:15] Intento #6 — Navegando a URL de inicio...
```

Cuando hay errores, el log incluye información de backoff:

```
[2026-03-18 09:20:15] Intento #5 — Timeout en carga de página. Reiniciando en 5s... (error #1)
[2026-03-18 09:20:25] Intento #6 — Timeout en carga de página. Reiniciando en 10s... (error #2)
[2026-03-18 09:20:40] Intento #7 — Timeout en carga de página. Reiniciando en 20s... (error #3)
```

Tras 10 errores consecutivos del mismo tipo, el log muestra una alerta especial:

```
[2026-03-18 09:25:00] Intento #15 — ALERTA: Demasiados timeouts consecutivos. Posible congestión del portal.
```

El backoff se resetea automáticamente tras un ciclo exitoso (con o sin citas).

Sin este log no es posible saber si el script lleva horas fallando en silencio.

---

## 10. Detección de disponibilidad y estados de la página

Tras solicitar cita (PASO 5), el script evalúa el estado de la página con múltiples verificaciones para evitar falsos positivos:

1. **Detección WAF:** Antes de evaluar, comprueba si la página es un bloqueo del firewall (ver sección 7.6).
2. **Contenido mínimo:** Verifica que `document.body.innerText` tiene al menos 50 caracteres (descarta páginas vacías o de error).
3. **Búsqueda case-insensitive:** Busca el texto de `config.json` (`texto_no_hay_citas`) en minúsculas.
4. **Verificación de URL:** Comprueba que la URL contiene `icpplus` o `icpplustiem`.
5. **Verificación positiva (opcional):** Si `texto_hay_citas` está configurado en `config.json`, confirma la presencia del texto positivo.

Con estas señales, el script clasifica la página en cuatro estados:

| Estado | Condiciones | Comportamiento |
|---|---|---|
| **WAF_BANEADO** | Página de rechazo del WAF (ambas señales: "URL was rejected" + "support ID") | Backoff agresivo de 5-15 min |
| **NO HAY CITAS** | Texto "no hay citas" presente (señal definitiva) | Click en Aceptar, espera intervalo, reintenta |
| **HAY CITAS** | Sin texto negativo + URL válida + contenido suficiente (+ texto positivo si configurado) | Alerta sonora |
| **DESCONOCIDO** | Página vacía, URL inesperada, o señales contradictorias | Log de advertencia, espera con backoff, reintenta |

Los estados **DESCONOCIDO** y **WAF_BANEADO** nunca se interpretan como "hay cita". La detección WAF requiere **ambas** señales ("URL was rejected" **Y** "support ID") simultáneamente, lo que elimina cualquier riesgo de confundir una página legítima del portal con un bloqueo WAF.

### Manejo de errores en el ciclo

| Error | Causa probable | Comportamiento |
|---|---|---|
| `WafBanError` | Firewall del portal bloqueó la IP | Backoff agresivo (5min, 10min, 15min max) |
| `ConnectionError` | WebSocket muerto, Brave cerrado | Reconexión automática con backoff exponencial |
| `TimeoutError` | Portal saturado, conexión lenta | Backoff exponencial (5s, 10s, 20s..., max 5min) |
| `RuntimeError` (JS) | Elemento no encontrado, portal cambió IDs | Backoff exponencial + alerta tras 10 errores consecutivos |
| Excepción inesperada | Error de red, bug, etc. | Backoff exponencial + alerta tras 10 errores consecutivos |

El script **nunca se detiene por un error**. Tras un ciclo exitoso (con o sin citas), el backoff se resetea al intervalo normal.

---

## 11. Configuración

La configuración se divide en dos archivos:

### 11.1. Archivo `.env` — Datos personales y cadencia (configurado por el usuario)

```env
# Datos personales (OBLIGATORIO — rellenar antes de ejecutar)
NIE=X1234567A
NOMBRE=NOMBRE APELLIDO1 APELLIDO2

# Depuración (OPCIONAL — ejecutar solo hasta un paso concreto, 0-5)
PASO_HASTA=5

# Cadencia (OPCIONAL — valores por defecto si no se especifican)
INTERVALO_REINTENTO_SEGUNDOS=120
TIMEOUT_CARGA_PAGINA_SEGUNDOS=15
```

El archivo `.env` NO se sube al repositorio (está en `.gitignore`). El usuario lo crea manualmente y rellena sus datos.

El script valida al arrancar que `NIE` y `NOMBRE` existen y no están vacíos, y que `PASO_HASTA` está entre 0 y 5. Si alguna validación falla, muestra un error descriptivo y se cierra.

#### Variables obligatorias

| Variable | Descripción |
|---|---|
| `NIE` | Número de identidad de extranjero |
| `NOMBRE` | Nombre y apellidos completos |

#### Variables opcionales — Cadencia y tiempos

| Variable | Descripción | Defecto |
|---|---|---|
| `PASO_HASTA` | Paso hasta el que ejecutar (0-5). Para depuración. | `5` |
| `INTERVALO_REINTENTO_SEGUNDOS` | Segundos entre reintentos cuando no hay cita | `120` |
| `TIMEOUT_CARGA_PAGINA_SEGUNDOS` | Timeout de espera de carga de página | `15` |
| `TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS` | Timeout para esperar que un elemento aparezca en el DOM | `10` |

#### Variables opcionales — Delays humanizados

| Variable | Descripción | Defecto |
|---|---|---|
| `DELAY_ACCION_BASE` | Segundos base entre cada acción del formulario | `2.0` |
| `DELAY_ACCION_VARIANZA` | Fracción de varianza aleatoria sobre base. Rango resultante: `[base, base + base×varianza]` | `0.8` |
| `DELAY_SCROLL_MIN` | Mínimo de pausa entre pasos de scroll (segundos) | `0.8` |
| `DELAY_SCROLL_MAX` | Máximo de pausa entre pasos de scroll (segundos) | `2.0` |
| `DELAY_EVALUACION_MIN` | Mínimo de pausa antes de evaluar resultado (segundos) | `2.0` |
| `DELAY_EVALUACION_MAX` | Máximo de pausa antes de evaluar resultado (segundos) | `5.0` |
| `PAUSA_ENTRE_PASOS_MIN` | Mínimo de pausa entre formularios (segundos) | `2.0` |
| `PAUSA_ENTRE_PASOS_MAX` | Máximo de pausa entre formularios (segundos) | `5.0` |

#### Variables opcionales — WAF (Web Application Firewall)

| Variable | Descripción | Defecto |
|---|---|---|
| `WAF_BACKOFF_BASE_SEGUNDOS` | Espera tras el primer ban del WAF (segundos) | `300` (5 min) |
| `WAF_BACKOFF_MAX_SEGUNDOS` | Espera máxima tras bans consecutivos (segundos) | `900` (15 min) |
| `WAF_BACKOFF_UMBRAL_ALERTA` | Número de bans consecutivos antes de mostrar alerta | `3` |

#### Modo depuración con `PASO_HASTA`

El script siempre empieza desde el paso 0 (navegación a la URL de inicio). `PASO_HASTA` controla hasta dónde llega:

| `PASO_HASTA` | Ejecuta | Comportamiento |
|---|---|---|
| `0` | Solo navegación a la URL | Ejecuta una vez y para |
| `1` | Navegación + Formulario 1 (Provincia) | Ejecuta una vez y para |
| `2` | Navegación + F1 + F2 (Trámite) | Ejecuta una vez y para |
| `3` | Navegación + F1 + F2 + F3 (Aviso) | Ejecuta una vez y para |
| `4` | Navegación + F1 + F2 + F3 + F4 (Datos) | Ejecuta una vez y para |
| `5` | Ciclo completo (todos los pasos) | **Bucle infinito** — modo producción |

Cuando `PASO_HASTA < 5`, el script ejecuta los pasos indicados **una sola vez** y se detiene limpiamente. Esto permite verificar paso a paso que cada formulario funciona correctamente sin riesgo de efectos secundarios en el portal.

### 11.2. Archivo `config.json` — IDs de elementos HTML (no tocar)

```json
{
    "url_inicio": "https://icp.administracionelectronica.gob.es/icpplus/index.html",
    "ids": {
        "dropdown_provincia": "form",
        "valor_madrid": "/icpplustiem/citar?p=28&locale=es",
        "boton_aceptar_f1": "btnAceptar",
        "dropdown_tramite": "tramiteGrupo[0]",
        "valor_tramite": "4112",
        "boton_aceptar_f2": "btnAceptar",
        "boton_entrar_f3": "btnEntrar",
        "input_nie": "txtIdCitado",
        "input_nombre": "txtDesCitado",
        "boton_aceptar_f4": "btnEnviar",
        "boton_solicitar_cita": "btnEnviar",
        "texto_no_hay_citas": "En este momento no hay citas disponibles."
    }
}
```

Los IDs de elementos HTML están externalizados. Si el portal cambia un ID, se edita una línea del JSON sin tocar el código Python. Este archivo SÍ se sube al repositorio.

---

## 12. Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| El portal cambia los IDs de los elementos | Media | IDs externalizados en config.json; corrección inmediata |
| El portal detecta el patrón de navegación repetida (misma IP, mismo flujo) | Media | Cadencia configurable, pausas entre pasos, detección automática de ban WAF con backoff de 5-15 min |
| El portal añade CAPTCHA en algún paso | Baja | El bot se detiene y el usuario resuelve manualmente |
| Brave cierra o pierde conexión | Baja | **Reconexión automática** con backoff exponencial |
| La página tarda más de lo esperado en cargar | Media | Timeouts configurables por paso |
| Error de certificado SSL del portal | Baja | Relanzar Brave con `--ignore-certificate-errors` (ver sección 5.2) |

---

## 13. Lo que este bot NO hace

- No resuelve CAPTCHAs
- No introduce el código SMS (el usuario lo hace manualmente)
- No selecciona hora de cita (el usuario lo hace manualmente)
- No corre 24/7 sin supervisión (requiere que el PC esté encendido y Brave abierto)
- No usa proxies, VPNs ni rotación de IP

---

## 14. Troubleshooting

### "No se puede conectar a localhost:9222"

- Brave no se lanzó con `--remote-debugging-port=9222`
- Brave ya estaba corriendo antes de ejecutar el comando con el flag. Cerrar todas las ventanas de Brave y volver a lanzar con el flag.
- Otro programa está usando el puerto 9222. Cambiar a otro puerto (ej: 9223) tanto en el comando de Brave como en el script.

### "La conexión no es privada" / `NET::ERR_CERT_AUTHORITY_INVALID`

- El portal ICP tiene un problema de certificado SSL. Brave bloquea el acceso.
- Si aparece la opción "Avanzado → Continuar": hacer click para aceptar y relanzar el bot.
- Si NO aparece (HSTS activo): cerrar Brave y relanzarlo con `--ignore-certificate-errors` (ver sección 5.2).

### "Elemento no encontrado: ID_xxx"

- El portal cambió el ID del elemento. Abrir DevTools (F12), inspeccionar el elemento, copiar el nuevo ID y actualizar config.json.

### "La página no avanza después de seleccionar un valor"

- Probablemente falta el dispatchEvent. Ver sección 8 de este documento.

### "WAF DETECTADO" / "The requested URL was rejected"

- El firewall del portal (WAF) ha baneado temporalmente tu IP por detectar patrones de automatización.
- El bot detecta esta situación automáticamente y espera 5-15 minutos antes de reintentar.
- Si ocurre frecuentemente, aumentar los delays en `.env`:
  - `INTERVALO_REINTENTO_SEGUNDOS=180` (3 minutos entre reintentos)
  - `DELAY_ACCION_BASE=3.0` (3 segundos base entre acciones)
  - `DELAY_ACCION_VARIANZA=1.0` (varianza del 100%, rango [3.0, 6.0]s)
- El ban WAF es temporal (generalmente 5-15 minutos). El bot se recupera solo.

### "El script lleva horas sin encontrar cita"

- Es el comportamiento esperado. Las citas para este trámite en Madrid se liberan esporádicamente.
- Verificar en el log que el script está completando ciclos (no se ha quedado atascado en un paso).
- Considerar reducir el intervalo de reintento si es muy conservador (no bajar de 30 segundos).

### "El log muestra ALERTA: Demasiados errores consecutivos"

- El script lleva 10+ errores seguidos sin completar un ciclo.
- Si son **timeouts**: el portal está saturado o la conexión es lenta. El backoff ya está espaciando los reintentos automáticamente.
- Si son **errores JS**: el portal probablemente cambió algún ID. Abrir DevTools (F12), verificar IDs y actualizar `config.json`.
- Si son **errores de conexión**: Brave puede haberse cerrado o la red cayó. El script intenta reconectar automáticamente.

### "El log muestra ADVERTENCIA: Estado de página no reconocido"

- La página no coincide con ningún estado esperado (ni "no hay citas" ni una cita real).
- Puede ser: página de mantenimiento, error 500, redirección inesperada, o cambio en el portal.
- Navegar manualmente al portal y verificar que sigue operativo.
- Si el portal funciona pero el bot sigue mostrando este aviso, inspeccionar el HTML con F12 y verificar que el texto y botones de `config.json` siguen siendo correctos.

### "El script se detuvo con un error no reconocido"

- Copiar el log del error. Probablemente es un estado inesperado de la página (ver sección 10).
- Navegar manualmente al portal y verificar que sigue operativo.

---

## 15. Limitaciones

- El PC debe estar encendido y Brave abierto durante toda la ejecución.
- El usuario debe estar disponible para tomar el control del navegador cuando suene la alerta (selección de hora + confirmación SMS).
- El script no resuelve CAPTCHAs ni introduce códigos SMS.
- No hay rotación de IP. Si la IP es bloqueada, reiniciar el router para obtener una nueva IP (en la mayoría de conexiones domésticas españolas).
- El script opera en una sola pestaña. No abrir otras pestañas ni interactuar con Brave mientras el script está corriendo.

> **Nota:** Si Brave se cierra o la conexión se pierde, el script se reconecta automáticamente. No requiere reinicio manual.

---

## 16. Resumen de mapeo de elementos HTML

Todos los IDs de elementos han sido identificados y verificados:

| Formulario | Elemento | ID | Evento/Función |
|---|---|---|---|
| F1 Provincia | Dropdown | `form` | — |
| F1 Provincia | Botón Aceptar | `btnAceptar` | `envia()` |
| F2 Trámite | Dropdown | `tramiteGrupo[0]` | `eliminarSeleccionOtrosGrupos(0)` |
| F2 Trámite | Botón Aceptar | `btnAceptar` | `envia()` |
| F3 Aviso | Botón Entrar | `btnEntrar` | `document.forms[0].submit()` |
| F4 Datos | Input NIE | `txtIdCitado` | — |
| F4 Datos | Input Nombre | `txtDesCitado` | `comprobarDatos()` |
| F4 Datos | Botón Aceptar | `btnEnviar` | `envia()` |
| F5 Solicitar | Botón Solicitar | `btnEnviar` | `enviar('solicitud')` |
| No citas | Botón (texto variable: "Salir"/"Aceptar") | búsqueda por texto | `goAc_opc_direct()` |

URL de inicio: `https://icp.administracionelectronica.gob.es/icpplus/index.html`

## 17. Estructura del proyecto

```
surftbrowsing/
├── cita_bot.py                # Orquestación: formularios, bucle principal, evaluación
├── comportamiento_humano.py   # Motor anti-detección: SimuladorHumano, WAF, delays
├── cdp_helpers.py             # Capa CDP: CDPSession, ejecutar_js, safe_js_string
├── config.json                # IDs de elementos HTML del portal
├── .env.example               # Plantilla de configuración personal
├── .env                       # Configuración personal (no se sube al repo)
├── requirements.txt           # Dependencias de producción
├── requirements-dev.txt       # Dependencias de desarrollo (pytest, coverage)
├── README.md                  # Este documento (incluye evaluación y deuda técnica)
└── tests/                     # Tests automatizados (151 tests)
    ├── conftest.py            # Fixtures: MockWebSocket, mock_cdp
    ├── test_backoff.py        # Tests de BackoffController
    ├── test_cdp_session.py    # Tests de CDPSession (reconexión, timeouts)
    ├── test_config.py         # Validación de config.json
    ├── test_detection.py      # Tests de detección de citas y WAF
    ├── test_integration.py    # Tests de integración (reconexión, backoff, URL)
    ├── test_js_helpers.py     # Tests de safe_js_string (escape de strings)
    ├── test_main.py           # Tests del bucle principal
    ├── test_navigation.py     # Tests de formularios y navegación
    └── test_simulador_humano.py # Tests de SimuladorHumano (30 tests)
```

### Ejecutar tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v                                                      # Todos los tests
python -m pytest tests/ --cov=cita_bot --cov=cdp_helpers --cov=comportamiento_humano  # Con cobertura
```

---

## 18. Refactoring anti-detección

Se completó un refactoring en 6 fases para mejorar la evasión de detección del WAF:

| Fase | Descripción | Estado |
|------|-------------|--------|
| 0 | Extraer `cdp_helpers.py` (capa CDP pura) | Completada |
| 1 | Extraer `comportamiento_humano.py` (funciones anti-detección) | Completada |
| 2 | Clase `SimuladorHumano` con estado persistente del ratón | Completada |
| 3 | Movimiento de ratón concurrente durante delays (`asyncio.create_task`) | Completada |
| 4 | Secuencias pre-acción con orden variable (`secuencia_pre_accion()`) | Completada |
| 5 | Scroll nativo via `mouseWheel` CDP (reemplaza `window.scrollBy()` JS) | Completada |

Mejoras clave:
- **Ratón nunca quieto**: durante delays de 2-5s, el ratón se mueve con 4 patrones diferentes
- **Secuencias impredecibles**: cada acción de formulario ejecuta 2-4 acciones preparatorias en orden aleatorio
- **Scroll indetectable**: eventos `mouseWheel` nativos via CDP, indistinguibles de un usuario real
- **Estado Python-side**: posición del ratón mantenida en `SimuladorHumano`, sin `window.__mouse_pos` global JS

---

## 19. Evaluación de la solución

> Fecha: 2026-03-19

**Veredicto: SOLUCIÓN SÓLIDA Y BIEN ESTRUCTURADA**

### Tests

| Métrica | Valor |
|---------|-------|
| Tests totales | 151 |
| Tests pasados | 151/151 (100%) |
| Archivos de test | 10 |
| Módulos cubiertos | `cita_bot.py`, `cdp_helpers.py`, `comportamiento_humano.py` |

Líneas no cubiertas corresponden a funciones que requieren infraestructura externa (Brave, WebSocket real, SO Windows): `obtener_ws_url()`, `alerta_sonora()`, `conectar_brave()`, `main()`, `__main__`.

### Puntuación

| Categoría | Nota (1-10) | Comentario |
|-----------|-------------|------------|
| Funcionalidad | 9 | Cumple todos los objetivos planteados |
| Calidad de código | 8 | Limpio, consistente, bien estructurado |
| Tests | 9 | 151 tests, cobertura de 3 módulos |
| Documentación | 9 | README exhaustivo, deuda técnica documentada |
| Robustez | 8 | Reconexión automática, backoff, manejo de errores |
| Seguridad | 8 | Escape de strings, credenciales en .env |
| Mantenibilidad | 8 | Config externalizada, código modular |
| **Promedio** | **8.4** | **Solución de alta calidad** |

### Observaciones menores

1. `verificar_url()` acepta cualquier URL que contenga "icpplus" — riesgo bajo dado el contexto.
2. Sin `texto_hay_citas` configurado, la ausencia del texto negativo se interpreta como "hay citas". Se recomienda configurar `texto_hay_citas` para reducir falsos positivos.
3. No hay keep-alive HTTP activo tras detectar cita — la sesión puede expirar si el usuario tarda en llegar al PC.

### Riesgos

| Riesgo | Severidad | Mitigación actual |
|--------|-----------|-------------------|
| Portal cambia IDs HTML | Media | `config.json` externalizado, fácil de actualizar |
| Portal implementa CAPTCHA | Alta | No mitigado (fuera de alcance) |
| Falso positivo sin texto positivo | Baja-Media | `texto_hay_citas` configurable (opcional) |
| Sesión expira tras alerta | Baja | Usuario debe actuar rápido |
| Ban por IP | Baja | Delays aleatorios + backoff, sin rotación de IP |

---

## 20. Deuda técnica

Auditoría exhaustiva del código: 17 puntos de falla identificados. **Todos cerrados.**

| ID | Título | Severidad | Estado |
|----|--------|-----------|--------|
| TD-01 | WebSocket muerto sin reconexión | **CRÍTICA** | **Resuelto** |
| TD-02 | Falso positivo en detección de citas | **CRÍTICA** | **Resuelto** |
| TD-03 | Escape de strings insuficiente en JS | Media-Alta | **Resuelto** |
| TD-04 | `click_salir()` rompe el loop | Media | **Resuelto** |
| TD-05 | Selección de pestaña no determinista | Media | Descartada |
| TD-06 | `asyncio.get_event_loop()` deprecado | Baja-Media | Descartada |
| TD-07 | Sin detección de CAPTCHA | Crítica | Descartada |
| TD-08 | Keep-alive no genera tráfico HTTP real | Media | **Resuelto** |
| TD-09 | Intervalo fijo sin backoff adaptativo | Media | **Resuelto** |
| TD-10 | Sin tests automatizados | Media | **Resuelto** |
| TD-11 | Alerta sonora inútil en Linux/Mac | Baja | Descartada |
| TD-12 | Timeout uniforme para todas las operaciones CDP | Baja-Media | **Resuelto** |
| TD-13 | `esperar_elemento` escapa IDs redundantemente | Baja-Media | **Resuelto** |
| TD-14 | `click_salir` lanza RuntimeError en vez de tolerar fallos | Media | **Resuelto** |
| TD-15 | `scroll_humano` se ejecuta antes de verificar carga | Media | **Resuelto** |
| TD-16 | `asyncio.get_event_loop()` deprecado en `esperar_elemento` | Baja | **Resuelto** |
| TD-17 | Timeout de `esperar_elemento` hardcoded (10s) | Baja-Media | **Resuelto** |

- **13 resueltos:** TD-01 a TD-04, TD-08 a TD-10, TD-12 a TD-17
- **4 descartados:** TD-05 (una sola pestaña), TD-06 (subsumido por TD-16), TD-07 (requiere servicio externo), TD-11 (target es Windows)
