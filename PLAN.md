# Plan de Desarrollo — cita_bot

## Fase 0: Información necesaria del usuario

Antes de implementar, necesito que el usuario proporcione:

### Bloque A — Portal (inspección con F12)

1. **URL de inicio:** ✅ `https://icp.administracionelectronica.gob.es/icpplus/index.html`
2. **IDs de elementos HTML** por formulario:

   **Formulario 1 (provincia):** ✅ COMPLETADO
   - ID del dropdown de provincia: `form`
   - Valor de la opción "Madrid": `/icpplustiem/citar?p=28&locale=es`
   - ID del botón "Aceptar": `btnAceptar` (onclick llama a `envia()`)

   **Formulario 2 (oficina y trámite):** ✅ COMPLETADO
   - ID del dropdown de trámite: `tramiteGrupo[0]` (onchange llama a `eliminarSeleccionOtrosGrupos(0);cargaMensajesTramite()`)
   - Valor del trámite: `4112` (POLICÍA TARJETA CONFLICTO UCRANIA)
   - ID del botón "Aceptar": `btnAceptar` (onclick llama a `envia()`)

   **Formulario 3 (aviso informativo):** ✅ COMPLETADO
   - ID del botón "Entrar": `btnEntrar` (onclick llama a `document.forms[0].submit()`)

   **Formulario 4 (datos personales):** ✅ COMPLETADO
   - ID del input NIE: `txtIdCitado` (maxlength 9)
   - ID del input Nombre: `txtDesCitado` (onchange llama a `comprobarDatos()`)
   - ID del botón "Aceptar": `btnEnviar` (onclick llama a `envia()`)

   **Formulario 5 (solicitar cita):** ✅ COMPLETADO
   - ID del botón "Solicitar Cita": `btnEnviar` (onclick llama a `enviar('solicitud')`)

   **Página sin citas:** ✅ COMPLETADO
   - ID del botón "Salir": `btnSalir` (onclick llama a `goAc_opc_direct()`)
   - Texto exacto: `En este momento no hay citas disponibles.`
   - Contenedor: `<div class="mf-main--content ac-custom-content">`

3. **¿La página usa IDs estáticos o dinámicos?** (si cambian cada vez que recargas, hay que usar otro selector)

### Bloque B — Datos personales y preferencias → archivo `.env`

El usuario configura sus datos y preferencias en un archivo `.env` (no se sube al repo):

```env
NIE=X1234567A
NOMBRE=NOMBRE APELLIDO1 APELLIDO2
INTERVALO_REINTENTO_SEGUNDOS=60
DELAY_ENTRE_ACCIONES_SEGUNDOS=1.0
TIMEOUT_CARGA_PAGINA_SEGUNDOS=15
```

- `NIE` y `NOMBRE` son obligatorios. El script valida al arrancar.
- Los parámetros de cadencia son opcionales (tienen valores por defecto).
- Dependencia adicional: `python-dotenv` para leer el `.env`.

---

## Fase 1: Estructura base, config.json y .env

**Archivos:** `config.json`, `.env.example`, `.gitignore`, `cita_bot.py` (esqueleto)

**Tareas:**
- Crear `config.json` con URL de inicio e IDs de elementos HTML
- Crear `.env.example` con plantilla de variables (NIE, NOMBRE, cadencia)
- Crear/actualizar `.gitignore` para excluir `.env`
- Crear esqueleto de `cita_bot.py` con:
  - Carga de `.env` con `python-dotenv`
  - Carga de `config.json` para IDs
  - Validación de variables obligatorias (NIE, NOMBRE)
  - Logging con formato timestamp + número de intento
  - Estructura main con manejo de Ctrl+C

---

## Fase 2: Conexión CDP

**Tareas:**
- Función para descubrir el WebSocket de Brave via `http://localhost:9222/json`
- Función para conectar al WebSocket con `websockets`
- Función helper para ejecutar JS en la página (`Runtime.evaluate`)
- Función helper para navegar a una URL (`Page.navigate`) y esperar carga (`Page.loadEventFired`)
- Manejo de errores de conexión (Brave no abierto, puerto no disponible)

**Resultado:** Se puede conectar a Brave y ejecutar JS arbitrario en la página.

---

## Fase 3: Navegación de formularios

**Tareas:**
- Implementar funciones por cada paso del flujo:
  - `paso_formulario_1()` — seleccionar provincia + aceptar
  - `paso_formulario_2()` — seleccionar trámite + aceptar
  - `paso_formulario_3()` — aceptar aviso
  - `paso_formulario_4()` — rellenar NIE y nombre + aceptar
  - `paso_formulario_5()` — solicitar cita
- Cada función:
  - Espera `delay_entre_acciones_segundos` entre cada interacción
  - Usa `getElementById` + `dispatchEvent` según la especificación
  - Espera carga de página después de cada click en "Aceptar"
  - Valida que el elemento existe antes de interactuar (si no existe → error descriptivo)

**Resultado:** El bot puede completar un ciclo completo de 5 formularios.

---

## Fase 4: Detección de disponibilidad y alerta

**Tareas:**
- Leer el contenido de la página después del paso 5
- Buscar el texto exacto de "no hay citas"
- **Si no hay cita:**
  - Log del resultado
  - Esperar `intervalo_reintento_segundos`
  - Click en botón Aceptar de la página sin citas
  - Volver al paso 3 (inicio del bucle)
- **Si hay cita:**
  - Log destacado con timestamp
  - Alerta sonora en bucle
  - Bucle de keep-alive (leer elemento del DOM cada 30s para mantener sesión)
  - No tocar nada en la página

**Resultado:** Bot funcional en bucle completo.

---

## Fase 5: Manejo de estados inesperados

**Tareas:**
- Detectar errores del servidor (500, 503) → reintentar tras espera
- Detectar sesión expirada → reiniciar desde paso 2
- Timeout configurable por carga de página → reiniciar desde paso 2
- Elemento no encontrado → log del ID que falta + detener script
- CAPTCHA inesperado → alerta sonora + detener script
- Cualquier estado no reconocido → log + alerta + detener

**Resultado:** Bot robusto que no se queda colgado en ningún escenario.

---

## Fase 6: Testing manual y ajustes

**Tareas:**
- El usuario ejecuta el bot contra el portal real
- Verificar que cada formulario se completa correctamente
- Ajustar delays si el portal es lento
- Verificar que los eventos `dispatchEvent` activan las dependencias del formulario
- Confirmar que la alerta sonora funciona

**Resultado:** Bot listo para uso en producción.

---

## Resumen de archivos a crear

| Archivo | Fase | Descripción |
|---------|------|-------------|
| `config.json` | 1 | URL de inicio + IDs de elementos HTML |
| `.env.example` | 1 | Plantilla para que el usuario cree su `.env` |
| `.gitignore` | 1 | Excluye `.env` del repositorio |
| `cita_bot.py` | 1-5 | Script principal del bot |
