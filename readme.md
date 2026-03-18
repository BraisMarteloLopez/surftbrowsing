# Plan de trabajo: Bot cita previa extranjería — POLICÍA TARJETA CONFLICTO UCRANIA (Madrid)

**Fecha:** 18 de marzo de 2026
**Estado:** Pendiente de mapeo de IDs de elementos HTML

---

## 1. Objetivo

Automatizar el proceso de solicitud de cita previa en el portal ICP del gobierno español para el trámite "POLICÍA TARJETA CONFLICTO UCRANIA" en Madrid.

El bot navega el formulario completo en bucle hasta que detecta disponibilidad de cita. Cuando hay cita disponible, emite una alerta sonora y cede el control al usuario para completar manualmente los pasos finales (selección de hora y confirmación SMS).

---

## 2. Arquitectura

### Enfoque: Chrome DevTools Protocol (CDP) sobre navegador real

El script Python se conecta al navegador Brave del usuario mediante el protocolo CDP, que expone un canal WebSocket en `localhost:9222`.

A través de este canal, el script inyecta sentencias JavaScript directamente en el contexto de la página cargada. Estas sentencias operan sobre el DOM de la página usando los **IDs nativos de los elementos HTML** (inputs, selects, buttons) para:

- **Seleccionar opciones** en dropdowns (`document.getElementById('id').value = 'valor'`)
- **Rellenar campos de texto** (`document.getElementById('id').value = 'texto'`)
- **Hacer click en botones** (`document.getElementById('id').click()`)
- **Leer contenido de la página** para detectar mensajes como "no hay citas disponibles"

### Por qué IDs de elementos HTML como método de interacción

- **Robustez:** Los IDs son identificadores únicos dentro del DOM. A diferencia de XPaths o selectores CSS compuestos, no dependen de la estructura jerárquica de la página ni de clases CSS que pueden cambiar por motivos estéticos.
- **Simplicidad:** Una línea de JS por acción. No se necesitan frameworks ni librerías de scraping.
- **Mantenimiento:** Si el portal cambia un ID, el cambio es una edición de una línea en el archivo de configuración. No requiere modificar lógica del script.
- **Indetectable:** JavaScript ejecutado vía CDP en el contexto de la página es idéntico a JavaScript ejecutado desde la consola del navegador por un humano. No existe flag, header ni fingerprint que lo distinga de una interacción manual.

### Diferencia con Selenium/WebDriver

Selenium instancia un navegador controlado mediante el protocolo WebDriver, que inyecta flags detectables (`navigator.webdriver = true`) y genera un fingerprint artificial. El portal ICP detecta y bloquea este patrón activamente (confirmado por múltiples repositorios y usuarios).

CDP sobre un navegador real no tiene este problema. El navegador es la instalación normal del usuario, con su perfil, cookies e historial. CDP es un canal lateral de comunicación, no una inyección en el navegador.

---

## 3. Flujo detallado del bot

### PASO 0 — Lanzamiento de Brave (manual, una sola vez)

El usuario abre Brave desde línea de comandos con el flag de depuración remota:

```
brave.exe --remote-debugging-port=9222
```

Brave se abre normalmente. El flag solo habilita el puerto WebSocket de CDP.

### PASO 1 — Conexión del script Python

```
python cita_bot.py
```

El script se conecta al WebSocket de Brave en `localhost:9222`. Si Brave no está abierto o no tiene el flag, el script muestra un error descriptivo y se cierra.

### PASO 2 — Navegación a la URL de inicio

El script navega automáticamente a la URL de inicio del portal ICP.
Espera a que la página cargue completamente antes de continuar.

> **PENDIENTE:** URL exacta de inicio del portal.

### PASO 3 — Formulario 1: Selección de provincia

Acciones JS ejecutadas por el script:

1. Seleccionar "Madrid" en el dropdown de provincia → `getElementById('ID_DROPDOWN_PROVINCIA').value = 'VALOR_MADRID'`
2. Click en botón "Aceptar" → `getElementById('ID_BOTON_ACEPTAR_F1').click()`
3. Esperar carga de la siguiente página

> **PENDIENTE:** ID del dropdown de provincia, valor de la opción "Madrid", ID del botón Aceptar.

### PASO 4 — Formulario 2: Selección de oficina y trámite

Acciones JS ejecutadas por el script:

1. No se toca el dropdown de oficina (se deja la opción por defecto "cualquier oficina")
2. Seleccionar trámite → `getElementById('ID_DROPDOWN_TRAMITE').value = '4112'`
3. Click en botón "Aceptar" → `getElementById('ID_BOTON_ACEPTAR_F2').click()`
4. Esperar carga de la siguiente página

> **PENDIENTE:** ID del dropdown de trámite, ID del botón Aceptar.

### PASO 5 — Formulario 3: Aviso informativo

Acciones JS ejecutadas por el script:

1. Click en botón "Aceptar" → `getElementById('ID_BOTON_ACEPTAR_F3').click()`
2. Esperar carga de la siguiente página

> **PENDIENTE:** ID del botón Aceptar.

### PASO 6 — Formulario 4: Datos personales

Acciones JS ejecutadas por el script:

1. Rellenar campo NIE → `getElementById('ID_INPUT_NIE').value = 'X1234567A'`
2. Rellenar campo Nombre y Apellidos → `getElementById('ID_INPUT_NOMBRE').value = 'NOMBRE APELLIDO1 APELLIDO2'`
3. Click en botón "Aceptar" → `getElementById('ID_BOTON_ACEPTAR_F4').click()`
4. Esperar carga de la siguiente página

> **PENDIENTE:** ID del input NIE, ID del input Nombre, ID del botón Aceptar.

### PASO 7 — Formulario 5: Solicitar cita

Acciones JS ejecutadas por el script:

1. Click en botón "Solicitar cita" → `getElementById('ID_BOTON_SOLICITAR').click()`
2. Esperar carga de la respuesta

> **PENDIENTE:** ID del botón "Solicitar cita".

### PASO 8 — Comprobación de disponibilidad

El script busca en el contenido de la página el texto de "no hay citas disponibles".

- **Si encuentra el mensaje:** No hay cita. El script espera el intervalo configurado (por defecto 60 segundos) y vuelve al PASO 2 para repetir el proceso completo.
- **Si NO encuentra el mensaje:** Hay cita disponible (o algo inesperado). El script emite un sonido de alerta, imprime un mensaje en consola, y NO hace nada más. El usuario toma el control del navegador y continúa manualmente.

> **PENDIENTE:** Texto exacto del mensaje "no hay citas disponibles".

---

## 4. Archivo de configuración (config.json)

```json
{
    "url_inicio": "PENDIENTE",
    "nie": "PENDIENTE",
    "nombre": "PENDIENTE",
    "intervalo_reintento_segundos": 60,
    "ids": {
        "dropdown_provincia": "PENDIENTE",
        "valor_madrid": "PENDIENTE",
        "boton_aceptar_f1": "PENDIENTE",
        "dropdown_tramite": "PENDIENTE",
        "valor_tramite": "4112",
        "boton_aceptar_f2": "PENDIENTE",
        "boton_aceptar_f3": "PENDIENTE",
        "input_nie": "PENDIENTE",
        "input_nombre": "PENDIENTE",
        "boton_aceptar_f4": "PENDIENTE",
        "boton_solicitar_cita": "PENDIENTE",
        "texto_no_hay_citas": "PENDIENTE"
    }
}
```

Los IDs se externalizan en configuración para que si el portal cambia un ID, la corrección sea editar una línea del JSON sin tocar el código Python.

---

## 5. Dependencias técnicas

- **Python 3.10+**
- **Librería `websockets`** (pip install websockets) — para la conexión CDP
- **Brave** (o Chrome/Edge) instalado normalmente en Windows
- Ninguna otra dependencia

---

## 6. Riesgos y limitaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| El portal cambia los IDs de los elementos | Media | IDs externalizados en config.json; corrección inmediata |
| El portal detecta el patrón de navegación repetida (misma IP, mismo flujo) | Baja-media | Intervalo configurable entre reintentos; no hay fingerprint artificial |
| El portal añade CAPTCHA en algún paso | Baja | El bot se detiene y el usuario resuelve manualmente |
| Brave cierra o pierde conexión | Baja | El script detecta la desconexión y muestra error |
| La página tarda más de lo esperado en cargar | Media | Timeouts configurables por paso |

---

## 7. Lo que este bot NO hace

- No resuelve CAPTCHAs
- No introduce el código SMS (el usuario lo hace manualmente)
- No selecciona hora de cita (el usuario lo hace manualmente)
- No corre 24/7 sin supervisión (requiere que el PC esté encendido y Brave abierto)
- No usa proxies, VPNs ni rotación de IP

---

## 8. Próximo paso

Recopilar los IDs de los elementos HTML de cada formulario. El usuario navega el portal con DevTools (F12) abiertas, inspecciona cada elemento interactivo, y proporciona el ID (atributo `id=""` del elemento HTML).

Elementos pendientes por formulario:

- **Formulario 1:** ID dropdown provincia, valor opción Madrid, ID botón Aceptar
- **Formulario 2:** ID dropdown trámite, ID botón Aceptar
- **Formulario 3:** ID botón Aceptar
- **Formulario 4:** ID input NIE, ID input Nombre, ID botón Aceptar
- **Formulario 5:** ID botón Solicitar cita
- **General:** URL de inicio, texto exacto del mensaje "no hay citas"
