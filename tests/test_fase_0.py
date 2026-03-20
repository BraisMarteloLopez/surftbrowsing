"""Tests exhaustivos para fase_0 — flujo completo de Página 0."""

import asyncio
from unittest.mock import AsyncMock, patch, call, MagicMock

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_core import (
    CDPSession, WafBanError, ElementoNoEncontrado, TimeoutCargaPagina,
)
from humano import (
    Personalidad, EstadoRaton, fase_0,
)


# ---------------------------------------------------------------------------
# Helpers para construir mocks de fase_0
# ---------------------------------------------------------------------------

def _make_personalidad_rapida():
    """Personalidad rápida determinista para tests."""
    with patch("humano.random.choice", return_value="rapido"):
        with patch("humano.random.uniform", return_value=0.5):
            return Personalidad()


def _make_config():
    return {
        "url_inicio": "https://icp.administracionelectronica.gob.es/icpplus/index.html",
        "ids": {
            "dropdown_provincia": "form",
            "valor_madrid": "/icpplustiem/citar?p=28&locale=es",
            "boton_aceptar_f1": "btnAceptar",
        },
    }


def _make_cdp_mock():
    """CDP mock que responde a todo de forma genérica."""
    cdp = AsyncMock(spec=CDPSession)
    cdp.send = AsyncMock(return_value={})
    cdp.is_alive = True

    # pre_wait_event devuelve un Future que se resuelve inmediatamente
    def make_future(*args, **kwargs):
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"method": "Page.loadEventFired"})
        return fut

    cdp.pre_wait_event = MagicMock(side_effect=make_future)
    cdp.wait_future = AsyncMock(return_value={"method": "Page.loadEventFired"})

    return cdp


# Mock responses para ejecutar_js
OPTIONS_RESPONSE = {
    "value": {
        "options": [
            {"index": 0, "text": "Seleccione..."},
            {"index": 1, "text": "Barcelona"},
            {"index": 2, "text": "Madrid"},
            {"index": 3, "text": "Valencia"},
        ],
        "currentIndex": 0,
    }
}

MADRID_VERIFIED = {"value": "Madrid"}
NOT_MADRID = {"value": "Barcelona"}
NORMAL_PAGE = {"value": "Sede Electrónica"}


def _build_ejecutar_js_side_effect(verification_results=None):
    """Construye un side_effect para ejecutar_js que responde según el contexto.

    verification_results: lista de strings para las verificaciones de selección.
                         Default: ["Madrid"] (éxito en primera verificación).
    """
    if verification_results is None:
        verification_results = ["Madrid"]

    call_index = [0]
    verify_index = [0]

    async def side_effect(cdp, expression, timeout=5.0):
        expr = expression.strip()

        # Focus call
        if "focus()" in expr and "selectedOptions" not in expr:
            return {}

        # Options listing
        if "sel.options.length" in expr or "opts.push" in expr:
            return OPTIONS_RESPONSE

        # Verification call (textContent.trim)
        if "selectedOptions" in expr or ("sel.options[sel.selectedIndex]" in expr
                                          and "textContent" in expr):
            idx = verify_index[0]
            verify_index[0] += 1
            if idx < len(verification_results):
                return {"value": verification_results[idx]}
            return {"value": "Madrid"}

        # Change/input dispatch
        if "dispatchEvent" in expr and ("change" in expr or "input" in expr):
            return {}

        # Fallback set value (reintento)
        if "sel.value" in expr:
            return {}

        # WAF detection (body text)
        if "document.body.innerText" in expr:
            return {"value": "Sede Electrónica"}

        return {}

    return side_effect


# =========================================================================
# Fase 0 — Primera vez (navegación)
# =========================================================================

class TestFase0PrimeraVez:
    @pytest.mark.asyncio
    async def test_navega_a_url_inicio(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True, config=config)

        # Verificar que se navegó
        send_calls = cdp.send.call_args_list
        page_enable = [c for c in send_calls if c[0][0] == "Page.enable"]
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        assert len(page_enable) >= 1
        assert len(page_navigate) == 1
        assert page_navigate[0][0][1]["url"] == config["url_inicio"]

    @pytest.mark.asyncio
    async def test_no_navega_en_reintento(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=False, config=config)

        # No debe haber Page.navigate
        send_calls = cdp.send.call_args_list
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        assert len(page_navigate) == 0


# =========================================================================
# Fase 0 — Detección WAF
# =========================================================================

class TestFase0Waf:
    @pytest.mark.asyncio
    async def test_waf_en_carga_inicial_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=True):
                with pytest.raises(WafBanError, match="WAF detectado en Página 0"):
                    with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                        await fase_0(cdp, personalidad, raton,
                                     es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_waf_tras_envio_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        # WAF no detectado en carga inicial, sí tras envío
        waf_calls = [0]

        async def waf_side_effect(cdp):
            waf_calls[0] += 1
            return waf_calls[0] > 1  # True en la segunda llamada (post-envío)

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", side_effect=waf_side_effect):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    with pytest.raises(WafBanError, match="tras envío"):
                                                        await fase_0(cdp, personalidad, raton,
                                                                     es_primera_vez=True, config=config)


# =========================================================================
# Fase 0 — Selección de Madrid
# =========================================================================

class TestFase0SeleccionMadrid:
    @pytest.mark.asyncio
    async def test_navega_con_arrowdown_hasta_madrid(self):
        """Madrid está en index 2, current es 0 → debe enviar 2 ArrowDown."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        teclas_enviadas = []

        async def mock_enviar_tecla(cdp, key):
            teclas_enviadas.append(key)

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", side_effect=mock_enviar_tecla):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True, config=config)

        # Scroll exploratorio: 1 iteración × 1 ArrowDown (randint=1 para ambos)
        # + navegación hasta Madrid: index 2 - 0 = 2 ArrowDown
        # + 1 Enter para confirmar
        arrow_downs = [t for t in teclas_enviadas if t == "ArrowDown"]
        enters = [t for t in teclas_enviadas if t == "Enter"]
        assert len(arrow_downs) >= 2  # al menos 2 para llegar a Madrid
        assert len(enters) == 1  # confirmar selección

    @pytest.mark.asyncio
    async def test_madrid_no_encontrado_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        # Options sin Madrid
        options_sin_madrid = {
            "value": {
                "options": [
                    {"index": 0, "text": "Seleccione..."},
                    {"index": 1, "text": "Barcelona"},
                ],
                "currentIndex": 0,
            }
        }

        async def js_sin_madrid(cdp, expression, timeout=5.0):
            if "opts.push" in expression:
                return options_sin_madrid
            if "focus()" in expression:
                return {}
            return {}

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=js_sin_madrid):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    with pytest.raises(ElementoNoEncontrado,
                                                                       match="Madrid"):
                                                        await fase_0(cdp, personalidad, raton,
                                                                     es_primera_vez=True,
                                                                     config=config)

    @pytest.mark.asyncio
    async def test_verificacion_fallida_reintenta_con_value(self):
        """Si la verificación post-selección falla, usa .value como fallback."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        js_expressions = []

        # Primera verificación: "Barcelona", segunda: "Madrid"
        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["Barcelona", "Madrid"]
        )

        async def tracking_js(cdp, expression, timeout=5.0):
            js_expressions.append(expression)
            return await side_effect(cdp, expression, timeout)

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=tracking_js):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        # Verificar que hubo un fallback con sel.value (the full expression includes it)
        all_js = "\n".join(js_expressions)
        assert "sel.value =" in all_js, (
            f"Expected fallback sel.value assignment. JS calls:\n{all_js[:500]}"
        )

    @pytest.mark.asyncio
    async def test_verificacion_fallida_dos_veces_lanza_error(self):
        """Si ambas verificaciones fallan, lanza RuntimeError."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["Barcelona", "Barcelona"]
        )

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=side_effect):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    with pytest.raises(RuntimeError,
                                                                       match="2 intentos"):
                                                        await fase_0(cdp, personalidad, raton,
                                                                     es_primera_vez=True,
                                                                     config=config)


# =========================================================================
# Fase 0 — Espera de elementos
# =========================================================================

class TestFase0EsperaElementos:
    @pytest.mark.asyncio
    async def test_espera_form_antes_de_interactuar(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with patch("humano.esperar_elemento", side_effect=mock_esperar):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        # Debe esperar #form (múltiples veces: carga + mover_a_elemento + re-verificar)
        # y #btnAceptar
        assert "#form" in esperar_calls
        assert "#btnAceptar" in esperar_calls

    @pytest.mark.asyncio
    async def test_form_no_encontrado_propaga_excepcion(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def esperar_falla(cdp, selector, timeout=None):
            raise ElementoNoEncontrado(f"#{selector} no encontrado")

        with patch("humano.esperar_elemento", side_effect=esperar_falla):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(ElementoNoEncontrado):
                        await fase_0(cdp, personalidad, raton,
                                     es_primera_vez=True, config=config)


# =========================================================================
# Fase 0 — Click en Aceptar y espera de carga
# =========================================================================

class TestFase0Envio:
    @pytest.mark.asyncio
    async def test_click_nativo_en_btn_aceptar(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        clicks = []

        async def mock_click(cdp, x, y):
            clicks.append((x, y))

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", side_effect=mock_click):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        # Debe haber al menos 2 clicks: uno en #form y otro en #btnAceptar
        assert len(clicks) >= 2

    @pytest.mark.asyncio
    async def test_pre_registra_evento_carga_antes_del_click(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        # pre_wait_event debe ser llamado con "Page.loadEventFired"
        pre_wait_calls = cdp.pre_wait_event.call_args_list
        load_events = [c for c in pre_wait_calls if c[0][0] == "Page.loadEventFired"]
        assert len(load_events) >= 1

    @pytest.mark.asyncio
    async def test_timeout_carga_tras_click_lanza_excepcion(self):
        cdp = _make_cdp_mock()
        # Primera llamada a wait_future (navegación) OK, segunda (post-click) timeout
        call_count = [0]

        async def wait_future_side_effect(fut, timeout=None):
            call_count[0] += 1
            if call_count[0] <= 1:
                return {"method": "Page.loadEventFired"}
            raise asyncio.TimeoutError()

        cdp.wait_future = AsyncMock(side_effect=wait_future_side_effect)
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=1):
                                                    with pytest.raises(TimeoutCargaPagina):
                                                        await fase_0(cdp, personalidad, raton,
                                                                     es_primera_vez=True,
                                                                     config=config)


# =========================================================================
# Fase 0 — Aterrizaje (comportamiento humano)
# =========================================================================

class TestFase0Aterrizaje:
    @pytest.mark.asyncio
    async def test_micro_movimientos_ejecutados(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", side_effect=mock_micro):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.99):
                                                with patch("humano.random.randint", return_value=2):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        # Al menos 2 micro-movimientos en aterrizaje (randint=2)
        assert len(micro_calls) >= 2

    @pytest.mark.asyncio
    async def test_scroll_exploratorio_con_probabilidad(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        scroll_calls = []

        async def mock_scroll(*args, **kwargs):
            scroll_calls.append(1)

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                        with patch("humano._scroll_exploratorio", side_effect=mock_scroll):
                                            # random.random=0.1 < SCROLL_PROB=0.30 → scroll happens
                                            with patch("humano.random.random", return_value=0.1):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        assert len(scroll_calls) >= 1


# =========================================================================
# Fase 0 — Transición (comportamiento opcional)
# =========================================================================

class TestFase0Transicion:
    @pytest.mark.asyncio
    async def test_idle_movimiento_con_probabilidad(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(args)

        # random.random=0.1 → both IDLE_PROB (0.4) and EXTRA_PROB (0.2) trigger
        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                    with patch("humano._mover_raton", new_callable=AsyncMock):
                        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                            with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                with patch("humano._click_nativo", new_callable=AsyncMock):
                                    with patch("humano._micro_movimiento", side_effect=mock_micro):
                                        with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                            with patch("humano.random.random", return_value=0.1):
                                                with patch("humano.random.randint", return_value=1):
                                                    await fase_0(cdp, personalidad, raton,
                                                                 es_primera_vez=True,
                                                                 config=config)

        # micro-movimientos: aterrizaje (1) + transición idle (1) = al least 2
        assert len(micro_calls) >= 2


# =========================================================================
# Fase 0 — Flujo completo end-to-end
# =========================================================================

class TestFase0EndToEnd:
    @pytest.mark.asyncio
    async def test_flujo_completo_sin_errores(self):
        """Test de integración: todo el flujo de fase_0 sin errores."""
        cdp = _make_cdp_mock()
        raton = EstadoRaton()
        config = _make_config()

        for velocidad in ["rapido", "normal", "lento"]:
            with patch("humano.random.choice", return_value=velocidad):
                personalidad = Personalidad()

            with patch("humano.esperar_elemento", new_callable=AsyncMock,
                        return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
                with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                    with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                        with patch("humano._mover_raton", new_callable=AsyncMock):
                            with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                                with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                    with patch("humano._click_nativo", new_callable=AsyncMock):
                                        with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                            with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                                with patch("humano.random.random", return_value=0.99):
                                                    with patch("humano.random.randint", return_value=1):
                                                        # No debe lanzar excepción
                                                        await fase_0(cdp, personalidad, raton,
                                                                     es_primera_vez=True,
                                                                     config=config)

    @pytest.mark.asyncio
    async def test_multiples_ejecuciones_no_acumulan_estado(self):
        """Ejecutar fase_0 varias veces no causa problemas de estado."""
        config = _make_config()

        for i in range(3):
            cdp = _make_cdp_mock()
            personalidad = _make_personalidad_rapida()
            raton = EstadoRaton()

            with patch("humano.esperar_elemento", new_callable=AsyncMock,
                        return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
                with patch("humano.detectar_waf", new_callable=AsyncMock, return_value=False):
                    with patch("humano.ejecutar_js", side_effect=_build_ejecutar_js_side_effect()):
                        with patch("humano._mover_raton", new_callable=AsyncMock):
                            with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                                with patch("humano._enviar_tecla", new_callable=AsyncMock):
                                    with patch("humano._click_nativo", new_callable=AsyncMock):
                                        with patch("humano._micro_movimiento", new_callable=AsyncMock):
                                            with patch("humano._scroll_exploratorio", new_callable=AsyncMock):
                                                with patch("humano.random.random", return_value=0.99):
                                                    with patch("humano.random.randint", return_value=1):
                                                        await fase_0(cdp, personalidad, raton,
                                                                     es_primera_vez=(i == 0),
                                                                     config=config)
