# Plan de Desarrollo — cita_bot

## Fase 0: Información necesaria del usuario

Antes de implementar, necesito que el usuario proporcione:

### Bloque A — Portal (inspección con F12)

1. **URL de inicio** del portal ICP (la primera página que carga el formulario)
2. **IDs de elementos HTML** por formulario:

   **Formulario 1 (provincia):**
   - ID del dropdown de provincia
   - Valor de la opción "Madrid" dentro de ese dropdown
   - ID del botón "Aceptar"

   **Formulario 2 (oficina y trámite):**
   - ID del dropdown de trámite
   - ID del botón "Aceptar"

   **Formulario 3 (aviso informativo):**
   - ID del botón "Aceptar"

   **Formulario 4 (datos personales):**
   - ID del input NIE
   - ID del input Nombre
   - ID del botón "Aceptar"

   **Formulario 5 (solicitar cita):**
   - ID del botón "Solicitar cita"

   **Página sin citas:**
   - ID del botón "Aceptar" (el que devuelve al inicio)
   - Texto exacto del mensaje "no hay citas disponibles" (copiar literal)

3. **¿La página usa IDs estáticos o dinámicos?** (si cambian cada vez que recargas, hay que usar otro selector)

### Bloque B — Datos personales

4. NIE del usuario (ej: X1234567A)
5. Nombre completo tal como aparece en el formulario

### Bloque C — Preferencias

6. ¿Intervalo de reintento deseado? (default: 60s)
7. ¿Delay entre acciones? (default: 1.0s)
8. ¿Método de alerta sonora preferido? Opciones:
   - `winsound.Beep` (solo Windows, sin dependencias extra)
   - `playsound` (multiplataforma, requiere `pip install playsound`)
   - Print en consola + beep del sistema (`\a`)

---

## Fase 1: Estructura base y config.json

**Archivos:** `config.json`, `cita_bot.py` (esqueleto)

**Tareas:**
- Crear `config.json` con los valores proporcionados por el usuario (o placeholders si aún no los tiene)
- Crear esqueleto de `cita_bot.py` con:
  - Carga de config.json
  - Logging con formato timestamp + número de intento
  - Estructura main con manejo de Ctrl+C

**Sin dependencias externas en esta fase.**

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
| `config.json` | 1 | Configuración externalizada |
| `cita_bot.py` | 1-5 | Script principal del bot |
