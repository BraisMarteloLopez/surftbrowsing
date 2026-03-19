"""Tests para funciones de navegación y formularios — Fase 8."""

import asyncio
from unittest.mock import AsyncMock, patch, call

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cita_bot import (
    CDPSession, EstadoPagina,
    navegar, click_y_esperar_carga, scroll_humano, verificar_url,
    click_salir, delay,
    paso_formulario_1, paso_formulario_2, paso_formulario_3,
    paso_formulario_4, paso_formulario_5,
    ciclo_completo, evaluar_estado_pagina,
    safe_js_string, ejecutar_js, intervalo_con_jitter,
)


@pytest.fixture
def ids():
    return {
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
        "boton_salir_nocita": "btnSalir",
        "texto_no_hay_citas": "En este momento no hay citas disponibles.",
    }


# ---------------------------------------------------------------------------
# aplicar_zoom
# ---------------------------------------------------------------------------

class TestScrollHumano:
    @pytest.mark.asyncio
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    async def test_scroll_ejecuta_n_pasos(self, mock_ejs, mock_sleep):
        cdp = AsyncMock(spec=CDPSession)
        await scroll_humano(cdp, pasos=3)
        assert mock_ejs.call_count == 3
        for call_args in mock_ejs.call_args_list:
            js_code = call_args[0][1]
            assert "scrollBy" in js_code
            assert "smooth" in js_code

    @pytest.mark.asyncio
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    async def test_scroll_pasos_default(self, mock_ejs, mock_sleep):
        cdp = AsyncMock(spec=CDPSession)
        await scroll_humano(cdp)
        assert mock_ejs.call_count == 3  # default pasos=3


# ---------------------------------------------------------------------------
# navegar
# ---------------------------------------------------------------------------

class TestNavegar:
    @pytest.mark.asyncio
    async def test_navegar_envia_comandos_correctos(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.pre_wait_event.return_value = asyncio.Future()
        cdp.pre_wait_event.return_value.set_result({"method": "Page.loadEventFired"})
        cdp.wait_future = AsyncMock()

        await navegar(cdp, "https://example.com")

        # Verifica Page.enable y Page.navigate
        calls = cdp.send.call_args_list
        assert any("Page.enable" in str(c) for c in calls)
        assert any("Page.navigate" in str(c) for c in calls)


# ---------------------------------------------------------------------------
# click_y_esperar_carga
# ---------------------------------------------------------------------------

class TestClickYEsperarCarga:
    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    async def test_click_y_carga_normal(self, mock_ejs):
        cdp = AsyncMock(spec=CDPSession)
        load_fut = asyncio.Future()
        load_fut.set_result({"method": "Page.loadEventFired"})
        cdp.pre_wait_event.return_value = load_fut
        cdp.wait_future = AsyncMock()

        await click_y_esperar_carga(cdp, "document.getElementById('btn').click();")
        mock_ejs.assert_called_once()

    @pytest.mark.asyncio
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    async def test_click_timeout_continua(self, mock_ejs):
        """Si wait_future da timeout, continúa sin error."""
        cdp = AsyncMock(spec=CDPSession)
        load_fut = asyncio.Future()
        cdp.pre_wait_event.return_value = load_fut
        cdp.wait_future = AsyncMock(side_effect=asyncio.TimeoutError)

        await click_y_esperar_carga(cdp, "btn.click();")
        # No lanza excepción


# ---------------------------------------------------------------------------
# click_salir
# ---------------------------------------------------------------------------

class TestClickSalir:
    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    async def test_click_salir_usa_safe_js(self, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await click_salir(cdp, ids)
        js_code = mock_click.call_args[0][1]
        assert "btnSalir" in js_code


# ---------------------------------------------------------------------------
# delay
# ---------------------------------------------------------------------------

class TestDelay:
    @pytest.mark.asyncio
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_delay_uses_delay_accion(self, mock_sleep):
        await delay()
        mock_sleep.assert_called_once()


# ---------------------------------------------------------------------------
# paso_formulario_1
# ---------------------------------------------------------------------------

class TestPasoFormulario1:
    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    @patch("cita_bot.delay", new_callable=AsyncMock)
    @patch("cita_bot.scroll_humano", new_callable=AsyncMock)
    async def test_formulario_1_selecciona_provincia(self, mock_scroll, mock_delay, mock_ejs, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await paso_formulario_1(cdp, ids)

        mock_scroll.assert_called_once()
        js_code = mock_ejs.call_args[0][1]
        assert "form" in js_code
        assert safe_js_string(ids["valor_madrid"]) in js_code
        click_js = mock_click.call_args[0][1]
        assert "btnAceptar" in click_js


# ---------------------------------------------------------------------------
# paso_formulario_2
# ---------------------------------------------------------------------------

class TestPasoFormulario2:
    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    @patch("cita_bot.delay", new_callable=AsyncMock)
    @patch("cita_bot.scroll_humano", new_callable=AsyncMock)
    async def test_formulario_2_selecciona_tramite(self, mock_scroll, mock_delay, mock_ejs, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await paso_formulario_2(cdp, ids)

        mock_scroll.assert_called_once()
        js_code = mock_ejs.call_args[0][1]
        assert safe_js_string(ids["dropdown_tramite"]) in js_code
        assert "4112" in js_code


# ---------------------------------------------------------------------------
# paso_formulario_3
# ---------------------------------------------------------------------------

class TestPasoFormulario3:
    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    @patch("cita_bot.delay", new_callable=AsyncMock)
    @patch("cita_bot.scroll_humano", new_callable=AsyncMock)
    async def test_formulario_3_click_entrar(self, mock_scroll, mock_delay, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await paso_formulario_3(cdp, ids)

        mock_scroll.assert_called_once()
        click_js = mock_click.call_args[0][1]
        assert "btnEntrar" in click_js


# ---------------------------------------------------------------------------
# paso_formulario_4
# ---------------------------------------------------------------------------

class TestPasoFormulario4:
    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    @patch("cita_bot.delay", new_callable=AsyncMock)
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "JUAN GARCÍA")
    async def test_formulario_4_rellena_datos(self, mock_delay, mock_ejs, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await paso_formulario_4(cdp, ids)

        # 2 llamadas a ejecutar_js: NIE + Nombre
        assert mock_ejs.call_count == 2
        nie_js = mock_ejs.call_args_list[0][0][1]
        nombre_js = mock_ejs.call_args_list[1][0][1]
        assert "X1234567A" in nie_js
        assert "txtIdCitado" in nie_js
        assert "JUAN GARCÍA" in nombre_js
        assert "txtDesCitado" in nombre_js

    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    @patch("cita_bot.ejecutar_js", new_callable=AsyncMock)
    @patch("cita_bot.delay", new_callable=AsyncMock)
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "O'BRIEN TEST")
    async def test_formulario_4_escapa_nombre_con_comilla(self, mock_delay, mock_ejs, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await paso_formulario_4(cdp, ids)

        nombre_js = mock_ejs.call_args_list[1][0][1]
        assert "O\\'BRIEN TEST" in nombre_js


# ---------------------------------------------------------------------------
# paso_formulario_5
# ---------------------------------------------------------------------------

class TestPasoFormulario5:
    @pytest.mark.asyncio
    @patch("cita_bot.click_y_esperar_carga", new_callable=AsyncMock)
    @patch("cita_bot.delay", new_callable=AsyncMock)
    async def test_formulario_5_solicita_cita(self, mock_delay, mock_click, ids):
        cdp = AsyncMock(spec=CDPSession)
        await paso_formulario_5(cdp, ids)

        click_js = mock_click.call_args[0][1]
        assert "btnEnviar" in click_js


# ---------------------------------------------------------------------------
# ciclo_completo
# ---------------------------------------------------------------------------

class TestCicloCompleto:
    @pytest.mark.asyncio
    @patch("cita_bot.evaluar_estado_pagina", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_5", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_4", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_3", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_2", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_1", new_callable=AsyncMock)
    async def test_ciclo_completo_5_pasos(self, f1, f2, f3, f4, f5, mock_eval, ids):
        cdp = AsyncMock(spec=CDPSession)
        mock_eval.return_value = EstadoPagina.NO_HAY_CITAS

        result = await ciclo_completo(cdp, ids, paso_hasta=5)

        assert result == EstadoPagina.NO_HAY_CITAS
        f1.assert_called_once()
        f2.assert_called_once()
        f3.assert_called_once()
        f4.assert_called_once()
        f5.assert_called_once()
        mock_eval.assert_called_once()

    @pytest.mark.asyncio
    @patch("cita_bot.paso_formulario_3", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_2", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_1", new_callable=AsyncMock)
    async def test_ciclo_modo_depuracion(self, f1, f2, f3, ids):
        cdp = AsyncMock(spec=CDPSession)

        result = await ciclo_completo(cdp, ids, paso_hasta=3)

        assert result is None
        f1.assert_called_once()
        f2.assert_called_once()
        f3.assert_called_once()

    @pytest.mark.asyncio
    @patch("cita_bot.evaluar_estado_pagina", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_5", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_4", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_3", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_2", new_callable=AsyncMock)
    @patch("cita_bot.paso_formulario_1", new_callable=AsyncMock)
    async def test_ciclo_hay_citas(self, f1, f2, f3, f4, f5, mock_eval, ids):
        cdp = AsyncMock(spec=CDPSession)
        mock_eval.return_value = EstadoPagina.HAY_CITAS

        result = await ciclo_completo(cdp, ids, paso_hasta=5)
        assert result == EstadoPagina.HAY_CITAS


# ---------------------------------------------------------------------------
# mantener_sesion
# ---------------------------------------------------------------------------

class TestIntervaloConJitter:
    def test_jitter_rango(self):
        """El jitter produce valores dentro de ±15% del base."""
        base = 100.0
        for _ in range(100):
            resultado = intervalo_con_jitter(base)
            assert 85.0 <= resultado <= 115.0

    def test_jitter_no_es_constante(self):
        """El jitter produce valores diferentes (no siempre el mismo)."""
        base = 60.0
        resultados = {intervalo_con_jitter(base) for _ in range(20)}
        assert len(resultados) > 1


# ---------------------------------------------------------------------------
# ejecutar_js
# ---------------------------------------------------------------------------

class TestEjecutarJs:
    @pytest.mark.asyncio
    async def test_ejecutar_js_exception_details(self, mock_ws):
        """ejecutar_js lanza RuntimeError si hay exceptionDetails."""
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def respond():
            await asyncio.sleep(0.05)
            # inject_response wraps in {"id": N, "result": ...}
            # ejecutar_js does result.get("result", {}) on the CDP response
            mock_ws.inject_response(1, {
                "result": {"type": "undefined"},
                "exceptionDetails": {"text": "SyntaxError"},
            })

        asyncio.create_task(respond())
        with pytest.raises(RuntimeError, match="Error JS"):
            await ejecutar_js(cdp, "invalid{{{", timeout=2.0)
        await cdp.close()

    @pytest.mark.asyncio
    async def test_ejecutar_js_devuelve_valor(self, mock_ws):
        """ejecutar_js devuelve el result.result correctamente."""
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def respond():
            await asyncio.sleep(0.05)
            mock_ws.inject_response(1, {
                "result": {"type": "number", "value": 42},
            })

        asyncio.create_task(respond())
        result = await ejecutar_js(cdp, "21 * 2;", timeout=2.0)
        assert result == {"type": "number", "value": 42}
        await cdp.close()
