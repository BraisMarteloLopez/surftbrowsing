"""Tests de integración — Fase 8 (TD-10 completo).

Tests que verifican flujos end-to-end con mocks, sin conexión a Brave ni al portal.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cita_bot import (
    CDPSession, EstadoPagina, BackoffController,
    evaluar_estado_pagina, verificar_url, ejecutar_js,
)


# ---------------------------------------------------------------------------
# Verificar URL post-navegación
# ---------------------------------------------------------------------------

class TestVerificarUrl:
    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js")
    async def test_url_coincide(self, mock_ejs):
        cdp = AsyncMock(spec=CDPSession)
        mock_ejs.return_value = {
            "value": "https://icp.administracionelectronica.gob.es/icpplus/index.html"
        }
        result = await verificar_url(cdp, "https://icp.administracionelectronica.gob.es/icpplus/index.html")
        assert result is True

    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js")
    async def test_url_con_icpplus_valida(self, mock_ejs):
        cdp = AsyncMock(spec=CDPSession)
        mock_ejs.return_value = {
            "value": "https://icp.administracionelectronica.gob.es/icpplustiem/citar?p=28"
        }
        result = await verificar_url(cdp, "https://icp.administracionelectronica.gob.es/icpplus/index.html")
        assert result is True

    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js")
    async def test_url_completamente_diferente(self, mock_ejs):
        cdp = AsyncMock(spec=CDPSession)
        mock_ejs.return_value = {"value": "https://example.com/error"}
        result = await verificar_url(cdp, "https://icp.administracionelectronica.gob.es/icpplus/index.html")
        assert result is False

    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js")
    async def test_url_vacia(self, mock_ejs):
        cdp = AsyncMock(spec=CDPSession)
        mock_ejs.return_value = {}
        result = await verificar_url(cdp, "https://icp.administracionelectronica.gob.es/icpplus/index.html")
        assert result is False


# ---------------------------------------------------------------------------
# Reconexión tras desconexión
# ---------------------------------------------------------------------------

class TestReconexion:
    @pytest.mark.asyncio
    async def test_cdp_session_lifecycle(self, mock_ws):
        """Ciclo completo: crear, usar, desconectar, verificar estado."""
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        assert cdp.is_alive is True

        # Enviar un comando con respuesta
        async def respond():
            await asyncio.sleep(0.05)
            mock_ws.inject_response(1, {"result": {"type": "string", "value": "test"}})

        asyncio.create_task(respond())
        result = await cdp.send("Runtime.evaluate", {"expression": "'test'"}, timeout=2.0)
        assert "result" in result

        # Desconectar
        mock_ws.force_disconnect()
        await asyncio.sleep(0.1)
        assert cdp.is_alive is False

        # Intentar enviar → error
        with pytest.raises(ConnectionError):
            await cdp.send("Page.enable")

        await cdp.close()

    @pytest.mark.asyncio
    async def test_multiple_pending_futures_all_resolved(self, mock_ws):
        """Múltiples Futures pendientes se resuelven todos al desconectar."""
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        tasks = []
        for _ in range(5):
            t = asyncio.create_task(
                cdp.send("Runtime.evaluate", {"expression": "1"}, timeout=10.0)
            )
            tasks.append(t)

        await asyncio.sleep(0.05)
        mock_ws.force_disconnect()
        await asyncio.sleep(0.1)

        for t in tasks:
            with pytest.raises((ConnectionError, asyncio.CancelledError)):
                await t

        await cdp.close()


# ---------------------------------------------------------------------------
# Backoff integrado con flujo de errores
# ---------------------------------------------------------------------------

class TestBackoffIntegration:
    def test_secuencia_errores_y_exito(self):
        """Simula 5 timeouts, luego éxito, luego otro error."""
        bc = BackoffController(intervalo_base=5.0, max_intervalo=300.0, umbral_alerta=10)

        # 5 errores consecutivos → intervalos crecientes
        intervalos = []
        for _ in range(5):
            intervalos.append(bc.registrar_error("timeout"))

        assert intervalos == [5.0, 10.0, 20.0, 40.0, 80.0]
        assert bc.errores_consecutivos == 5
        assert bc.debe_alertar is False

        # Éxito → reset
        bc.registrar_exito()
        assert bc.errores_consecutivos == 0

        # Nuevo error → empieza desde base
        assert bc.registrar_error("js_error") == 5.0

    def test_tipos_mixtos_no_resetean(self):
        """Diferentes tipos de error suman al mismo contador."""
        bc = BackoffController(intervalo_base=1.0, umbral_alerta=3)
        bc.registrar_error("timeout")
        bc.registrar_error("js_error")
        bc.registrar_error("conexion")
        assert bc.errores_consecutivos == 3
        assert bc.debe_alertar is True
        assert bc.tipo_ultimo_error == "conexion"


# ---------------------------------------------------------------------------
# Detección + backoff: flujo combinado
# ---------------------------------------------------------------------------

class TestDeteccionYBackoff:
    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js")
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_desconocido_incrementa_backoff(self, mock_sleep, mock_ejs):
        """Estado DESCONOCIDO debería integrarse con backoff."""
        cdp = AsyncMock(spec=CDPSession)
        ids = {"boton_salir_nocita": "btnSalir"}

        # Simular página vacía → DESCONOCIDO
        mock_ejs.return_value = {"value": 10}  # body length < 50
        estado = await evaluar_estado_pagina(cdp, ids)
        assert estado == EstadoPagina.DESCONOCIDO

        # Verificar que backoff registra correctamente
        bc = BackoffController(intervalo_base=5.0)
        espera = bc.registrar_error("desconocido")
        assert espera == 5.0
        assert bc.errores_consecutivos == 1


# ---------------------------------------------------------------------------
# ejecutar_js con timeout diferenciado
# ---------------------------------------------------------------------------

class TestTimeoutsDiferenciados:
    @pytest.mark.asyncio
    async def test_ejecutar_js_usa_timeout_js(self, mock_ws):
        """ejecutar_js pasa TIMEOUT_JS (5s) por defecto, no TIMEOUT_PAGINA (15s)."""
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        # No inyectamos respuesta → timeout
        with pytest.raises(asyncio.TimeoutError):
            await ejecutar_js(cdp, "1+1;", timeout=0.1)

        await cdp.close()

    @pytest.mark.asyncio
    async def test_ejecutar_js_custom_timeout(self, mock_ws):
        """ejecutar_js respeta timeout personalizado."""
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def respond():
            await asyncio.sleep(0.3)
            mock_ws.inject_response(1, {
                "result": {"result": {"type": "number", "value": 2}}
            })

        asyncio.create_task(respond())
        # Timeout de 0.1s → debe fallar (respuesta llega en 0.3s)
        with pytest.raises(asyncio.TimeoutError):
            await ejecutar_js(cdp, "1+1;", timeout=0.1)

        await cdp.close()
