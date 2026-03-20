# AUTO WEBSURFT v2 — Replicación de Comportamiento Humano por Fases

**Fecha:** 20 de marzo de 2026
**Estado:** En desarrollo (plan de trabajo)

---

## 1. Contexto y Motivación

La versión anterior (archivos `old_*`) demostró que la automatización del portal ICP funciona correctamente a nivel funcional: los formularios se rellenan, la detección de disponibilidad es fiable, y la infraestructura CDP es sólida.

**El problema:** el WAF (Web Application Firewall) detecta y bloquea la automatización. No es un problema de funcionalidad, sino de **patrones reconocibles**. El bot actual, aunque incluye delays aleatorios y movimientos de ratón, sigue siendo predecible porque:

1. **Estructura repetitiva:** cada ciclo ejecuta exactamente la misma secuencia de acciones en el mismo orden.
2. **Timing artificial:** los delays aleatorios tienen distribuciones uniformes que no corresponden al timing real de un humano.
3. **Acciones atómicas:** cada acción (seleccionar dropdown, rellenar campo) se ejecuta como un bloque monolítico, sin las micro-acciones intermedias que un humano hace naturalmente.
4. **Ausencia de comportamiento contextual:** un humano no interactúa con una página de forma idéntica cada vez — lee, duda, se distrae, corrige, revisa.

---

## 2. Nuevo Enfoque: Replicación Exacta de Comportamiento Humano

La idea central es **grabar mentalmente lo que hago yo (el usuario) cuando relleno el formulario paso a paso**, y codificar esa secuencia exacta con micro-variaciones.

### Principios

1. **Cada página del formulario es una FASE independiente** con su propia secuencia de acciones.
2. **Cada fase replica el comportamiento humano real paso a paso**, no como una abstracción genérica ("mover ratón, esperar, hacer click") sino como una secuencia concreta: "llego a la página, miro la pantalla 1-2 segundos, muevo el ratón hacia el dropdown, lo abro, busco la opción, la selecciono, muevo el ratón al botón, hago click".
3. **Micro-variaciones controladas**: el orden de ciertas acciones puede variar ligeramente, los tiempos tienen jitter, pero la estructura general replica fielmente el flujo humano.
4. **Sin patrones repetitivos entre ciclos**: cada ejecución de una fase elige entre varias "personalidades" o variantes del mismo flujo humano.

---

## 3. Arquitectura de Fases

Cada página del formulario se mapea a una fase. Cada fase es una función async que ejecuta una secuencia de micro-acciones que replican exactamente lo que haría un humano en esa página.

```
FASE 0 — Navegación inicial (llegar a la web)
FASE 1 — Página de selección de provincia
FASE 2 — Página de selección de trámite
FASE 3 — Página de aviso informativo
FASE 4 — Página de datos personales (NIE + nombre)
FASE 5 — Página de solicitud de cita + evaluación
```

### Estructura de cada fase

Cada fase se descompone en **micro-pasos secuenciales** que replican el flujo humano real:

```python
async def fase_X(sesion):
    # 1. ATERRIZAJE: la página acaba de cargar
    #    - Humano: mira la pantalla, orientándose (1-3s sin hacer nada)
    #    - Bot: pausa de "lectura" con micro-movimientos oculares del ratón

    # 2. RECONOCIMIENTO: identifica los elementos de la página
    #    - Humano: mueve los ojos (y a veces el ratón) por la página
    #    - Bot: scroll suave, movimiento del ratón por zonas de contenido

    # 3. APROXIMACIÓN: mueve el ratón hacia el primer elemento interactivo
    #    - Humano: trayectoria imprecisa, a veces se desvía, corrige
    #    - Bot: curva con overshoot ocasional

    # 4. INTERACCIÓN: interactúa con el elemento (click, select, type)
    #    - Humano: click, pausa mirando el resultado, continúa
    #    - Bot: click CDP nativo, pausa post-click

    # 5. TRANSICIÓN: busca el siguiente elemento o botón de envío
    #    - Humano: puede releer algo, scroll, mover ratón idle
    #    - Bot: comportamiento variable antes de la siguiente acción

    # 6. ENVÍO: click en botón de envío/aceptar
    #    - Humano: mueve ratón al botón, a veces duda, click
    #    - Bot: aproximación con pausa pre-click variable

    # 7. ESPERA: la página carga
    #    - Humano: mira la pantalla esperando, puede mover ratón
    #    - Bot: movimiento idle durante la espera de carga
```

---

## 4. Plan de Trabajo — Fases de Implementación

### Fase de Implementación 0: Infraestructura Base

**Objetivo:** Reutilizar la capa CDP existente y crear el nuevo esqueleto.

- [ ] Crear `cdp_core.py` — Copiar/adaptar la capa CDP de `old_cdp_helpers.py` (CDPSession, ejecutar_js, safe_js_string). Esta capa está validada y no necesita cambios funcionales.
- [ ] Crear `config.json` — Mismo contenido que `old_config.json` (IDs de elementos verificados).
- [ ] Crear `humano.py` — Nuevo módulo de comportamiento humano, diseñado desde cero con el enfoque por fases.
- [ ] Crear `bot.py` — Nuevo orquestador que ejecuta las fases secuencialmente.

### Fase de Implementación 1: Motor de Micro-Acciones Humanas

**Objetivo:** Construir las primitivas de bajo nivel que las fases usarán.

Cada primitiva replica UNA acción atómica humana, no una secuencia genérica:

| Primitiva | Qué replica | Cómo |
|-----------|-------------|------|
| `mirar_pagina()` | Humano aterriza en página y la mira | Pausa 1-3s + micro-movimientos de ratón tipo "lectura ocular" |
| `buscar_elemento(id)` | Humano busca visualmente un campo | Scroll si necesario + movimiento de ratón errático hacia la zona del elemento |
| `aproximar_raton(id)` | Humano mueve la mano hacia el campo | Curva imprecisa con overshoot ocasional (10-15% prob) y corrección |
| `click_campo(id)` | Humano hace click en un input/select | mousePressed + mouseReleased CDP con pausa inter-click realista |
| `seleccionar_opcion(id, valor)` | Humano abre dropdown y elige opción | Abrir → pausa visual → seleccionar → pausa confirmación |
| `escribir_texto(id, texto)` | Humano escribe en un campo | Char a char con Input.dispatchKeyEvent, velocidad variable, pausas entre palabras |
| `click_boton(id)` | Humano hace click en botón de envío | Aproximación + pausa pre-click (¿estoy seguro?) + click |
| `scroll_lectura()` | Humano hace scroll para leer contenido | mouseWheel nativo, 1-3 pasos, velocidad variable |
| `pausa_pensamiento()` | Humano duda, relee, se distrae | Pausa 0.5-4s con movimiento idle de ratón |
| `micro_correccion()` | Humano mueve ratón ligeramente sin motivo | Desplazamiento ±5-15px desde posición actual |

#### Escritura char-a-char vs `.value =`

La versión anterior usa `.value = "texto"` + `dispatchEvent`. Esto es instantáneo y detectable: un campo que pasa de vacío a lleno en 0ms no es humano.

La nueva versión escribirá carácter a carácter usando `Input.dispatchKeyEvent` de CDP:

```python
async def escribir_texto(sesion, element_id, texto):
    await click_campo(sesion, element_id)  # Focus nativo
    for i, char in enumerate(texto):
        # Velocidad variable: más lento al inicio, pausa entre palabras
        if char == ' ':
            await asyncio.sleep(random.uniform(0.08, 0.20))
        else:
            await asyncio.sleep(random.uniform(0.04, 0.12))

        # Enviar tecla via CDP (genera eventos keyDown, keyPress, keyUp nativos)
        await sesion.cdp.send("Input.dispatchKeyEvent", {
            "type": "keyDown", "text": char, ...
        })
        await sesion.cdp.send("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": char, ...
        })

        # Pausa ocasional: humano levanta las manos del teclado
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 1.0))
```

Esto genera una secuencia de eventos `keyDown`/`keyUp` con `isTrusted: true`, idéntica a la de un humano escribiendo.

### Fase de Implementación 2: Secuencias por Página (Fases 0-5)

**Objetivo:** Implementar cada fase como una secuencia concreta de micro-acciones.

#### FASE 0 — Navegación Inicial

```
Secuencia humana:
1. El navegador carga la URL de inicio
2. Miro la página 1-2 segundos (¿es la página correcta?)
3. Posiblemente hago un scroll suave para ver el contenido
4. Identifico el dropdown de provincia
```

#### FASE 1 — Selección de Provincia (Madrid)

```
Secuencia humana real (lo que YO hago):
1. La página cargó → miro la pantalla 1-2s orientándome
2. Veo el dropdown de provincia → muevo el ratón hacia él
3. Hago click en el dropdown para abrirlo
4. Busco "Madrid" en la lista (pausa visual 0.5-1.5s)
5. Selecciono "Madrid"
6. Miro la pantalla brevemente (¿se actualizó algo? 0.5-1s)
7. Muevo el ratón hacia el botón "Aceptar"
8. Pausa mínima antes de hacer click (¿todo correcto? 0.3-0.8s)
9. Click en "Aceptar"
10. Espero a que cargue la siguiente página
```

**Variante A (el que va rápido):**
- Pausa inicial corta (0.5-1s)
- Movimiento directo al dropdown
- Click rápido en Aceptar

**Variante B (el que lee):**
- Pausa inicial larga (2-3s)
- Scroll antes de interactuar
- Lee el aviso si lo hay
- Pausa antes de Aceptar

**Variante C (el que duda):**
- Mueve el ratón hacia el dropdown, se desvía, vuelve
- Selecciona provincia, pausa larga mirando
- Mueve ratón a otro lado y luego al botón Aceptar

#### FASE 2 — Selección de Trámite

```
Secuencia humana real:
1. Página cargada → miro 1-2s
2. El dropdown de oficina ya tiene la opción por defecto → lo ignoro
3. Busco el dropdown de trámite → muevo ratón hacia él
4. Click para abrir el dropdown
5. Busco el trámite correcto (pausa visual 1-2s, puede haber scroll dentro del dropdown)
6. Selecciono el trámite
7. Verifico visualmente que se seleccionó bien (0.5-1s)
8. Muevo ratón al botón "Aceptar"
9. Click en "Aceptar"
10. Espero carga
```

**Micro-variación:** a veces miro primero el dropdown de oficina (muevo el ratón allí), decido dejarlo por defecto, y luego voy al de trámite.

#### FASE 3 — Aviso Informativo

```
Secuencia humana real:
1. Página de aviso cargada → la leo (2-5s)
2. Hago scroll para ver el contenido completo (a veces)
3. Busco el botón "Entrar"
4. Muevo ratón al botón
5. Click en "Entrar"
6. Espero carga
```

**Variante rápida:** ya me sé el aviso, voy directo al botón (1-2s total).
**Variante lectora:** leo todo, scroll, pauso, luego click (5-8s total).

#### FASE 4 — Datos Personales

```
Secuencia humana real:
1. Página cargada → miro los campos 1-2s
2. Hago click en el campo NIE
3. Escribo mi NIE (carácter a carácter, ~1-2s total para 9 chars)
4. Tab o click en el campo Nombre
5. Escribo mi nombre (carácter a carácter, ~2-4s según longitud)
6. Miro que todo esté bien (0.5-1.5s)
7. Muevo ratón al botón "Aceptar"
8. Click en "Aceptar"
9. Espero carga
```

**Variante de orden:** a veces relleno primero el nombre y luego el NIE (ya implementado en v1, mantener).

**Variante de corrección (10-15% prob):** escribo un carácter mal, pauso, borro con Backspace, corrijo.

#### FASE 5 — Solicitar Cita + Evaluación

```
Secuencia humana real:
1. Página cargada → miro la pantalla 1-2s
2. Busco el botón "Solicitar Cita"
3. Muevo ratón al botón
4. Pausa pre-click (momento de "vamos allá")
5. Click en "Solicitar Cita"
6. Espero la respuesta (2-5s mirando la pantalla)
7. Leo el resultado
```

La evaluación del resultado (HAY_CITAS / NO_HAY_CITAS / WAF / DESCONOCIDO) se mantiene idéntica a la versión anterior — está validada y es robusta.

### Fase de Implementación 3: Variantes y Personalidades

**Objetivo:** Que cada ejecución de cada fase no sea idéntica a la anterior.

Implementar un sistema de "personalidades" que module los tiempos:

```python
class Personalidad:
    """Define el perfil temporal de una sesión."""
    def __init__(self):
        # Cada sesión elige aleatoriamente un perfil
        self.velocidad = random.choice(["rapido", "normal", "lento"])
        self.nerviosismo = random.uniform(0.0, 1.0)  # afecta a micro-correcciones
        self.atencion = random.uniform(0.5, 1.0)  # afecta a pausas de lectura

    def pausa_aterrizaje(self) -> float:
        base = {"rapido": 0.8, "normal": 1.5, "lento": 2.5}[self.velocidad]
        return base * random.uniform(0.8, 1.3)

    def pausa_pre_click(self) -> float:
        base = {"rapido": 0.2, "normal": 0.5, "lento": 1.0}[self.velocidad]
        return base * random.uniform(0.7, 1.4)

    def velocidad_escritura(self) -> float:
        """Retorna delay base entre teclas en segundos."""
        return {"rapido": 0.04, "normal": 0.07, "lento": 0.12}[self.velocidad]
```

Una personalidad se elige al inicio de cada ciclo y se mantiene durante las 6 fases. Esto asegura consistencia intra-ciclo (un humano no cambia de velocidad drásticamente entre formularios) pero variabilidad inter-ciclo.

### Fase de Implementación 4: Gestión de Ciclo y WAF

**Objetivo:** Orquestador principal que ejecuta las fases y gestiona reintentos.

- Mantener la lógica de detección WAF validada de la v1 (referencia: `old_comportamiento_humano.py:detectar_waf`).
- Mantener el BackoffController validado (referencia: `old_cita_bot.py:BackoffController`).
- Mantener la evaluación de estado de página (referencia: `old_cita_bot.py:evaluar_estado_pagina`).
- Mantener la limpieza de caché entre ciclos (referencia: `old_comportamiento_humano.py:limpiar_datos_navegador`).
- **Nuevo:** entre ciclos, variar el tiempo de espera con una distribución más natural (no uniforme).
- **Nuevo:** al inicio de cada ciclo, crear una nueva `Personalidad` que module toda la sesión.

### Fase de Implementación 5: Tests

**Objetivo:** Tests para el nuevo código, reutilizando fixtures de `old_conftest.py`.

---

## 5. Diferencias Clave vs Versión Anterior

| Aspecto | v1 (old_*) | v2 (nuevo) |
|---------|-----------|------------|
| Estructura | Secuencia genérica para todos los formularios | Secuencia específica por página |
| Interacción con campos | `.value = "texto"` instantáneo | Escritura char-a-char via CDP KeyEvent |
| Focus en campos | `dispatchEvent('input')` JS | Click CDP nativo → `isTrusted: true` |
| Variabilidad | Delays uniformes aleatorios | Personalidades con distribuciones naturales |
| Scroll | Genérico al final de cada paso | Contextual: solo cuando un humano haría scroll |
| Movimiento de ratón | Acciones preparatorias aleatorias | Trayectoria que replica el recorrido visual real |
| Overshoot | No existe | 10-15% probabilidad de pasarse y corregir |
| Correcciones de texto | No existen | 10-15% prob de typo + backspace + corrección |
| Patrón entre ciclos | Mismo flujo exacto | Personalidad aleatoria por ciclo |

---

## 6. Archivos de Referencia (old_*)

Los archivos renombrados con prefijo `old_` contienen código **funcional y validado**. Sirven como referencia para:

| Archivo | Referencia para |
|---------|----------------|
| `old_cdp_helpers.py` | CDPSession, ejecutar_js, safe_js_string — reutilizar tal cual |
| `old_cita_bot.py` | BackoffController, evaluar_estado_pagina, ciclo principal |
| `old_comportamiento_humano.py` | SimuladorHumano, detectar_waf, limpiar_datos_navegador |
| `old_config.json` | IDs de elementos HTML verificados del portal |
| `old_README.md` | Documentación completa del flujo del portal (pasos, IDs, eventos) |
| `tests/old_conftest.py` | Fixtures: MockWebSocket, mock_cdp |
| `tests/old_test_*.py` | Tests validados (151 pasando) como referencia |

---

## 7. Estructura del Proyecto (objetivo)

```
surftbrowsing/
├── bot.py                    # Orquestador: ciclo principal, gestión de fases
├── humano.py                 # Motor de micro-acciones humanas + personalidades
├── cdp_core.py               # Capa CDP (basada en old_cdp_helpers.py)
├── config.json               # IDs de elementos HTML del portal
├── .env.example              # Plantilla de configuración personal
├── .env                      # Configuración personal (no se sube al repo)
├── requirements.txt          # Dependencias de producción
├── requirements-dev.txt      # Dependencias de desarrollo
├── README.md                 # Este documento
├── old_cita_bot.py           # [REF] Orquestador v1
├── old_comportamiento_humano.py  # [REF] Comportamiento humano v1
├── old_cdp_helpers.py        # [REF] CDP helpers v1
├── old_config.json           # [REF] Config v1
├── old_README.md             # [REF] Documentación v1
└── tests/
    ├── conftest.py           # Fixtures para nuevos tests
    ├── test_*.py             # Tests nuevos
    ├── old_conftest.py       # [REF] Fixtures v1
    └── old_test_*.py         # [REF] Tests v1 (151 tests)
```

---

## 8. Orden de Implementación Recomendado

1. **cdp_core.py** — Copiar y limpiar la capa CDP. Sin cambios funcionales.
2. **config.json** — Copiar `old_config.json`.
3. **humano.py** — Primitivas de micro-acciones (mirar, aproximar, click, escribir).
4. **Fases 0-1** — Implementar y probar navegación + selección de provincia.
5. **Fases 2-3** — Selección de trámite + aviso informativo.
6. **Fase 4** — Datos personales con escritura char-a-char.
7. **Fase 5** — Solicitar cita + evaluación (reutilizar lógica v1).
8. **bot.py** — Orquestador con personalidades y ciclo principal.
9. **Tests** — Validar cada fase independientemente.
10. **Pruebas manuales** — Ejecutar contra el portal real con `PASO_HASTA` progresivo.

---

## 9. Notas Importantes

- **No reinventamos la rueda:** la capa CDP, la detección WAF, la evaluación de resultados y el BackoffController están validados. Los reutilizamos.
- **Lo que cambia es HOW, no WHAT:** el bot sigue haciendo exactamente lo mismo (rellenar 5 formularios), pero la forma en que lo hace es indistinguible de un humano real.
- **Cada fase se puede probar independientemente** con `PASO_HASTA`, igual que en v1.
- **Los archivos old_* no se borran** hasta que la v2 esté completamente validada en producción.
