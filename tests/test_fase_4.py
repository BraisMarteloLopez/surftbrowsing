"""Tests para fase_4 — flujo completo de Página 4 (solicitar cita)."""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_core import (
    CDPSession, WafBanError, ElementoNoEncontrado, TimeoutCargaPagina,
)
from humano import (
    Personalidad, EstadoRaton, fase_4,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_personalidad_rapida():
    with patch("humano.random.choice", return_value="rapido"):
        with patch("humano.random.uniform", return_value=0.5):
            return Personalidad()


def _make_config():
    return {
        "url_inicio": "https://icp.administracionelectronica.gob.es/icpplus/index.html",
        "ids": {
            "boton_solicitar_cita": "btnEnviar",
        },
    }


def _make_cdp_mock():
    cdp = AsyncMock(spec=CDPSession)
    cdp.send = AsyncMock(return_value={})
    cdp.is_alive = True

    def make_future(*args, **kwargs):
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"method": "Page.loadEventFired"})
        return fut

    cdp.pre_wait_event = MagicMock(side_effect=make_future)
    cdp.wait_future = AsyncMock(return_value={"method": "Page.loadEventFired"})

    return cdp


def _build_ejecutar_js_side_effect():
    async def side_effect(cdp, expression, timeout=5.0):
        if "focus()" in expression:
            return {}
        if "document.body.innerText" in expression:
            return {"value": "Solicitar cita"}
        return {}

    return side_effect


@contextmanager
def fase_4_patches(**overrides):
    defaults = {
        "esperar_elemento": {"new_callable": AsyncMock,
                             "return_value": {"x": 400, "y": 300, "width": 200, "height": 30}},
        "detectar_waf": {"new_callable": AsyncMock, "return_value": False},
        "ejecutar_js": {"side_effect": _build_ejecutar_js_side_effect()},
        "_mover_raton": {"new_callable": AsyncMock},
        "sleep": {"new_callable": AsyncMock},
        "_click_nativo": {"new_callable": AsyncMock},
        "_micro_movimiento": {"new_callable": AsyncMock},
        "random_random": {"return_value": 0.99},
        "random_randint": {"return_value": 1},
    }

    for key, val in overrides.items():
        if isinstance(val, dict):
            defaults[key] = val
        else:
            if callable(val) and not isinstance(val, AsyncMock):
                defaults[key] = {"side_effect": val}
            else:
                defaults[key] = {"return_value": val}

    targets = {
        "esperar_elemento": "humano.esperar_elemento",
        "detectar_waf": "humano.detectar_waf",
        "ejecutar_js": "humano.ejecutar_js",
        "_mover_raton": "humano._mover_raton",
        "sleep": "humano.asyncio.sleep",
        "_click_nativo": "humano._click_nativo",
        "_micro_movimiento": "humano._micro_movimiento",
        "random_random": "humano.random.random",
        "random_randint": "humano.random.randint",
    }

    started = {}
    try:
        for key, target in targets.items():
            p = patch(target, **defaults[key])
            started[key] = p.start()
        yield started
    finally:
        patch.stopall()


# =========================================================================
# Fase 4 — Carga y WAF
# =========================================================================

class TestFase4CargaYWaf:
    @pytest.mark.asyncio
    async def test_espera_boton_solicitar_cita(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with fase_4_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_4(cdp, personalidad, raton, config)

        assert "#btnEnviar" in esperar_calls

    @pytest.mark.asyncio
    async def test_waf_en_carga_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_4_patches(detectar_waf={"new_callable": AsyncMock, "return_value": True}):
            with pytest.raises(WafBanError, match="Página 4"):
                await fase_4(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_waf_tras_envio_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        waf_calls = [0]

        async def waf_side_effect(cdp):
            waf_calls[0] += 1
            return waf_calls[0] > 1

        with fase_4_patches(detectar_waf={"side_effect": waf_side_effect}):
            with pytest.raises(WafBanError, match="tras envío"):
                await fase_4(cdp, personalidad, raton, config)


# =========================================================================
# Fase 4 — Focus + Click
# =========================================================================

class TestFase4FocusClick:
    @pytest.mark.asyncio
    async def test_focus_antes_de_click(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        js_calls = []

        base = _build_ejecutar_js_side_effect()

        async def tracking_js(cdp, expression, timeout=5.0):
            js_calls.append(expression.strip())
            return await base(cdp, expression, timeout)

        with fase_4_patches(ejecutar_js={"side_effect": tracking_js}):
            await fase_4(cdp, personalidad, raton, config)

        focus_calls = [e for e in js_calls if "focus()" in e and "btnEnviar" in e]
        assert len(focus_calls) >= 1

    @pytest.mark.asyncio
    async def test_click_nativo_ejecutado(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        clicks = []

        async def mock_click(cdp, x, y):
            clicks.append((x, y))

        with fase_4_patches(_click_nativo={"side_effect": mock_click}):
            await fase_4(cdp, personalidad, raton, config)

        assert len(clicks) == 1

    @pytest.mark.asyncio
    async def test_pre_registra_evento_carga(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_4_patches():
            await fase_4(cdp, personalidad, raton, config)

        pre_wait_calls = cdp.pre_wait_event.call_args_list
        load_events = [c for c in pre_wait_calls if c[0][0] == "Page.loadEventFired"]
        assert len(load_events) >= 1


# =========================================================================
# Fase 4 — Timeout
# =========================================================================

class TestFase4Timeout:
    @pytest.mark.asyncio
    async def test_timeout_carga_lanza_excepcion(self):
        cdp = _make_cdp_mock()
        cdp.wait_future = AsyncMock(side_effect=asyncio.TimeoutError())
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_4_patches():
            with pytest.raises(TimeoutCargaPagina, match="Página 4"):
                await fase_4(cdp, personalidad, raton, config)


# =========================================================================
# Fase 4 — No navega
# =========================================================================

class TestFase4NoNavega:
    @pytest.mark.asyncio
    async def test_no_hace_page_navigate(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_4_patches():
            await fase_4(cdp, personalidad, raton, config)

        send_calls = cdp.send.call_args_list
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        assert len(page_navigate) == 0


# =========================================================================
# Fase 4 — Aterrizaje
# =========================================================================

class TestFase4Aterrizaje:
    @pytest.mark.asyncio
    async def test_micro_movimientos_ejecutados(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_4_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_randint={"return_value": 2},
        ):
            await fase_4(cdp, personalidad, raton, config)

        assert len(micro_calls) >= 2


# =========================================================================
# Fase 4 — Disconnect
# =========================================================================

class TestFase4Disconnect:
    @pytest.mark.asyncio
    async def test_esperar_elemento_falla(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def esperar_falla(cdp, selector, timeout=None):
            raise ConnectionError("CDP disconnected")

        with fase_4_patches(esperar_elemento={"side_effect": esperar_falla}):
            with pytest.raises(ConnectionError):
                await fase_4(cdp, personalidad, raton, config)


# =========================================================================
# Fase 4 — Config inválida
# =========================================================================

class TestFase4ConfigInvalida:
    @pytest.mark.asyncio
    async def test_config_sin_boton_lanza_keyerror(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"ids": {}}

        with fase_4_patches():
            with pytest.raises(KeyError):
                await fase_4(cdp, personalidad, raton, config)


# =========================================================================
# Fase 4 — End to end
# =========================================================================

class TestFase4EndToEnd:
    @pytest.mark.asyncio
    async def test_flujo_completo_sin_errores(self):
        cdp = _make_cdp_mock()
        raton = EstadoRaton()
        config = _make_config()

        for velocidad in ["rapido", "normal", "lento"]:
            with patch("humano.random.choice", return_value=velocidad):
                personalidad = Personalidad()

            with fase_4_patches():
                await fase_4(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_multiples_ejecuciones_no_acumulan_estado(self):
        config = _make_config()

        for i in range(3):
            cdp = _make_cdp_mock()
            personalidad = _make_personalidad_rapida()
            raton = EstadoRaton()

            with fase_4_patches():
                await fase_4(cdp, personalidad, raton, config)
