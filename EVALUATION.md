# Evaluación de la Solución — cita_bot

> Fecha: 2026-03-19
> Evaluador: Claude Code (automatizado)

---

## Resumen Ejecutivo

**Veredicto: SOLUCIÓN SÓLIDA Y BIEN ESTRUCTURADA**

El bot cumple su objetivo: automatizar la navegación del portal ICP para buscar citas de extranjería, con detección robusta y alerta al usuario. El código es limpio, bien documentado, y cuenta con una suite de tests completa.

---

## 1. Tests

| Métrica | Valor |
|---------|-------|
| Tests totales | 151 |
| Tests pasados | 151/151 (100%) |
| Archivos de test | 10 |
| Módulos cubiertos | `cita_bot.py`, `cdp_helpers.py`, `comportamiento_humano.py` |

**Desglose por archivo de test:**
- `test_simulador_humano.py` — 30 tests (SimuladorHumano: estado, scroll, delays, patrones, secuencias)
- `test_navigation.py` — tests de formularios y navegación (usa `mock_humano` fixture)
- `test_detection.py` — tests de detección de citas y WAF
- `test_cdp_session.py` — tests de CDPSession (reconexión, timeouts)
- `test_backoff.py`, `test_config.py`, `test_integration.py`, `test_js_helpers.py`, `test_main.py`

**Líneas no cubiertas:** Corresponden a funciones que requieren infraestructura externa (Brave, WebSocket real, SO Windows): `obtener_ws_url()`, `alerta_sonora()`, `conectar_brave()`, `main()`, `__main__`.

---

## 2. Arquitectura

### Puntos fuertes

- **CDP sobre Brave:** Decisión acertada. Evita la detección de WebDriver que Selenium expone. El portal ICP no puede distinguir la automatización de un usuario real.
- **Separación de config:** `config.json` externaliza los IDs HTML del portal, facilitando mantenimiento si el portal cambia.
- **BackoffController:** Implementación limpia de backoff exponencial con conteo de errores y alertas por umbral.
- **CDPSession:** Manejo correcto de WebSocket con callbacks, eventos pre-registrados, y detección de desconexión.
- **Anti-detección avanzada:** `SimuladorHumano` con movimiento de ratón concurrente durante delays (4 patrones), secuencias pre-acción con orden variable, scroll nativo via `mouseWheel` CDP, estado del ratón Python-side (no JS global).

### Arquitectura general

```
.env (credenciales) → cita_bot.py → comportamiento_humano.py → cdp_helpers.py → Brave Browser → Portal ICP
                         ↑                    ↑
                    config.json          SimuladorHumano
                    (IDs HTML)       (estado ratón, viewport)
```

Arquitectura modular en 3 capas tras el refactoring anti-detección (6 fases completadas):
- `cdp_helpers.py` — Transporte CDP puro
- `comportamiento_humano.py` — Motor anti-detección (`SimuladorHumano`)
- `cita_bot.py` — Orquestación de formularios

---

## 3. Calidad del Código

### Positivo

- **Consistencia:** Todas las funciones de formulario siguen el mismo patrón simplificado: `secuencia_pre_accion(element_id)` → acción JS → siguiente paso.
- **Escape de strings:** `safe_js_string()` cubre los vectores de inyección JS relevantes (backslash, comillas, newlines, null bytes).
- **Manejo de errores:** Cada tipo de error tiene su handler específico en `main()` con backoff apropiado.
- **Logging:** Timestamps + número de intento en cada mensaje. Claro y útil para diagnóstico.
- **Configurabilidad:** Todos los timings son configurables vía `.env` sin tocar código.

### Observaciones menores

1. **Warning en test de reconexión** (línea 270): El mock de `ejecutar_js` no awaita correctamente la coroutine en `test_main_reconnects_when_not_alive`. No afecta funcionalidad, pero debería corregirse para tests limpios.

2. **`verificar_url()` es permisiva** (líneas 292-301): Acepta cualquier URL que contenga "icpplus". Si el portal redirige a una subpágina inesperada dentro de icpplus (ej. página de error), pasaría la verificación. Riesgo bajo dado el contexto.

3. **Detección de citas sin `texto_hay_citas`** (líneas 506-507): Si no se configura texto positivo, la ausencia del texto negativo se interpreta como "hay citas". Esto es documentado y funcional, pero el README debería enfatizar más la recomendación de configurar `texto_hay_citas` para reducir falsos positivos.

4. **Keep-alive eliminado** (correcto): La versión actual no mantiene sesión activa tras detectar cita — solo alerta sonora. Esto evita generar tráfico sospechoso pero significa que la sesión puede expirar si el usuario tarda en llegar al PC.

---

## 4. Deuda Técnica

El documento `TECHNICAL_DEBT.md` identifica 17 ítems. Estado actual:

| Estado | Cantidad |
|--------|----------|
| Resueltos | 13 (TD-01 a TD-04, TD-08 a TD-10, TD-12 a TD-17) |
| Descartados (justificado) | 4 (TD-05, TD-06, TD-07, TD-11) |
| Pendientes | 0 |

**Todos los ítems están cerrados.** Las decisiones de descarte son razonables:
- TD-05 (selección de pestaña): Riesgo bajo, uso esperado es una sola pestaña.
- TD-07 (CAPTCHA): Fuera de alcance, requeriría servicio externo.
- TD-11 (alerta Linux): Target es Windows, `\a` es suficiente como fallback.

---

## 5. Documentación

- **README.md**: Completo. Cubre instalación, arquitectura modular (3 capas), `SimuladorHumano`, flujo detallado, anti-detección, troubleshooting, y testing.
- **PLAN_ANTIDETECCION.md**: Plan de refactoring en 6 fases, todas completadas con indicadores de estado.
- **TECHNICAL_DEBT.md**: Auditoría exhaustiva con análisis de impacto y soluciones (17 ítems, todos cerrados).
- **Docstrings:** Presentes en todas las funciones y clases públicas.
- **.env.example:** Documentado con valores por defecto.

---

## 6. Seguridad

- **Credenciales:** NIE y nombre se cargan desde `.env` (no hardcoded). `.env` no está trackeado en git.
- **JS Injection:** `safe_js_string()` previene inyección en strings interpolados.
- **No hay secretos expuestos:** El log muestra solo los primeros 3 caracteres del NIE y el primer nombre.
- **SSL:** El README documenta correctamente la necesidad de `--ignore-certificate-errors` para el portal ICP.

---

## 7. Riesgos Identificados

| Riesgo | Severidad | Mitigación actual |
|--------|-----------|-------------------|
| Portal cambia IDs HTML | Media | `config.json` externalizado, fácil de actualizar |
| Portal implementa CAPTCHA | Alta | No mitigado (TD-07 descartado) |
| Falso positivo sin texto positivo | Baja-Media | `texto_hay_citas` configurable (opcional) |
| Sesión expira tras alerta | Baja | Usuario debe actuar rápido; no hay keep-alive activo |
| Ban por IP | Baja | Delays aleatorios + backoff, pero sin rotación de IP |

---

## 8. Puntuación

| Categoría | Nota (1-10) | Comentario |
|-----------|-------------|------------|
| Funcionalidad | 9 | Cumple todos los objetivos planteados |
| Calidad de código | 8 | Limpio, consistente, bien estructurado |
| Tests | 9 | 151 tests, bien diseñados, cobertura de 3 módulos |
| Documentación | 9 | README exhaustivo, deuda técnica documentada |
| Robustez | 8 | Reconexión automática, backoff, manejo de errores |
| Seguridad | 8 | Escape de strings, credenciales en .env |
| Mantenibilidad | 8 | Config externalizada, código modular |
| **Promedio** | **8.4** | **Solución de alta calidad** |

---

## Conclusión

La solución está **lista para uso en producción** dentro de su contexto (automatización personal). Los 17 ítems de deuda técnica han sido evaluados y resueltos/descartados con justificación. El refactoring anti-detección (6 fases) ha sido completado, resultando en una arquitectura modular de 3 capas con 151 tests pasando al 100%. El código es mantenible y configurable.

**Recomendaciones para evolución futura:**
1. Configurar `texto_hay_citas` con el texto real que muestra el portal cuando hay citas disponibles.
2. Monitorizar cambios en los IDs del portal y actualizar `config.json` según sea necesario.
3. Considerar integración con servicio de CAPTCHA si el portal lo implementa.
