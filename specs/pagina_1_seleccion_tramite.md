# Especificación — Página 1: Selección de Trámite

**Estado:** Implementada
**Archivo destino:** `humano.py` → `async def fase_1()`

---

## Resumen

Segunda página del formulario ICP. Contiene un `<select>` de trámite y un botón "Aceptar".
El objetivo es seleccionar el trámite que empieza por "POLICIA TARJETA CONFLICTO UKRANIA" y avanzar.

**Elementos HTML objetivo:**

| Elemento | Selector | Tipo |
|----------|----------|------|
| Desplegable trámite | `<select id="tramiteGrupo[0]" onchange="eliminarSeleccionOtrosGrupos(0);cargaMensajesTramite()">` | `<select>` nativo |
| Botón aceptar | `<input id="btnAceptar" onclick="envia()">` | `<input type="button">` |

**Valor a seleccionar:** La opción cuyo `textContent` empieza por `"POLICIA TARJETA CONFLICTO UKRANIA"` (match por prefijo, `startsWith`).

**Nota CSS:** El ID `tramiteGrupo[0]` contiene corchetes. Se usa `CSS.escape()` o escape manual (`\[`, `\]`) para `querySelector`. En JS se usa `getElementById` directamente.

---

## Flujo de entrada

Siempre llegamos desde fase_0 (envío del formulario). No hay navegación.

---

## Secuencia de micro-acciones

### PASO 1 — Espera de carga + seguridad

```
1a. ESPERA OBLIGATORIA: waitForElement del dropdown trámite
1b. SEGURIDAD: detectar_waf()
```

### PASO 2 — Aterrizaje + scroll obligatorio

```
2a. DELAY: pausa de orientación (mismos rangos que fase_0)
2b. ACCIÓN: micro-movimientos de ratón
2c. ACCIÓN OBLIGATORIA: scroll pequeño (la página es más grande)
    - Distancia: uniform(F1_SCROLL_INICIAL_DIST_MIN, F1_SCROLL_INICIAL_DIST_MAX)
    - Default: 80-200px
```

### PASO 3 — Reconocimiento y apertura del desplegable trámite

Misma mecánica que fase_0 paso 3, pero con el selector del dropdown trámite.

### PASO 4 — Recorrido humano del desplegable

Misma mecánica errática que fase_0 paso 4 (ArrowDown exploratorio + navegación).

**Diferencia clave:** match por prefijo (`startsWith("POLICIA TARJETA CONFLICTO UKRANIA")`) en vez de igualdad exacta.

### PASO 5 — Transición hacia el botón

Idéntico a fase_0 paso 5.

### PASO 6 — Envío (click en "Aceptar")

Idéntico a fase_0 paso 6.

### PASO 7 — Espera de carga

Idéntico a fase_0 paso 7, con movimientos idle durante espera.

---

## Variables .env específicas de Página 1

```env
F1_SCROLL_INICIAL_DIST_MIN=80
F1_SCROLL_INICIAL_DIST_MAX=200
```

El resto de variables (ATERRIZAJE_*, DESPLEGABLE_*, TRANSICION_*, ENVIO_*) se comparten con todas las fases.

---

## Configuración en config.json

```json
{
  "ids": {
    "dropdown_tramite": "tramiteGrupo[0]",
    "valor_tramite": "4112",
    "boton_aceptar_f2": "btnAceptar"
  },
  "tramite_prefijo": "POLICIA TARJETA CONFLICTO UKRANIA"
}
```
