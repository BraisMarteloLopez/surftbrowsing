"""Tests exhaustivos para fase_0 — flujo completo de Página 0."""

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

        # WAF detection (body text)
        if "document.body.innerText" in expr:
            return {"value": "Sede Electrónica"}

        return {}

    return side_effect


@contextmanager
def fase_0_patches(**overrides):
    """Aplica todos los patches comunes para fase_0 tests.

    Keyword arguments override the default mocks:
        esperar_elemento, detectar_waf, ejecutar_js, _mover_raton,
        sleep, _enviar_tecla, _click_nativo, _micro_movimiento,
        _scroll_exploratorio, random_random, random_randint
    """
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

    # Apply overrides
    for key, val in overrides.items():
        if isinstance(val, dict):
            defaults[key] = val
        else:
            # Shortcut: pass a callable or value directly
            if callable(val) and not isinstance(val, AsyncMock):
                defaults[key] = {"side_effect": val}
            else:
                defaults[key] = {"return_value": val}

    patches = {}
    # Map key → patch target
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
        for key in targets:
            patch.stopall()
            break  # stopall stops everything


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

        with fase_0_patches():
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        send_calls = cdp.send.call_args_list
        page_navigate = [c for c in send_calls if c[0][0] == "Page.navigate"]
        # Page.enable is called once in conectar_navegador, not per-phase
        page_enable = [c for c in send_calls if c[0][0] == "Page.enable"]
        assert len(page_enable) == 0
        assert len(page_navigate) == 1
        assert page_navigate[0][0][1]["url"] == config["url_inicio"]

    @pytest.mark.asyncio
    async def test_no_navega_en_reintento(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_0_patches():
            await fase_0(cdp, personalidad, raton, es_primera_vez=False, config=config)

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

        with fase_0_patches(detectar_waf={"new_callable": AsyncMock, "return_value": True}):
            with pytest.raises(WafBanError, match="WAF detectado en Página 0"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

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

        with fase_0_patches(detectar_waf={"side_effect": waf_side_effect}):
            with pytest.raises(WafBanError, match="tras envío"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)


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

        with fase_0_patches(_enviar_tecla={"side_effect": mock_enviar_tecla}):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

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

        with fase_0_patches(ejecutar_js={"side_effect": js_sin_madrid}):
            with pytest.raises(ElementoNoEncontrado, match="Madrid"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_verificacion_fallida_reintenta_con_teclado(self):
        """Si la verificación post-selección falla, reintenta via teclado."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        teclas_enviadas = []
        original_enviar = AsyncMock()

        async def tracking_tecla(cdp, key):
            teclas_enviadas.append(key)

        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["Barcelona", "Madrid"]
        )

        with fase_0_patches(
            ejecutar_js={"side_effect": side_effect},
            _enviar_tecla={"side_effect": tracking_tecla},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        # Should have used keyboard (ArrowDown/ArrowUp + Enter) for retry
        assert "Enter" in teclas_enviadas, (
            f"Expected keyboard retry with Enter. Keys sent: {teclas_enviadas}"
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

        with fase_0_patches(ejecutar_js={"side_effect": side_effect}):
            with pytest.raises(RuntimeError, match="2 intentos"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_provincia_objetivo_configurable(self):
        """config['provincia_objetivo'] cambia la provincia buscada."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()
        config["provincia_objetivo"] = "Valencia"

        # Valencia está en index 3
        side_effect = _build_ejecutar_js_side_effect(
            verification_results=["Valencia"]
        )

        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        with fase_0_patches(
            ejecutar_js={"side_effect": side_effect},
            _enviar_tecla={"side_effect": mock_tecla},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        # Exploratory scrolls (1 iter × 1 arrow) + navigation to index 3 = 3 ArrowDowns
        arrow_downs = [t for t in teclas if t == "ArrowDown"]
        assert len(arrow_downs) >= 3


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

        with fase_0_patches(esperar_elemento={"side_effect": mock_esperar}):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

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

        with fase_0_patches(esperar_elemento={"side_effect": esperar_falla}):
            with pytest.raises(ElementoNoEncontrado):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)


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

        with fase_0_patches(_click_nativo={"side_effect": mock_click}):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        # Debe haber al menos 2 clicks: uno en #form y otro en #btnAceptar
        assert len(clicks) >= 2

    @pytest.mark.asyncio
    async def test_pre_registra_evento_carga_antes_del_click(self):
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_0_patches():
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        pre_wait_calls = cdp.pre_wait_event.call_args_list
        load_events = [c for c in pre_wait_calls if c[0][0] == "Page.loadEventFired"]
        assert len(load_events) >= 1

    @pytest.mark.asyncio
    async def test_timeout_carga_tras_click_lanza_excepcion(self):
        cdp = _make_cdp_mock()
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

        with fase_0_patches():
            with pytest.raises(TimeoutCargaPagina):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)


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

        with fase_0_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_randint={"return_value": 2},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

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

        with fase_0_patches(
            _scroll_exploratorio={"side_effect": mock_scroll},
            # random.random=0.1 < SCROLL_PROB=0.30 → scroll happens
            random_random={"return_value": 0.1},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

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
        with fase_0_patches(
            _micro_movimiento={"side_effect": mock_micro},
            random_random={"return_value": 0.1},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        # micro-movimientos: aterrizaje (1) + transición idle (1) = at least 2
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

            with fase_0_patches():
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_multiples_ejecuciones_no_acumulan_estado(self):
        """Ejecutar fase_0 varias veces no causa problemas de estado."""
        config = _make_config()

        for i in range(3):
            cdp = _make_cdp_mock()
            personalidad = _make_personalidad_rapida()
            raton = EstadoRaton()

            with fase_0_patches():
                await fase_0(cdp, personalidad, raton,
                             es_primera_vez=(i == 0), config=config)


# =========================================================================
# Fase 0 — Robustez: configuración inválida y edge cases
# =========================================================================

class TestFase0ConfigInvalida:
    @pytest.mark.asyncio
    async def test_config_sin_ids_lanza_keyerror(self):
        """Config sin 'ids' debe fallar con KeyError."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"url_inicio": "https://example.com"}

        with fase_0_patches():
            with pytest.raises(KeyError):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_config_sin_url_inicio_lanza_keyerror(self):
        """Config sin 'url_inicio' debe fallar con KeyError."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {"ids": {"dropdown_provincia": "form", "valor_madrid": "x", "boton_aceptar_f1": "btn"}}

        with fase_0_patches():
            with pytest.raises(KeyError):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_config_ids_incompletos_lanza_keyerror(self):
        """Config sin 'boton_aceptar_f1' debe fallar."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = {
            "url_inicio": "https://example.com",
            "ids": {"dropdown_provincia": "form", "valor_madrid": "x"},
        }

        with fase_0_patches():
            with pytest.raises(KeyError):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)


class TestFase0DisconnectMidFase:
    @pytest.mark.asyncio
    async def test_cdp_send_falla_en_navegacion(self):
        """Si cdp.send falla durante Page.navigate, la excepción se propaga."""
        cdp = _make_cdp_mock()
        cdp.send = AsyncMock(side_effect=ConnectionError("CDP disconnected"))
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_0_patches():
            with pytest.raises(ConnectionError):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_wait_future_falla_en_navegacion(self):
        """Si wait_future falla en la primera llamada (navegación), se propaga."""
        cdp = _make_cdp_mock()
        cdp.wait_future = AsyncMock(side_effect=ConnectionError("CDP lost"))
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_0_patches():
            with pytest.raises(ConnectionError):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_ejecutar_js_falla_en_focus(self):
        """Si ejecutar_js falla al hacer focus, la excepción se propaga."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_falla_focus(cdp, expression, timeout=5.0):
            if "focus()" in expression:
                raise ConnectionError("CDP gone during focus")
            return {}

        with fase_0_patches(ejecutar_js={"side_effect": js_falla_focus}):
            with pytest.raises(ConnectionError, match="focus"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)


class TestFase0TimeoutEdgeCases:
    @pytest.mark.asyncio
    async def test_esperar_elemento_timeout_en_reintento(self):
        """En reintento (no primera vez), si esperar_elemento falla → excepción."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def esperar_timeout(cdp, selector, timeout=None):
            raise ElementoNoEncontrado(f"{selector} timeout")

        with fase_0_patches(esperar_elemento={"side_effect": esperar_timeout}):
            with pytest.raises(ElementoNoEncontrado):
                await fase_0(cdp, personalidad, raton, es_primera_vez=False, config=config)

    @pytest.mark.asyncio
    async def test_options_vacias_lanza_error(self):
        """Si el <select> no tiene opciones, debe lanzar ElementoNoEncontrado."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_options_vacias(cdp, expression, timeout=5.0):
            if "opts.push" in expression:
                return {"value": {"options": [], "currentIndex": 0}}
            if "focus()" in expression:
                return {}
            return {}

        with fase_0_patches(ejecutar_js={"side_effect": js_options_vacias}):
            with pytest.raises(ElementoNoEncontrado, match="Madrid"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_ejecutar_js_retorna_none_value(self):
        """Si ejecutar_js retorna value=None para options, no crashea."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        async def js_none_value(cdp, expression, timeout=5.0):
            if "opts.push" in expression:
                return {}  # No "value" key
            if "focus()" in expression:
                return {}
            return {}

        with fase_0_patches(ejecutar_js={"side_effect": js_none_value}):
            with pytest.raises(ElementoNoEncontrado, match="Madrid"):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

    @pytest.mark.asyncio
    async def test_idle_task_cancelada_en_timeout(self):
        """Tras TimeoutCargaPagina, la tarea idle debe cancelarse correctamente."""
        cdp = _make_cdp_mock()
        call_count = [0]

        async def wait_future_timeout(fut, timeout=None):
            call_count[0] += 1
            if call_count[0] <= 1:
                return {"method": "Page.loadEventFired"}
            raise asyncio.TimeoutError()

        cdp.wait_future = AsyncMock(side_effect=wait_future_timeout)
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        with fase_0_patches():
            with pytest.raises(TimeoutCargaPagina):
                await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        # No queda tarea pendiente (verificar que no hay warning de tarea no awaited)
        # Si llegamos aquí sin errores, la limpieza fue correcta.


class TestFase0SelectNavigation:
    @pytest.mark.asyncio
    async def test_madrid_ya_seleccionado_no_envia_arrows(self):
        """Si Madrid ya está seleccionado (currentIndex==2), no hace ArrowDown de navegación."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        madrid_already_selected = {
            "value": {
                "options": [
                    {"index": 0, "text": "Seleccione..."},
                    {"index": 1, "text": "Barcelona"},
                    {"index": 2, "text": "Madrid"},
                ],
                "currentIndex": 2,
            }
        }

        async def js_madrid_already(cdp, expression, timeout=5.0):
            if "opts.push" in expression:
                return madrid_already_selected
            if "focus()" in expression:
                return {}
            if "sel.options[sel.selectedIndex]" in expression and "textContent" in expression:
                return {"value": "Madrid"}
            if "dispatchEvent" in expression:
                return {}
            return {}

        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        with fase_0_patches(
            ejecutar_js={"side_effect": js_madrid_already},
            _enviar_tecla={"side_effect": mock_tecla},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        # Exploratory arrows (1 iter × 1 arrow) + 0 navigation arrows + Enter
        nav_arrows = [t for t in teclas if t in ("ArrowDown", "ArrowUp")]
        # Only the exploratory scroll arrows, no additional navigation ones
        # With randint=1: 1 iter × 1 arrow = 1 exploratory ArrowDown
        # + 0 navigation arrows (already at Madrid)
        enters = [t for t in teclas if t == "Enter"]
        assert len(enters) == 1
        # Total arrows should be just the exploratory ones (1)
        assert len(nav_arrows) == 1

    @pytest.mark.asyncio
    async def test_arrowup_cuando_target_antes_de_current(self):
        """Si target < current, debe usar ArrowUp en vez de ArrowDown."""
        cdp = _make_cdp_mock()
        personalidad = _make_personalidad_rapida()
        raton = EstadoRaton()
        config = _make_config()

        # Current at Valencia (3), Madrid at 2 → need ArrowUp
        options_at_valencia = {
            "value": {
                "options": [
                    {"index": 0, "text": "Seleccione..."},
                    {"index": 1, "text": "Barcelona"},
                    {"index": 2, "text": "Madrid"},
                    {"index": 3, "text": "Valencia"},
                ],
                "currentIndex": 3,
            }
        }

        async def js_at_valencia(cdp, expression, timeout=5.0):
            if "opts.push" in expression:
                return options_at_valencia
            if "focus()" in expression:
                return {}
            if "sel.options[sel.selectedIndex]" in expression and "textContent" in expression:
                return {"value": "Madrid"}
            if "dispatchEvent" in expression:
                return {}
            return {}

        teclas = []

        async def mock_tecla(cdp, key):
            teclas.append(key)

        with fase_0_patches(
            ejecutar_js={"side_effect": js_at_valencia},
            _enviar_tecla={"side_effect": mock_tecla},
        ):
            await fase_0(cdp, personalidad, raton, es_primera_vez=True, config=config)

        arrow_ups = [t for t in teclas if t == "ArrowUp"]
        assert len(arrow_ups) >= 1  # Al menos 1 ArrowUp para ir de 3→2
