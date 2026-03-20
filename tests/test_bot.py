"""Tests exhaustivos para bot.py — BackoffController, limpiar_datos, utilidades."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_core import CDPSession, TIMEOUT_JS
from bot import BackoffController, intervalo_con_jitter, limpiar_datos_navegador


# =========================================================================
# BackoffController
# =========================================================================

class TestBackoffController:
    def test_primer_error_devuelve_intervalo_base(self):
        bc = BackoffController(intervalo_base=5.0)
        espera = bc.registrar_error("test")
        assert espera == 5.0

    def test_backoff_exponencial(self):
        bc = BackoffController(intervalo_base=5.0, max_intervalo=300.0)
        assert bc.registrar_error("e1") == 5.0    # 5 * 2^0
        assert bc.registrar_error("e2") == 10.0   # 5 * 2^1
        assert bc.registrar_error("e3") == 20.0   # 5 * 2^2
        assert bc.registrar_error("e4") == 40.0   # 5 * 2^3

    def test_no_excede_max_intervalo(self):
        bc = BackoffController(intervalo_base=100.0, max_intervalo=300.0)
        bc.registrar_error("e1")  # 100
        bc.registrar_error("e2")  # 200
        espera = bc.registrar_error("e3")  # 400 → capped to 300
        assert espera == 300.0

    def test_registrar_exito_resetea_contadores(self):
        bc = BackoffController(intervalo_base=5.0)
        bc.registrar_error("e1")
        bc.registrar_error("e2")
        assert bc.errores_consecutivos == 2

        bc.registrar_exito()
        assert bc.errores_consecutivos == 0

        # Tras reset, vuelve al intervalo base
        espera = bc.registrar_error("e3")
        assert espera == 5.0

    def test_errores_consecutivos(self):
        bc = BackoffController()
        assert bc.errores_consecutivos == 0
        bc.registrar_error("x")
        assert bc.errores_consecutivos == 1
        bc.registrar_error("y")
        assert bc.errores_consecutivos == 2

    def test_debe_alertar_bajo_umbral(self):
        bc = BackoffController(umbral_alerta=3)
        bc.registrar_error("e1")
        bc.registrar_error("e2")
        assert bc.debe_alertar is False

    def test_debe_alertar_en_umbral(self):
        bc = BackoffController(umbral_alerta=3)
        bc.registrar_error("e1")
        bc.registrar_error("e2")
        bc.registrar_error("e3")
        assert bc.debe_alertar is True

    def test_debe_alertar_sobre_umbral(self):
        bc = BackoffController(umbral_alerta=2)
        bc.registrar_error("e1")
        bc.registrar_error("e2")
        bc.registrar_error("e3")
        assert bc.debe_alertar is True

    def test_exito_desactiva_alerta(self):
        bc = BackoffController(umbral_alerta=1)
        bc.registrar_error("e1")
        assert bc.debe_alertar is True
        bc.registrar_exito()
        assert bc.debe_alertar is False

    def test_defaults_razonables(self):
        bc = BackoffController()
        assert bc.intervalo_base == 5.0
        assert bc.max_intervalo == 300.0
        assert bc.umbral_alerta == 10


# =========================================================================
# intervalo_con_jitter
# =========================================================================

class TestIntervaloConJitter:
    def test_jitter_dentro_de_rango(self):
        for _ in range(200):
            resultado = intervalo_con_jitter(120.0)
            assert 120 * 0.84 <= resultado <= 120 * 1.16  # un poco de tolerancia

    def test_jitter_con_base_cero(self):
        assert intervalo_con_jitter(0.0) == 0.0

    def test_jitter_variabilidad(self):
        """Verificar que no siempre devuelve el mismo valor."""
        resultados = set()
        for _ in range(50):
            resultados.add(round(intervalo_con_jitter(100.0), 2))
        assert len(resultados) > 1


# =========================================================================
# limpiar_datos_navegador
# =========================================================================

class TestLimpiarDatosNavegador:
    @pytest.mark.asyncio
    async def test_envia_storage_clear(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        await limpiar_datos_navegador(
            cdp, "https://icp.administracionelectronica.gob.es/icpplus/index.html"
        )

        calls = cdp.send.call_args_list
        storage_calls = [c for c in calls if c[0][0] == "Storage.clearDataForOrigin"]
        assert len(storage_calls) == 1
        assert "icp.administracionelectronica.gob.es" in storage_calls[0][0][1]["origin"]

    @pytest.mark.asyncio
    async def test_envia_network_clear_cache(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        await limpiar_datos_navegador(cdp, "https://example.com/path")

        calls = cdp.send.call_args_list
        methods = [c[0][0] for c in calls]
        assert "Network.enable" in methods
        assert "Network.clearBrowserCache" in methods

    @pytest.mark.asyncio
    async def test_no_crashea_si_storage_falla(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=Exception("storage error"))

        # No debería lanzar excepción
        await limpiar_datos_navegador(cdp, "https://example.com")

    @pytest.mark.asyncio
    async def test_origin_limpio_sin_path(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        await limpiar_datos_navegador(cdp, "https://example.com/deep/path?q=1")

        calls = cdp.send.call_args_list
        storage_calls = [c for c in calls if c[0][0] == "Storage.clearDataForOrigin"]
        # Origin debe ser solo scheme://netloc, sin path ni query
        assert storage_calls[0][0][1]["origin"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_no_incluye_cookies(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        await limpiar_datos_navegador(cdp, "https://example.com")

        calls = cdp.send.call_args_list
        storage_calls = [c for c in calls if c[0][0] == "Storage.clearDataForOrigin"]
        storage_types = storage_calls[0][0][1]["storageTypes"]
        assert "cookies" not in storage_types
