"""Tests exhaustivos para fase_2 — flujo completo de Página 2 (aviso informativo)."""

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
    Personalidad, EstadoRaton, fase_2,
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
            "boton_entrar_f3": "btnEntrar",
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


def _build_scroll_sequence(scroll_steps):
    """Construye un side_effect para ejecutar_js que simula scroll progresivo.

    scroll_steps: lista de (scrollTop, clientHeight, scrollHeight) tuples.
    El último debe tener scrollTop + clientHeight >= scrollHeight.
    """
    step_index = [0]

    async def side_effect(cdp, expression, timeout=5.0):
        expr = expression.strip()

        if "focus()" in expr:
            return {}

        if "pageYOffset" in expr or "scrollTop" in expr:
            idx = min(step_index[0], len(scroll_steps) - 1)
            step_index[0] += 1
            st, ch, sh = scroll_steps[idx]
            return {"value": {"scrollTop": st, "clientHeight": ch, "scrollHeight": sh}}

        if "document.body.innerText" in expr:
            return {"value": "Información sobre citas previas"}

        return {}

    return side_effect


@contextmanager
def fase_2_patches(**overrides):
    """Aplica todos los patches comunes para fase_2 tests."""
    defaults = {
        "esperar_elemento": {"new_callable": AsyncMock,
                             "return_value": {"x": 400, "y": 300, "width": 200, "height": 30}},
        "detectar_waf": {"new_callable": AsyncMock, "return_value": False},
        "ejecutar_js": {"side_effect": _build_scroll_sequence([
            (0, 600, 1800),
            (600, 600, 1800),
            (1200, 600, 1800),
        ])},
        "_mover_raton": {"new_callable": AsyncMock},
        "sleep": {"new_callable": AsyncMock},
        "_click_nativo": {"new_callable": AsyncMock},
        "_micro_movimiento": {"new_callable": AsyncMock},
        "_scroll_exploratorio": {"new_callable": AsyncMock},
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
        "_scroll_exploratorio": "humano._scroll_exploratorio",
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
# Fase 2 — Carga y WAF
# =========================================================================

class TestFase2CargaYWaf:
    @pytest.mark.asyncio
    async def test_espera_boton_entrar_al_inicio(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with fase_2_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_2(cdp, personalidad, raton, config)

        assert "#btnEntrar" in esperar_calls

    @pytest.mark.asyncio
    async def test_waf_en_carga_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_2_patches(detectar_waf={"new_callable": AsyncMock, "return_value": True}):
            with pytest.raises(WafBanError, match="Página 2"):
                await fase_2(cdp, personalidad, raton, config)

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

        with fase_2_patches(detectar_waf={"side_effect": waf_side_effect}):
            with pytest.raises(WafBanError, match="tras envío"):
                await fase_2(cdp, personalidad, raton, config)


# =========================================================================
# Fase 2 — No navega
# =========================================================================

class TestFase2NoNavega:
    @pytest.mark.asyncio
    async def test_no_hace_page_navigate(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_2_patches():
            await fase_2(cdp, personalidad, raton, config)

        send_calls = cdp.send.call_args_list
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        assert len(page_navigate) == 0


# =========================================================================
# Fase 2 — Scroll exhaustivo
# =========================================================================

class TestFase2ScrollExhaustivo:
    @pytest.mark.asyncio
    async def test_scroll_multiple_veces_hasta_agotar(self):
        """Debe hacer scroll varias veces hasta que scrollTop+clientHeight >= scrollHeight."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        scroll_calls = []

        async def mock_scroll(*args, **kwargs):
            scroll_calls.append(1)

        with fase_2_patches(_scroll_exploratorio={"side_effect": mock_scroll}):
            await fase_2(cdp, personalidad, raton, config)

        # 3 pasos de scroll: (0,600,1800) → (600,600,1800) → (1200,600,1800)
        # Solo the first 2 need scroll, the 3rd check sees we're at bottom
        assert len(scroll_calls) >= 2, f"Esperaba al menos 2 scrolls, hubo {len(scroll_calls)}"

    @pytest.mark.asyncio
    async def test_pagina_corta_no_scroll(self):
        """Si scrollTop+clientHeight >= scrollHeight desde el inicio, no scrollea."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        scroll_calls = []

        async def mock_scroll(*args, **kwargs):
            scroll_calls.append(1)

        # Página que ya está al final
        js_side_effect = _build_scroll_sequence([(0, 600, 600)])

        with fase_2_patches(
            _scroll_exploratorio={"side_effect": mock_scroll},
            ejecutar_js={"side_effect": js_side_effect},
        ):
            await fase_2(cdp, personalidad, raton, config)

        assert len(scroll_calls) == 0, f"No debería scrollear, pero hubo {len(scroll_calls)}"

    @pytest.mark.asyncio
    async def test_pagina_larga_muchos_scrolls(self):
        """Página muy larga requiere muchas iteraciones de scroll."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        scroll_calls = []

        async def mock_scroll(*args, **kwargs):
            scroll_calls.append(1)

        steps = [
            (0, 500, 3000),
            (500, 500, 3000),
            (1000, 500, 3000),
            (1500, 500, 3000),
            (2000, 500, 3000),
            (2500, 500, 3000),  # 2500+500 >= 3000 → done
        ]
        js_side_effect = _build_scroll_sequence(steps)

        with fase_2_patches(
            _scroll_exploratorio={"side_effect": mock_scroll},
            ejecutar_js={"side_effect": js_side_effect},
        ):
            await fase_2(cdp, personalidad, raton, config)

        assert len(scroll_calls) >= 5

    @pytest.mark.asyncio
    async def test_scroll_con_margen_5px(self):
        """Debe parar cuando estamos a menos de 5px del final."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        scroll_calls = []

        async def mock_scroll(*args, **kwargs):
            scroll_calls.append(1)

        # 1197+600 = 1797 >= 1800-5 → should stop
        steps = [(0, 600, 1800), (1197, 600, 1800)]
        js_side_effect = _build_scroll_sequence(steps)

        with fase_2_patches(
            _scroll_exploratorio={"side_effect": mock_scroll},
            ejecutar_js={"side_effect": js_side_effect},
        ):
            await fase_2(cdp, personalidad, raton, config)

        assert len(scroll_calls) == 1


# =========================================================================
# Fase 2 — Focus + Click en Entrar
# =========================================================================

class TestFase2FocusClick:
    @pytest.mark.asyncio
    async def test_focus_antes_de_click(self):
        """Debe hacer focus() en el botón antes del click."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        js_calls = []

        base_side_effect = _build_scroll_sequence([(0, 600, 600)])

        async def tracking_js(cdp, expression, timeout=5.0):
            js_calls.append(expression.strip())
            return await base_side_effect(cdp, expression, timeout)

        with fase_2_patches(ejecutar_js={"side_effect": tracking_js}):
            await fase_2(cdp, personalidad, raton, config)

        focus_calls = [e for e in js_calls if "focus()" in e and "btnEntrar" in e]
        assert len(focus_calls) >= 1, "Debe hacer focus() en btnEntrar"

    @pytest.mark.asyncio
    async def test_click_nativo_ejecutado(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        clicks = []

        async def mock_click(cdp, x, y):
            clicks.append((x, y))

        with fase_2_patches(_click_nativo={"side_effect": mock_click}):
            await fase_2(cdp, personalidad, raton, config)

        assert len(clicks) >= 1

    @pytest.mark.asyncio
    async def test_pre_registra_evento_carga(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_2_patches():
            await fase_2(cdp, personalidad, raton, config)

        pre_wait_calls = cdp.pre_wait_event.call_args_list
        load_events = [c for c in pre_wait_calls if c[0][0] == "Page.loadEventFired"]
        assert len(load_events) >= 1


# =========================================================================
# Fase 2 — Timeout de carga
# =========================================================================

class TestFase2Timeout:
    @pytest.mark.asyncio
    async def test_timeout_carga_lanza_excepcion(self):
        cdp = _make_cdp_mock()
        cdp.wait_future = AsyncMock(side_effect=asyncio.TimeoutError())
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_2_patches():
            with pytest.raises(TimeoutCargaPagina, match="Página 2"):
                await fase_2(cdp, personalidad, raton, config)


# =========================================================================
# Fase 2 — Aterrizaje
# =========================================================================

class TestFase2Aterrizaje:
    @pytest.mark.asyncio
    async def test_micro_movimientos_ejecutados(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_2_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_randint={"return_value": 2},
        ):
            await fase_2(cdp, personalidad, raton, config)

        assert len(micro_calls) >= 2


# =========================================================================
# Fase 2 — Transición
# =========================================================================

class TestFase2Transicion:
    @pytest.mark.asyncio
    async def test_idle_con_probabilidad_baja(self):
        """Con random.random=0.1 (< TRANSICION_IDLE_PROB=0.40), hace idle."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_2_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_random={"return_value": 0.1},
        ):
            await fase_2(cdp, personalidad, raton, config)

        # aterrizaje (1) + transición idle (1) = al menos 2
        assert len(micro_calls) >= 2

    @pytest.mark.asyncio
    async def test_sin_idle_con_probabilidad_alta(self):
        """Con random.random=0.99 (> TRANSICION_IDLE_PROB), no hace idle extra."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_2_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_random={"return_value": 0.99},
            random_randint={"return_value": 1},
        ):
            await fase_2(cdp, personalidad, raton, config)

        # Solo aterrizaje (1), sin idle extra
        assert len(micro_calls) == 1


# =========================================================================
# Fase 2 — Disconnect mid-fase
# =========================================================================

class TestFase2Disconnect:
    @pytest.mark.asyncio
    async def test_esperar_elemento_falla_por_desconexion(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def esperar_falla(cdp, selector, timeout=None):
            raise ConnectionError("CDP disconnected")

        with fase_2_patches(esperar_elemento={"side_effect": esperar_falla}):
            with pytest.raises(ConnectionError):
                await fase_2(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_ejecutar_js_falla_mid_scroll(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_falla(cdp, expression, timeout=5.0):
            if "pageYOffset" in expression:
                raise ConnectionError("CDP gone during scroll check")
            return {}

        with fase_2_patches(ejecutar_js={"side_effect": js_falla}):
            with pytest.raises(ConnectionError, match="scroll"):
                await fase_2(cdp, personalidad, raton, config)


# =========================================================================
# Fase 2 — Config inválida
# =========================================================================

class TestFase2ConfigInvalida:
    @pytest.mark.asyncio
    async def test_config_sin_boton_entrar_lanza_keyerror(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"ids": {}}

        with fase_2_patches():
            with pytest.raises(KeyError):
                await fase_2(cdp, personalidad, raton, config)


# =========================================================================
# Fase 2 — End to end
# =========================================================================

class TestFase2EndToEnd:
    @pytest.mark.asyncio
    async def test_flujo_completo_sin_errores(self):
        cdp = _make_cdp_mock()
        raton = EstadoRaton()
        config = _make_config()

        for velocidad in ["rapido", "normal", "lento"]:
            with patch("humano.random.choice", return_value=velocidad):
                personalidad = Personalidad()

            with fase_2_patches():
                await fase_2(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_multiples_ejecuciones_no_acumulan_estado(self):
        config = _make_config()

        for i in range(3):
            cdp = _make_cdp_mock()
            personalidad = _make_personalidad_rapida()
            raton = EstadoRaton()

            with fase_2_patches():
                await fase_2(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_orden_operaciones_scroll_luego_focus_luego_click(self):
        """Verifica el orden: scroll exhaustivo → focus → click."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        operations = []

        async def mock_scroll(*args, **kwargs):
            operations.append("scroll")

        async def mock_click(cdp, x, y):
            operations.append("click")

        base_side_effect = _build_scroll_sequence([
            (0, 600, 1200),
            (600, 600, 1200),
        ])

        async def tracking_js(cdp, expression, timeout=5.0):
            if "focus()" in expression:
                operations.append("focus")
            return await base_side_effect(cdp, expression, timeout)

        with fase_2_patches(
            _scroll_exploratorio={"side_effect": mock_scroll},
            _click_nativo={"side_effect": mock_click},
            ejecutar_js={"side_effect": tracking_js},
        ):
            await fase_2(cdp, personalidad, raton, config)

        # Scroll debe ir antes de focus, y focus antes de click
        scroll_indices = [i for i, op in enumerate(operations) if op == "scroll"]
        focus_indices = [i for i, op in enumerate(operations) if op == "focus"]
        click_indices = [i for i, op in enumerate(operations) if op == "click"]

        assert len(scroll_indices) >= 1
        assert len(focus_indices) >= 1
        assert len(click_indices) >= 1

        last_scroll = max(scroll_indices)
        first_focus = min(focus_indices)
        first_click = min(click_indices)

        assert last_scroll < first_focus, "Scroll debe ir antes de focus"
        assert first_focus < first_click, "Focus debe ir antes de click"
