"""Tests exhaustivos para fase_1 — flujo completo de Página 1 (selección de trámite)."""

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
    Personalidad, EstadoRaton, fase_1,
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
        "tramite_prefijo": "POLICIA TARJETA CONFLICTO UKRANIA",
        "ids": {
            "dropdown_tramite": "tramiteGrupo[0]",
            "valor_tramite": "4112",
            "boton_aceptar_f2": "btnAceptar",
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


# Mock responses
TRAMITE_OPTIONS = {
    "value": {
        "options": [
            {"index": 0, "text": "Seleccione..."},
            {"index": 1, "text": "POLICIA CNP - RECOGIDA DE TARJETA"},
            {"index": 2, "text": "POLICIA TARJETA CONFLICTO UKRANIA - SOLICITUD"},
            {"index": 3, "text": "POLICIA - AUTORIZACION DE REGRESO"},
        ],
        "currentIndex": 0,
    }
}


def _build_ejecutar_js_side_effect(verification_results=None):
    if verification_results is None:
        verification_results = ["POLICIA TARJETA CONFLICTO UKRANIA - SOLICITUD"]

    verify_index = [0]

    async def side_effect(cdp, expression, timeout=5.0):
        expr = expression.strip()

        if "focus()" in expr and "selectedOptions" not in expr:
            return {}

        if "sel.options.length" in expr or "opts.push" in expr:
            return TRAMITE_OPTIONS

        if "selectedOptions" in expr or ("sel.options[sel.selectedIndex]" in expr
                                          and "textContent" in expr):
            idx = verify_index[0]
            verify_index[0] += 1
            if idx < len(verification_results):
                return {"value": verification_results[idx]}
            return {"value": "POLICIA TARJETA CONFLICTO UKRANIA - SOLICITUD"}

        if "document.body.innerText" in expr:
            return {"value": "Sede Electrónica"}

        return {}

    return side_effect


@contextmanager
def fase_1_patches(**overrides):
    """Aplica todos los patches comunes para fase_1 tests."""
    defaults = {
        "esperar_elemento": {"new_callable": AsyncMock,
                             "return_value": {"x": 400, "y": 300, "width": 200, "height": 30}},
        "detectar_waf": {"new_callable": AsyncMock, "return_value": False},
        "ejecutar_js": {"side_effect": _build_ejecutar_js_side_effect()},
        "_mover_raton": {"new_callable": AsyncMock},
        "sleep": {"new_callable": AsyncMock},
        "_enviar_tecla": {"new_callable": AsyncMock},
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
        "_enviar_tecla": "humano._enviar_tecla",
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
# Fase 1 — Carga y WAF
# =========================================================================

class TestFase1CargaYWaf:
    @pytest.mark.asyncio
    async def test_espera_dropdown_tramite_al_inicio(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with fase_1_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_1(cdp, personalidad, raton, config)

        # Debe esperar el dropdown (con corchetes escapados) y el botón
        assert any("tramiteGrupo" in s for s in esperar_calls)
        assert "#btnAceptar" in esperar_calls

    @pytest.mark.asyncio
    async def test_waf_en_carga_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_1_patches(detectar_waf={"new_callable": AsyncMock, "return_value": True}):
            with pytest.raises(WafBanError, match="Página 1"):
                await fase_1(cdp, personalidad, raton, config)

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

        with fase_1_patches(detectar_waf={"side_effect": waf_side_effect}):
            with pytest.raises(WafBanError, match="tras envío"):
                await fase_1(cdp, personalidad, raton, config)


# =========================================================================
# Fase 1 — No navega (ya estamos en la página)
# =========================================================================

class TestFase1NoNavega:
    @pytest.mark.asyncio
    async def test_no_hace_page_navigate(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_1_patches():
            await fase_1(cdp, personalidad, raton, config)

        send_calls = cdp.send.call_args_list
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        assert len(page_navigate) == 0


# =========================================================================
# Fase 1 — Scroll obligatorio en aterrizaje
# =========================================================================

class TestFase1ScrollObligatorio:
    @pytest.mark.asyncio
    async def test_scroll_siempre_ejecutado(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        scroll_calls = []

        async def mock_scroll(*args, **kwargs):
            scroll_calls.append(1)

        # random.random=0.99 (high) — even so, scroll should happen because it's obligatory
        with fase_1_patches(_scroll_exploratorio={"side_effect": mock_scroll}):
            await fase_1(cdp, personalidad, raton, config)

        assert len(scroll_calls) >= 1, "Scroll obligatorio no ejecutado"


# =========================================================================
# Fase 1 — Selección de trámite (match por prefijo)
# =========================================================================

class TestFase1SeleccionTramite:
    @pytest.mark.asyncio
    async def test_navega_con_arrowdown_hasta_tramite(self):
        """Trámite en index 2, current 0 → al menos 2 ArrowDown de navegación."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        with fase_1_patches(_enviar_tecla={"side_effect": mock_tecla}):
            await fase_1(cdp, personalidad, raton, config)

        arrow_downs = [t for t in teclas if t == "ArrowDown"]
        enters = [t for t in teclas if t == "Enter"]
        assert len(arrow_downs) >= 2
        assert len(enters) == 1

    @pytest.mark.asyncio
    async def test_match_por_prefijo(self):
        """El match funciona con startsWith, no igualdad exacta."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()
        # Cambiar prefijo a algo más corto
        config["tramite_prefijo"] = "POLICIA TARJETA"

        with fase_1_patches():
            # No debe lanzar excepción
            await fase_1(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_tramite_no_encontrado_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()
        config["tramite_prefijo"] = "TRAMITE INEXISTENTE"

        with fase_1_patches():
            with pytest.raises(ElementoNoEncontrado, match="TRAMITE INEXISTENTE"):
                await fase_1(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_verificacion_fallida_reintenta_con_teclado(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        teclas_enviadas = []

        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["POLICIA CNP - RECOGIDA",
                                  "POLICIA TARJETA CONFLICTO UKRANIA - SOLICITUD"]
        )

        async def tracking_tecla(cdp, key):
            teclas_enviadas.append(key)

        with fase_1_patches(
            ejecutar_js={"side_effect": side_effect},
            _enviar_tecla={"side_effect": tracking_tecla},
        ):
            await fase_1(cdp, personalidad, raton, config)

        # Should have used keyboard (ArrowDown/ArrowUp + Enter) for retry
        assert "Enter" in teclas_enviadas

    @pytest.mark.asyncio
    async def test_verificacion_fallida_dos_veces_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["Seleccione...", "Seleccione..."]
        )

        with fase_1_patches(ejecutar_js={"side_effect": side_effect}):
            with pytest.raises(RuntimeError, match="2 intentos"):
                await fase_1(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_tramite_prefijo_configurable(self):
        """config['tramite_prefijo'] cambia el trámite buscado."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()
        config["tramite_prefijo"] = "POLICIA - AUTORIZACION"

        # Needs custom options to verify we navigate to index 3
        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["POLICIA - AUTORIZACION DE REGRESO"]
        )

        with fase_1_patches(
            ejecutar_js={"side_effect": side_effect},
            _enviar_tecla={"side_effect": mock_tecla},
        ):
            await fase_1(cdp, personalidad, raton, config)

        # Target at index 3 → exploratory (1) + nav (3) = at least 3 ArrowDowns
        arrow_downs = [t for t in teclas if t == "ArrowDown"]
        assert len(arrow_downs) >= 3


# =========================================================================
# Fase 1 — Envío y carga
# =========================================================================

class TestFase1Envio:
    @pytest.mark.asyncio
    async def test_click_nativo_en_btn_aceptar(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        clicks = []

        async def mock_click(cdp, x, y):
            clicks.append((x, y))

        with fase_1_patches(_click_nativo={"side_effect": mock_click}):
            await fase_1(cdp, personalidad, raton, config)

        assert len(clicks) >= 2  # dropdown + botón

    @pytest.mark.asyncio
    async def test_pre_registra_evento_carga(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_1_patches():
            await fase_1(cdp, personalidad, raton, config)

        pre_wait_calls = cdp.pre_wait_event.call_args_list
        load_events = [c for c in pre_wait_calls if c[0][0] == "Page.loadEventFired"]
        assert len(load_events) >= 1

    @pytest.mark.asyncio
    async def test_timeout_carga_lanza_excepcion(self):
        cdp = _make_cdp_mock()
        cdp.wait_future = AsyncMock(side_effect=asyncio.TimeoutError())
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_1_patches():
            with pytest.raises(TimeoutCargaPagina, match="Página 1"):
                await fase_1(cdp, personalidad, raton, config)


# =========================================================================
# Fase 1 — CSS selector con corchetes
# =========================================================================

class TestFase1CSSEscaping:
    @pytest.mark.asyncio
    async def test_selector_con_corchetes_funciona(self):
        """El selector tramiteGrupo[0] debe escaparse correctamente."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with fase_1_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_1(cdp, personalidad, raton, config)

        # El selector debe tener los corchetes escapados
        tramite_selectors = [s for s in esperar_calls if "tramiteGrupo" in s]
        assert len(tramite_selectors) >= 1
        assert tramite_selectors[0] == "#tramiteGrupo\\[0\\]"


# =========================================================================
# Fase 1 — Config inválida y edge cases
# =========================================================================

class TestFase1ConfigInvalida:
    @pytest.mark.asyncio
    async def test_config_sin_dropdown_tramite_lanza_keyerror(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"ids": {"boton_aceptar_f2": "btn", "valor_tramite": "x"}}

        with fase_1_patches():
            with pytest.raises(KeyError):
                await fase_1(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_options_vacias_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_vacio(cdp, expression, timeout=5.0):
            if "opts.push" in expression:
                return {"value": {"options": [], "currentIndex": 0}}
            if "focus()" in expression:
                return {}
            return {}

        with fase_1_patches(ejecutar_js={"side_effect": js_vacio}):
            with pytest.raises(ElementoNoEncontrado, match="POLICIA TARJETA"):
                await fase_1(cdp, personalidad, raton, config)


# =========================================================================
# Fase 1 — Disconnection mid-fase
# =========================================================================

class TestFase1Disconnect:
    @pytest.mark.asyncio
    async def test_esperar_elemento_falla_por_desconexion(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def esperar_falla(cdp, selector, timeout=None):
            raise ConnectionError("CDP disconnected")

        with fase_1_patches(esperar_elemento={"side_effect": esperar_falla}):
            with pytest.raises(ConnectionError):
                await fase_1(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_ejecutar_js_falla_mid_fase(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_falla(cdp, expression, timeout=5.0):
            if "focus()" in expression:
                raise ConnectionError("CDP gone during focus")
            return {}

        with fase_1_patches(ejecutar_js={"side_effect": js_falla}):
            with pytest.raises(ConnectionError, match="focus"):
                await fase_1(cdp, personalidad, raton, config)


# =========================================================================
# Fase 1 — Transición y aterrizaje
# =========================================================================

class TestFase1Aterrizaje:
    @pytest.mark.asyncio
    async def test_micro_movimientos_ejecutados(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_1_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_randint={"return_value": 2},
        ):
            await fase_1(cdp, personalidad, raton, config)

        assert len(micro_calls) >= 2


class TestFase1Transicion:
    @pytest.mark.asyncio
    async def test_idle_con_probabilidad(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_1_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_random={"return_value": 0.1},
        ):
            await fase_1(cdp, personalidad, raton, config)

        # aterrizaje (1) + transición idle (1) = at least 2
        assert len(micro_calls) >= 2


# =========================================================================
# Fase 1 — End to end
# =========================================================================

class TestFase1EndToEnd:
    @pytest.mark.asyncio
    async def test_flujo_completo_sin_errores(self):
        cdp = _make_cdp_mock()
        raton = EstadoRaton()
        config = _make_config()

        for velocidad in ["rapido", "normal", "lento"]:
            with patch("humano.random.choice", return_value=velocidad):
                personalidad = Personalidad()

            with fase_1_patches():
                await fase_1(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_multiples_ejecuciones_no_acumulan_estado(self):
        config = _make_config()

        for i in range(3):
            cdp = _make_cdp_mock()
            personalidad = _make_personalidad_rapida()
            raton = EstadoRaton()

            with fase_1_patches():
                await fase_1(cdp, personalidad, raton, config)
