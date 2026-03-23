# AUTO WEBSURFT v2

**Estado:** Fases 0-3 implementadas y testeadas. Fase 4 pendiente.

---

## Arquitectura

Automatización del portal ICP via Chrome DevTools Protocol (CDP). Cada página del formulario es una **fase** independiente (`fase_0`, `fase_1`, ...) con su propia secuencia de micro-acciones. Una **personalidad** (rapido/normal/lento) se elige aleatoriamente por ciclo y modula todos los tiempos.

```
Fase 0 — Selección de provincia          [IMPLEMENTADA]
Fase 1 — Selección de trámite            [IMPLEMENTADA]
Fase 2 — Aviso informativo               [IMPLEMENTADA]
Fase 3 — Datos personales (NIE + nombre) [IMPLEMENTADA]
Fase 4 — Solicitud de cita + evaluación  [PENDIENTE]
```

---

## Estructura del Proyecto

```
surftbrowsing/
├── bot.py                    # Orquestador: ciclo principal, backoff, reconexión
├── humano.py                 # Primitivas + fases (Personalidad, EstadoRaton, fase_0..fase_3)
├── cdp_core.py               # Capa CDP: CDPSession, ejecutar_js, esperar_elemento, detectar_waf, css_escape_id
├── config.json               # IDs de elementos HTML del portal
├── .env.example              # Plantilla con ~40 variables de timing configurables
├── .env                      # Config personal (no se sube al repo)
├── requirements.txt          # websockets, python-dotenv
├── requirements-dev.txt      # pytest, pytest-asyncio
├── specs/
│   ├── pagina_0_seleccion_sede.md  # Spec detallada de fase 0
│   └── pagina_1_seleccion_tramite.md  # Spec detallada de fase 1
├── tests/
│   ├── conftest.py           # MockWebSocket, fixtures compartidas
│   ├── test_cdp_core.py      # 47 tests — CDPSession, ejecutar_js, esperar_elemento, WAF, css_escape_id
│   ├── test_humano.py        # 24 tests — primitivas (ratón, click, tecla, scroll)
│   ├── test_fase_0.py        # 31 tests — flujo completo fase 0, robustez, edge cases
│   ├── test_fase_1.py        # 28 tests — flujo completo fase 1, prefijo, CSS escaping
│   ├── test_fase_2.py        # 21 tests — flujo completo fase 2, scroll exhaustivo
│   ├── test_fase_3.py        # 23 tests — flujo completo fase 3, autocomplete
│   ├── test_bot.py           # 18 tests — BackoffController, jitter, limpieza caché
│   ├── old_conftest.py       # [REF] Fixtures v1
│   └── old_test_*.py         # [REF] Tests v1
├── old_*.py / old_*.json     # [REF] Código v1 funcional (no borrar hasta v2 validada)
└── old_README.md             # [REF] Documentación v1
```

---

## Módulos

### `cdp_core.py`
Capa CDP reutilizada de v1. WebSocket → navegador con `--remote-debugging-port=9222`.

| Función | Descripción |
|---------|-------------|
| `CDPSession` | Sesión CDP con send/receive, eventos, pre_wait_event |
| `ejecutar_js(cdp, expr)` | Evalúa JS en la página, retorna resultado |
| `esperar_elemento(cdp, selector)` | Polling hasta que el elemento sea visible e interactuable |
| `esperar_carga_pagina(cdp)` | Espera `Page.loadEventFired` |
| `detectar_waf(cdp)` | Detecta bloqueo WAF por texto en body |
| `safe_js_string(s)` | Escapa strings para inyección segura en JS |
| `css_escape_id(raw_id)` | Escapa IDs con caracteres especiales para CSS (`tramiteGrupo[0]` → `#tramiteGrupo\[0\]`) |

### `humano.py`
Primitivas de bajo nivel + fases. Todos los tiempos vienen de `.env`.

**Primitivas:**

| Función | Qué hace |
|---------|----------|
| `_mover_raton(cdp, raton, x, y, dur)` | Trayectoria smoothstep con desviaciones |
| `_mover_a_elemento(cdp, raton, sel, pers)` | Mueve al elemento con overshoot opcional (12% prob) |
| `_click_nativo(cdp, x, y)` | mousePressed → pausa → mouseReleased |
| `_enviar_tecla(cdp, key)` | keyDown → keyUp via CDP |
| `_scroll_exploratorio(cdp, raton, min, max)` | mouseWheel nativo en 2-3 pasos |
| `_micro_movimiento(cdp, raton, ...)` | Movimiento idle del ratón |
| `_movimientos_idle_durante_espera(cdp, raton, evento)` | Idle mientras espera carga |
| `_rellenar_campo_autocomplete(cdp, pers, raton, sel, id, nombre)` | Click en input → ArrowDown → Enter (autocomplete del navegador) |

**Clases:**

| Clase | Descripción |
|-------|-------------|
| `Personalidad` | velocidad (rapido/normal/lento), factor, nerviosismo, atencion. `delay(min, max)` modula tiempos. |
| `EstadoRaton` | Mantiene posición x/y Python-side para trayectorias continuas |

**Fases implementadas:**

| Fase | Función | Pasos |
|------|---------|-------|
| 0 | `fase_0(cdp, pers, raton, primera_vez, config)` | Navegar → aterrizaje → abrir dropdown → buscar provincia (exact match) → seleccionar → click Aceptar → esperar carga |
| 1 | `fase_1(cdp, pers, raton, config)` | Aterrizaje + scroll obligatorio → abrir dropdown trámite → buscar trámite (prefix match) → seleccionar → click Aceptar → esperar carga |
| 2 | `fase_2(cdp, pers, raton, config)` | Aterrizaje → scroll exhaustivo hasta agotar contenido → focus + click "Entrar" → esperar carga |
| 3 | `fase_3(cdp, pers, raton, config)` | Aterrizaje → autocomplete NIE (click → ArrowDown → Enter) → autocomplete Nombre → focus + click "Aceptar" → esperar carga |

### `bot.py`
Orquestador principal. Ciclo infinito con personalidad nueva por iteración.

| Componente | Descripción |
|------------|-------------|
| `BackoffController` | Backoff exponencial con umbral de alerta |
| `limpiar_datos_navegador(cdp, origin)` | Limpia caché/storage sin tocar cookies |
| `main()` | Ciclo: conectar → fase_0 → fase_1 → fase_2 → fase_3 → (fase 4 pendiente) → limpiar → esperar |

---

## Configuración

### `.env` (requerido)

```bash
# Depuración
PASO_HASTA=3          # 0=solo fase 0, 1=hasta fase 1, ..., 5=todas las fases

# Timeouts
TIMEOUT_CARGA_PAGINA_SEGUNDOS=15
TIMEOUT_ESPERA_ELEMENTO_SEGUNDOS=10

# ~40 variables de timing (ver .env.example para lista completa)
# Ejemplo:
ATERRIZAJE_PAUSA_MIN=1.0
ATERRIZAJE_PAUSA_MAX=3.0
PERSONALIDAD_FACTOR_RAPIDO=0.6
PERSONALIDAD_FACTOR_NORMAL=1.0
PERSONALIDAD_FACTOR_LENTO=1.5
```

### `config.json`

IDs de elementos HTML del portal verificados:

```json
{
  "url_inicio": "https://icp.administracionelectronica.gob.es/icpplus/index.html",
  "tramite_prefijo": "POLICIA TARJETA CONFLICTO UKRANIA",
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
    "boton_solicitar_cita": "btnEnviar"
  }
}
```

Valores configurables en `config.json`:
- `provincia_objetivo` — provincia a seleccionar en fase 0 (default: "Madrid")
- `tramite_prefijo` — prefijo del trámite a buscar en fase 1 (match con `startsWith`)

---

## Uso

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar .env (opcional — solo para ajustar timings)
cp .env.example .env

# 3. Asegurar que el navegador tiene NIE y nombre guardados en autocomplete

# 4. Abrir navegador con CDP
brave --remote-debugging-port=9222

# 5. Ejecutar
PASO_HASTA=0 python bot.py   # solo fase 0
PASO_HASTA=3 python bot.py   # fases 0-3
```

---

## Tests

```bash
# Instalar deps de desarrollo
pip install -r requirements-dev.txt

# Ejecutar todos (192 tests)
python -m pytest tests/ -v

# Solo una suite
python -m pytest tests/test_fase_0.py -v    # 31 tests
python -m pytest tests/test_fase_1.py -v    # 28 tests
python -m pytest tests/test_fase_2.py -v    # 21 tests
python -m pytest tests/test_fase_3.py -v    # 23 tests
python -m pytest tests/test_humano.py -v    # 24 tests
python -m pytest tests/test_cdp_core.py -v  # 47 tests
python -m pytest tests/test_bot.py -v       # 18 tests
```

---

## Pendiente

- [x] Fase 0 — Selección de provincia
- [x] Fase 1 — Selección de trámite
- [x] Fase 2 — Aviso informativo (scroll exhaustivo + click "Entrar")
- [x] Fase 3 — Datos personales (NIE + nombre via autocomplete del navegador)
- [ ] Fase 4 — Solicitar cita + evaluación de resultado
- [ ] Pruebas manuales contra el portal real con `PASO_HASTA` progresivo

---

## Archivos de Referencia (old_*)

Código v1 funcional. No borrar hasta que v2 esté validada en producción.

| Archivo | Referencia para |
|---------|----------------|
| `old_cdp_helpers.py` | CDPSession, ejecutar_js, safe_js_string |
| `old_cita_bot.py` | BackoffController, evaluar_estado_pagina |
| `old_comportamiento_humano.py` | SimuladorHumano, detectar_waf, limpiar_datos_navegador |
| `old_config.json` | IDs verificados |
| `old_README.md` | Documentación completa del flujo del portal |
