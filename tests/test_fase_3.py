"""Tests exhaustivos para fase_3 — flujo completo de Página 3 (datos personales via autocomplete)."""

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
    Personalidad, EstadoRaton, fase_3,
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
            "input_nie": "txtIdCitado",
            "input_nombre": "txtDesCitado",
            "boton_aceptar_f4": "btnEnviar",
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


def _build_ejecutar_js_side_effect(nie_value="Y1234567X", nombre_value="Juan García López",
                                    nie_empty=False, nombre_empty=False):
    """Construye side_effect para ejecutar_js que simula autocomplete."""

    async def side_effect(cdp, expression, timeout=5.0):
        expr = expression.strip()

        if "focus()" in expr:
            return {}

        # Campo NIE — el.value
        if "txtIdCitado" in expr and "el.value" in expr:
            return {"value": "" if nie_empty else nie_value}

        # Campo Nombre — el.value
        if "txtDesCitado" in expr and "el.value" in expr:
            return {"value": "" if nombre_empty else nombre_value}

        # Botón focus
        if "btnEnviar" in expr and "focus()" in expr:
            return {}

        if "document.body.innerText" in expr:
            return {"value": "Datos personales"}

        return {}

    return side_effect


@contextmanager
def fase_3_patches(**overrides):
    """Aplica todos los patches comunes para fase_3 tests."""
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
# Fase 3 — Carga y WAF
# =========================================================================

class TestFase3CargaYWaf:
    @pytest.mark.asyncio
    async def test_espera_campo_nie_al_inicio(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with fase_3_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_3(cdp, personalidad, raton, config)

        assert "#txtIdCitado" in esperar_calls

    @pytest.mark.asyncio
    async def test_waf_en_carga_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_3_patches(detectar_waf={"new_callable": AsyncMock, "return_value": True}):
            with pytest.raises(WafBanError, match="Página 3"):
                await fase_3(cdp, personalidad, raton, config)

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

        with fase_3_patches(detectar_waf={"side_effect": waf_side_effect}):
            with pytest.raises(WafBanError, match="tras envío"):
                await fase_3(cdp, personalidad, raton, config)


# =========================================================================
# Fase 3 — Autocomplete de campos
# =========================================================================

class TestFase3Autocomplete:
    @pytest.mark.asyncio
    async def test_click_en_ambos_campos(self):
        """Debe hacer click en NIE y Nombre."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        clicks = []

        async def mock_click(cdp, x, y):
            clicks.append((x, y))

        with fase_3_patches(_click_nativo={"side_effect": mock_click}):
            await fase_3(cdp, personalidad, raton, config)

        # NIE click + Nombre click + botón click = 3
        assert len(clicks) == 3

    @pytest.mark.asyncio
    async def test_arrowdown_enter_para_cada_campo(self):
        """Debe enviar ArrowDown + Enter para seleccionar autocomplete en cada campo."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        with fase_3_patches(_enviar_tecla={"side_effect": mock_tecla}):
            await fase_3(cdp, personalidad, raton, config)

        # 2 campos × (ArrowDown + Enter) = 4 teclas
        arrow_downs = [t for t in teclas if t == "ArrowDown"]
        enters = [t for t in teclas if t == "Enter"]
        assert len(arrow_downs) == 2
        assert len(enters) == 2

    @pytest.mark.asyncio
    async def test_focus_en_ambos_campos(self):
        """Debe hacer focus() en NIE y Nombre."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        js_calls = []

        base_side_effect = _build_ejecutar_js_side_effect()

        async def tracking_js(cdp, expression, timeout=5.0):
            js_calls.append(expression.strip())
            return await base_side_effect(cdp, expression, timeout)

        with fase_3_patches(ejecutar_js={"side_effect": tracking_js}):
            await fase_3(cdp, personalidad, raton, config)

        focus_nie = [e for e in js_calls if "focus()" in e and "txtIdCitado" in e]
        focus_nombre = [e for e in js_calls if "focus()" in e and "txtDesCitado" in e]
        assert len(focus_nie) >= 1, "Debe hacer focus() en txtIdCitado"
        assert len(focus_nombre) >= 1, "Debe hacer focus() en txtDesCitado"

    @pytest.mark.asyncio
    async def test_verifica_valor_tras_autocomplete(self):
        """Debe verificar que el campo tiene valor tras seleccionar autocomplete."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        js_calls = []

        base_side_effect = _build_ejecutar_js_side_effect()

        async def tracking_js(cdp, expression, timeout=5.0):
            js_calls.append(expression.strip())
            return await base_side_effect(cdp, expression, timeout)

        with fase_3_patches(ejecutar_js={"side_effect": tracking_js}):
            await fase_3(cdp, personalidad, raton, config)

        # Debe leer el valor del campo para verificar
        value_checks = [e for e in js_calls if "el.value" in e]
        assert len(value_checks) >= 2, "Debe verificar ambos campos"


# =========================================================================
# Fase 3 — Autocomplete vacío
# =========================================================================

class TestFase3AutocompleteVacio:
    @pytest.mark.asyncio
    async def test_nie_vacio_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        side_effect = _build_ejecutar_js_side_effect(nie_empty=True)

        with fase_3_patches(ejecutar_js={"side_effect": side_effect}):
            with pytest.raises(RuntimeError, match="NIE"):
                await fase_3(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_nombre_vacio_lanza_error(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        side_effect = _build_ejecutar_js_side_effect(nombre_empty=True)

        with fase_3_patches(ejecutar_js={"side_effect": side_effect}):
            with pytest.raises(RuntimeError, match="Nombre"):
                await fase_3(cdp, personalidad, raton, config)


# =========================================================================
# Fase 3 — Focus + click en botón Aceptar
# =========================================================================

class TestFase3BotonAceptar:
    @pytest.mark.asyncio
    async def test_focus_en_boton_antes_de_click(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        js_calls = []

        base_side_effect = _build_ejecutar_js_side_effect()

        async def tracking_js(cdp, expression, timeout=5.0):
            js_calls.append(expression.strip())
            return await base_side_effect(cdp, expression, timeout)

        with fase_3_patches(ejecutar_js={"side_effect": tracking_js}):
            await fase_3(cdp, personalidad, raton, config)

        focus_btn = [e for e in js_calls if "focus()" in e and "btnEnviar" in e]
        assert len(focus_btn) >= 1, "Debe hacer focus() en btnEnviar"

    @pytest.mark.asyncio
    async def test_pre_registra_evento_carga(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_3_patches():
            await fase_3(cdp, personalidad, raton, config)

        pre_wait_calls = cdp.pre_wait_event.call_args_list
        load_events = [c for c in pre_wait_calls if c[0][0] == "Page.loadEventFired"]
        assert len(load_events) >= 1

    @pytest.mark.asyncio
    async def test_espera_boton_antes_de_click(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        esperar_calls = []

        async def mock_esperar(cdp, selector, timeout=None):
            esperar_calls.append(selector)
            return {"x": 400, "y": 300, "width": 200, "height": 30}

        with fase_3_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_3(cdp, personalidad, raton, config)

        assert "#btnEnviar" in esperar_calls


# =========================================================================
# Fase 3 — Timeout
# =========================================================================

class TestFase3Timeout:
    @pytest.mark.asyncio
    async def test_timeout_carga_lanza_excepcion(self):
        cdp = _make_cdp_mock()
        cdp.wait_future = AsyncMock(side_effect=asyncio.TimeoutError())
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_3_patches():
            with pytest.raises(TimeoutCargaPagina, match="Página 3"):
                await fase_3(cdp, personalidad, raton, config)


# =========================================================================
# Fase 3 — No navega
# =========================================================================

class TestFase3NoNavega:
    @pytest.mark.asyncio
    async def test_no_hace_page_navigate(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_3_patches():
            await fase_3(cdp, personalidad, raton, config)

        send_calls = cdp.send.call_args_list
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        assert len(page_navigate) == 0


# =========================================================================
# Fase 3 — Aterrizaje
# =========================================================================

class TestFase3Aterrizaje:
    @pytest.mark.asyncio
    async def test_micro_movimientos_ejecutados(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        micro_calls = []

        async def mock_micro(*args, **kwargs):
            micro_calls.append(1)

        with fase_3_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_randint={"return_value": 2},
        ):
            await fase_3(cdp, personalidad, raton, config)

        assert len(micro_calls) >= 2


# =========================================================================
# Fase 3 — Disconnect mid-fase
# =========================================================================

class TestFase3Disconnect:
    @pytest.mark.asyncio
    async def test_esperar_elemento_falla_por_desconexion(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def esperar_falla(cdp, selector, timeout=None):
            raise ConnectionError("CDP disconnected")

        with fase_3_patches(esperar_elemento={"side_effect": esperar_falla}):
            with pytest.raises(ConnectionError):
                await fase_3(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_ejecutar_js_falla_en_focus(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_falla(cdp, expression, timeout=5.0):
            if "focus()" in expression and "txtIdCitado" in expression:
                raise ConnectionError("CDP gone during focus")
            return {}

        with fase_3_patches(ejecutar_js={"side_effect": js_falla}):
            with pytest.raises(ConnectionError, match="focus"):
                await fase_3(cdp, personalidad, raton, config)


# =========================================================================
# Fase 3 — Config inválida
# =========================================================================

class TestFase3ConfigInvalida:
    @pytest.mark.asyncio
    async def test_config_sin_input_nie_lanza_keyerror(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"ids": {"input_nombre": "txtDesCitado", "boton_aceptar_f4": "btnEnviar"}}

        with fase_3_patches():
            with pytest.raises(KeyError):
                await fase_3(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_config_sin_boton_lanza_keyerror(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"ids": {"input_nie": "txtIdCitado", "input_nombre": "txtDesCitado"}}

        with fase_3_patches():
            with pytest.raises(KeyError):
                await fase_3(cdp, personalidad, raton, config)


# =========================================================================
# Fase 3 — Orden de operaciones
# =========================================================================

class TestFase3OrdenOperaciones:
    @pytest.mark.asyncio
    async def test_orden_nie_luego_nombre_luego_boton(self):
        """Verifica el orden: NIE → Nombre → botón Aceptar."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        operations = []

        base_side_effect = _build_ejecutar_js_side_effect()

        async def tracking_js(cdp, expression, timeout=5.0):
            if "focus()" in expression:
                if "txtIdCitado" in expression:
                    operations.append("focus_nie")
                elif "txtDesCitado" in expression:
                    operations.append("focus_nombre")
                elif "btnEnviar" in expression:
                    operations.append("focus_boton")
            return await base_side_effect(cdp, expression, timeout)

        async def mock_click(cdp, x, y):
            operations.append("click")

        with fase_3_patches(
            ejecutar_js={"side_effect": tracking_js},
            _click_nativo={"side_effect": mock_click},
        ):
            await fase_3(cdp, personalidad, raton, config)

        # NIE focus debe ir antes que Nombre focus
        nie_idx = operations.index("focus_nie")
        nombre_idx = operations.index("focus_nombre")
        boton_idx = operations.index("focus_boton")

        assert nie_idx < nombre_idx, "NIE debe ir antes que Nombre"
        assert nombre_idx < boton_idx, "Nombre debe ir antes que botón"

    @pytest.mark.asyncio
    async def test_no_escribe_char_a_char(self):
        """No debe enviar teclas de caracteres, solo ArrowDown y Enter."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        with fase_3_patches(_enviar_tecla={"side_effect": mock_tecla}):
            await fase_3(cdp, personalidad, raton, config)

        # Solo ArrowDown y Enter, nada de caracteres
        for t in teclas:
            assert t in ("ArrowDown", "Enter"), f"Tecla inesperada: {t}"


# =========================================================================
# Fase 3 — End to end
# =========================================================================

class TestFase3EndToEnd:
    @pytest.mark.asyncio
    async def test_flujo_completo_sin_errores(self):
        cdp = _make_cdp_mock()
        raton = EstadoRaton()
        config = _make_config()

        for velocidad in ["rapido", "normal", "lento"]:
            with patch("humano.random.choice", return_value=velocidad):
                personalidad = Personalidad()

            with fase_3_patches():
                await fase_3(cdp, personalidad, raton, config)

    @pytest.mark.asyncio
    async def test_multiples_ejecuciones_no_acumulan_estado(self):
        config = _make_config()

        for i in range(3):
            cdp = _make_cdp_mock()
            personalidad = _make_personalidad_rapida()
            raton = EstadoRaton()

            with fase_3_patches():
                await fase_3(cdp, personalidad, raton, config)
