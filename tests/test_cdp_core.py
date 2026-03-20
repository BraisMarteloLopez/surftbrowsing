"""Tests exhaustivos para cdp_core.py — CDPSession, esperas, WAF, utilidades."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_core import (
    CDPSession, ejecutar_js, safe_js_string, obtener_ws_url,
    esperar_elemento, esperar_carga_pagina, detectar_waf,
    WafBanError, ElementoNoEncontrado, TimeoutCargaPagina,
    log_info, TIMEOUT_JS,
)


# =========================================================================
# safe_js_string
# =========================================================================

class TestSafeJsString:
    def test_escapa_comilla_simple(self):
        assert safe_js_string("it's") == "it\\'s"

    def test_escapa_backslash(self):
        assert safe_js_string("a\\b") == "a\\\\b"

    def test_escapa_newline(self):
        assert safe_js_string("a\nb") == "a\\nb"

    def test_escapa_carriage_return(self):
        assert safe_js_string("a\rb") == "a\\rb"

    def test_escapa_tab(self):
        assert safe_js_string("a\tb") == "a\\tb"

    def test_escapa_null(self):
        assert safe_js_string("a\0b") == "a\\0b"

    def test_string_sin_caracteres_especiales(self):
        assert safe_js_string("Madrid") == "Madrid"

    def test_string_vacio(self):
        assert safe_js_string("") == ""

    def test_multiples_caracteres_especiales(self):
        result = safe_js_string("it's a\nnew\\line")
        assert result == "it\\'s a\\nnew\\\\line"

    def test_selector_css_con_corchetes(self):
        # Los corchetes no se escapan — solo los caracteres peligrosos para JS strings
        assert safe_js_string("tramiteGrupo[0]") == "tramiteGrupo[0]"


# =========================================================================
# CDPSession — send/receive
# =========================================================================

class TestCDPSession:
    @pytest.mark.asyncio
    async def test_send_receive_happy_path(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def respond():
            await asyncio.sleep(0.02)
            mock_ws.inject_response(1, {"result": {"type": "string", "value": "ok"}})

        asyncio.create_task(respond())
        result = await cdp.send("Runtime.evaluate", {"expression": "1+1"}, timeout=2.0)
        assert result["id"] == 1
        assert result["result"]["result"]["value"] == "ok"
        await cdp.close()

    @pytest.mark.asyncio
    async def test_send_incrementa_id(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def respond_both():
            await asyncio.sleep(0.02)
            mock_ws.inject_response(1, {"result": {}})
            await asyncio.sleep(0.02)
            mock_ws.inject_response(2, {"result": {}})

        asyncio.create_task(respond_both())
        await cdp.send("Method1", timeout=2.0)
        await cdp.send("Method2", timeout=2.0)

        payloads = mock_ws.get_sent_payloads()
        assert payloads[0]["id"] == 1
        assert payloads[1]["id"] == 2
        await cdp.close()

    @pytest.mark.asyncio
    async def test_send_timeout(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        with pytest.raises(asyncio.TimeoutError):
            await cdp.send("Never.responds", timeout=0.05)
        await cdp.close()

    @pytest.mark.asyncio
    async def test_send_cuando_desconectado_lanza_error(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)
        cdp._alive = False

        with pytest.raises(ConnectionError):
            await cdp.send("Runtime.evaluate")
        await cdp.close()

    @pytest.mark.asyncio
    async def test_is_alive_tras_desconexion(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)
        assert cdp.is_alive is True

        mock_ws.force_disconnect()
        await asyncio.sleep(0.05)
        assert cdp.is_alive is False
        await cdp.close()

    @pytest.mark.asyncio
    async def test_send_sin_params(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def respond():
            await asyncio.sleep(0.02)
            mock_ws.inject_response(1, {})

        asyncio.create_task(respond())
        await cdp.send("Page.enable", timeout=2.0)

        payloads = mock_ws.get_sent_payloads()
        assert "params" not in payloads[0]
        await cdp.close()


# =========================================================================
# CDPSession — eventos
# =========================================================================

class TestCDPSessionEventos:
    @pytest.mark.asyncio
    async def test_wait_event_happy_path(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def fire_event():
            await asyncio.sleep(0.02)
            mock_ws.inject_event("Page.loadEventFired", {})

        asyncio.create_task(fire_event())
        result = await cdp.wait_event("Page.loadEventFired", timeout=2.0)
        assert result["method"] == "Page.loadEventFired"
        await cdp.close()

    @pytest.mark.asyncio
    async def test_wait_event_timeout(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        with pytest.raises(asyncio.TimeoutError):
            await cdp.wait_event("Never.fires", timeout=0.05)
        await cdp.close()

    @pytest.mark.asyncio
    async def test_pre_wait_event_antes_de_que_ocurra(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        fut = cdp.pre_wait_event("Page.loadEventFired")

        async def fire_event():
            await asyncio.sleep(0.02)
            mock_ws.inject_event("Page.loadEventFired", {"ts": 123})

        asyncio.create_task(fire_event())
        result = await cdp.wait_future(fut, timeout=2.0)
        assert result["params"]["ts"] == 123
        await cdp.close()

    @pytest.mark.asyncio
    async def test_pre_wait_event_desconectado_lanza_error(self, mock_ws):
        cdp = CDPSession(mock_ws)
        cdp._alive = False

        with pytest.raises(ConnectionError):
            cdp.pre_wait_event("Page.loadEventFired")

    @pytest.mark.asyncio
    async def test_futures_pendientes_resueltos_en_desconexion(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        fut = cdp.pre_wait_event("Never.fires")
        mock_ws.force_disconnect()
        await asyncio.sleep(0.05)

        with pytest.raises(ConnectionError):
            fut.result()
        await cdp.close()


# =========================================================================
# ejecutar_js
# =========================================================================

class TestEjecutarJs:
    @pytest.mark.asyncio
    async def test_ejecutar_js_retorna_valor(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={
            "result": {"result": {"type": "string", "value": "hello"}}
        })
        result = await ejecutar_js(cdp, "document.title;")
        assert result == {"type": "string", "value": "hello"}

    @pytest.mark.asyncio
    async def test_ejecutar_js_lanza_error_en_excepcion_js(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={
            "result": {"exceptionDetails": {"text": "ReferenceError"}}
        })
        with pytest.raises(RuntimeError, match="Error JS"):
            await ejecutar_js(cdp, "undefined_var;")

    @pytest.mark.asyncio
    async def test_ejecutar_js_resultado_vacio(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {}})
        result = await ejecutar_js(cdp, "void 0;")
        assert result == {}

    @pytest.mark.asyncio
    async def test_ejecutar_js_envia_expression_correcta(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {"result": {"value": 42}}})
        await ejecutar_js(cdp, "1 + 1;")

        call_args = cdp.send.call_args
        assert call_args[0][0] == "Runtime.evaluate"
        assert call_args[0][1]["expression"] == "1 + 1;"
        assert call_args[0][1]["returnByValue"] is True


# =========================================================================
# esperar_elemento
# =========================================================================

class TestEsperarElemento:
    @pytest.mark.asyncio
    async def test_elemento_encontrado_primer_intento(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={
            "result": {"result": {"type": "object", "value": {
                "x": 400, "y": 300, "width": 200, "height": 30
            }}}
        })
        result = await esperar_elemento(cdp, "#form", timeout=1.0)
        assert result == {"x": 400, "y": 300, "width": 200, "height": 30}

    @pytest.mark.asyncio
    async def test_elemento_no_encontrado_timeout(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={
            "result": {"result": {"type": "object", "value": None}}
        })
        with pytest.raises(ElementoNoEncontrado, match="#form"):
            await esperar_elemento(cdp, "#form", timeout=0.1)

    @pytest.mark.asyncio
    async def test_elemento_aparece_tras_polling(self):
        """El elemento no existe al inicio pero aparece en el segundo polling."""
        cdp = AsyncMock(spec=CDPSession)
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return {"result": {"result": {"type": "object", "value": None}}}
            return {"result": {"result": {"type": "object", "value": {
                "x": 100, "y": 200, "width": 50, "height": 25
            }}}}

        cdp.send = AsyncMock(side_effect=side_effect)

        with patch("cdp_core.WAIT_ELEMENT_POLL_S", 0.01):
            result = await esperar_elemento(cdp, "#form", timeout=2.0)
        assert result["x"] == 100

    @pytest.mark.asyncio
    async def test_elemento_invisible_no_cuenta(self):
        """Elemento existe pero display:none → debe seguir polling."""
        cdp = AsyncMock(spec=CDPSession)
        # Retorna null siempre (simula que el JS devuelve null por visibility check)
        cdp.send = AsyncMock(return_value={
            "result": {"result": {"type": "object", "value": None}}
        })
        with pytest.raises(ElementoNoEncontrado):
            await esperar_elemento(cdp, "#hidden", timeout=0.1)

    @pytest.mark.asyncio
    async def test_timeout_default_usa_config(self):
        """Sin timeout explícito usa TIMEOUT_ESPERA_ELEMENTO."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={
            "result": {"result": {"type": "object", "value": None}}
        })
        with patch("cdp_core.TIMEOUT_ESPERA_ELEMENTO", 0.05):
            with patch("cdp_core.WAIT_ELEMENT_POLL_S", 0.01):
                with pytest.raises(ElementoNoEncontrado):
                    await esperar_elemento(cdp, "#x")


# =========================================================================
# esperar_carga_pagina
# =========================================================================

class TestEsperarCargaPagina:
    @pytest.mark.asyncio
    async def test_carga_exitosa(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        async def fire():
            await asyncio.sleep(0.02)
            mock_ws.inject_event("Page.loadEventFired", {})

        asyncio.create_task(fire())
        await esperar_carga_pagina(cdp, timeout=2.0)
        await cdp.close()

    @pytest.mark.asyncio
    async def test_carga_timeout_lanza_excepcion(self, mock_ws):
        cdp = CDPSession(mock_ws)
        await cdp.start()
        await asyncio.sleep(0.01)

        with pytest.raises(TimeoutCargaPagina):
            await esperar_carga_pagina(cdp, timeout=0.05)
        await cdp.close()


# =========================================================================
# detectar_waf
# =========================================================================

class TestDetectarWaf:
    @pytest.mark.asyncio
    async def test_waf_detectado_ambas_cadenas(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {"result": {
            "value": "The requested URL was rejected. Please consult with your administrator.\nYour support ID is: 12345"
        }}})
        assert await detectar_waf(cdp) is True

    @pytest.mark.asyncio
    async def test_waf_no_detectado_pagina_normal(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {"result": {
            "value": "Sede Electrónica - Selección de provincia"
        }}})
        assert await detectar_waf(cdp) is False

    @pytest.mark.asyncio
    async def test_waf_no_detectado_solo_una_cadena(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {"result": {
            "value": "The requested URL was rejected. Something else."
        }}})
        assert await detectar_waf(cdp) is False

    @pytest.mark.asyncio
    async def test_waf_no_detectado_body_vacio(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {"result": {"value": ""}}})
        assert await detectar_waf(cdp) is False

    @pytest.mark.asyncio
    async def test_waf_retorna_false_en_excepcion(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=ConnectionError("disconnected"))
        assert await detectar_waf(cdp) is False

    @pytest.mark.asyncio
    async def test_waf_case_insensitive(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={"result": {"result": {
            "value": "THE REQUESTED URL WAS REJECTED\nYOUR SUPPORT ID IS: ABC"
        }}})
        assert await detectar_waf(cdp) is True


# =========================================================================
# obtener_ws_url
# =========================================================================

class TestObtenerWsUrl:
    @pytest.mark.asyncio
    async def test_devuelve_url_de_primera_page_tab(self):
        tabs_json = json.dumps([
            {"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/ABC"},
        ]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = tabs_json
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("cdp_core.urllib.request.urlopen", return_value=mock_resp):
            url = await obtener_ws_url()
        assert url == "ws://localhost:9222/devtools/page/ABC"

    @pytest.mark.asyncio
    async def test_ignora_tabs_no_page(self):
        tabs_json = json.dumps([
            {"type": "background_page", "webSocketDebuggerUrl": "ws://x"},
            {"type": "page", "webSocketDebuggerUrl": "ws://correct"},
        ]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = tabs_json
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("cdp_core.urllib.request.urlopen", return_value=mock_resp):
            url = await obtener_ws_url()
        assert url == "ws://correct"

    @pytest.mark.asyncio
    async def test_sin_pestanas_lanza_error(self):
        tabs_json = json.dumps([]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = tabs_json
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("cdp_core.urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ConnectionError, match="sin pestañas"):
                await obtener_ws_url()

    @pytest.mark.asyncio
    async def test_conexion_fallida_lanza_error(self):
        with patch("cdp_core.urllib.request.urlopen", side_effect=OSError("refused")):
            with pytest.raises(ConnectionError, match="No se pudo conectar"):
                await obtener_ws_url()


# =========================================================================
# log_info
# =========================================================================

class TestLogInfo:
    def test_imprime_con_timestamp(self, capsys):
        log_info("test message")
        captured = capsys.readouterr()
        assert "test message" in captured.out
        assert "[" in captured.out  # timestamp brackets
