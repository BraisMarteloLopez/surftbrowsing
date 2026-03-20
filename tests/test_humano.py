"""Tests exhaustivos para humano.py — Primitivas, Personalidad, EstadoRaton."""

import asyncio
import random
from unittest.mock import AsyncMock, patch, call

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_core import CDPSession, TIMEOUT_JS
from humano import (
    Personalidad, EstadoRaton,
    _mover_raton, _mover_a_elemento, _click_nativo, _enviar_tecla,
    _scroll_exploratorio, _micro_movimiento, _movimientos_idle_durante_espera,
    PERSONALIDAD_FACTOR_RAPIDO, PERSONALIDAD_FACTOR_NORMAL, PERSONALIDAD_FACTOR_LENTO,
)


# =========================================================================
# Personalidad
# =========================================================================

class TestPersonalidad:
    def test_velocidad_es_valida(self):
        for _ in range(50):
            p = Personalidad()
            assert p.velocidad in ("rapido", "normal", "lento")

    def test_factor_corresponde_a_velocidad(self):
        with patch("humano.random.choice", return_value="rapido"):
            p = Personalidad()
            assert p.factor == PERSONALIDAD_FACTOR_RAPIDO

        with patch("humano.random.choice", return_value="normal"):
            p = Personalidad()
            assert p.factor == PERSONALIDAD_FACTOR_NORMAL

        with patch("humano.random.choice", return_value="lento"):
            p = Personalidad()
            assert p.factor == PERSONALIDAD_FACTOR_LENTO

    def test_nerviosismo_en_rango(self):
        for _ in range(50):
            p = Personalidad()
            assert 0.0 <= p.nerviosismo <= 1.0

    def test_atencion_en_rango(self):
        for _ in range(50):
            p = Personalidad()
            assert 0.5 <= p.atencion <= 1.0

    def test_delay_modulado_por_factor_rapido(self):
        with patch("humano.random.choice", return_value="rapido"):
            p = Personalidad()
        # Con factor 0.6, delay(1.0, 3.0) → uniform(0.6, 1.8)
        for _ in range(100):
            d = p.delay(1.0, 3.0)
            assert 0.6 * 0.99 <= d <= 1.8 * 1.01  # tolerancia float

    def test_delay_modulado_por_factor_lento(self):
        with patch("humano.random.choice", return_value="lento"):
            p = Personalidad()
        # Con factor 1.5, delay(1.0, 3.0) → uniform(1.5, 4.5)
        for _ in range(100):
            d = p.delay(1.0, 3.0)
            assert 1.5 * 0.99 <= d <= 4.5 * 1.01

    def test_repr_contiene_velocidad(self):
        p = Personalidad()
        r = repr(p)
        assert "velocidad=" in r
        assert p.velocidad in r


# =========================================================================
# EstadoRaton
# =========================================================================

class TestEstadoRaton:
    def test_posicion_inicial_en_rango(self):
        for _ in range(50):
            r = EstadoRaton()
            assert 200 <= r.x <= 600
            assert 150 <= r.y <= 400

    def test_posicion_mutable(self):
        r = EstadoRaton()
        r.x = 999
        r.y = 888
        assert r.x == 999
        assert r.y == 888


# =========================================================================
# _mover_raton
# =========================================================================

class TestMoverRaton:
    @pytest.mark.asyncio
    async def test_actualiza_posicion_raton(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 100, 100

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=20):
                await _mover_raton(cdp, raton, 500, 400, duracion=0.01)

        assert raton.x == 500
        assert raton.y == 400

    @pytest.mark.asyncio
    async def test_envia_eventos_mouseMoved(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 0, 0

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=15):
                await _mover_raton(cdp, raton, 100, 100, duracion=0.01)

        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) >= 15  # al menos 15 pasos
        for c in mouse_calls:
            assert c[0][1]["type"] == "mouseMoved"

    @pytest.mark.asyncio
    async def test_coordenadas_nunca_negativas(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 5, 5  # Cerca de 0

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=15):
                await _mover_raton(cdp, raton, 3, 3, duracion=0.01)

        for c in cdp.send.call_args_list:
            if c[0][0] == "Input.dispatchMouseEvent":
                assert c[0][1]["x"] >= 0
                assert c[0][1]["y"] >= 0

    @pytest.mark.asyncio
    async def test_tolerante_a_excepciones_cdp(self):
        """Si un envío CDP falla, no crashea — rompe el loop silenciosamente."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=ConnectionError("lost"))
        raton = EstadoRaton()
        raton.x, raton.y = 0, 0

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=15):
                await _mover_raton(cdp, raton, 100, 100, duracion=0.01)
        # No debería lanzar excepción
        assert raton.x == 100


# =========================================================================
# _mover_a_elemento
# =========================================================================

class TestMoverAElemento:
    @pytest.mark.asyncio
    async def test_mueve_al_centro_del_elemento(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 100, 100

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano._mover_raton", new_callable=AsyncMock):
                with patch("humano.random.random", return_value=0.5):  # no overshoot
                    with patch("humano.random.randint", return_value=0):  # no jitter
                        with patch("humano.random.uniform", return_value=0.5):
                            result = await _mover_a_elemento(cdp, raton, "#form",
                                                             Personalidad())

        assert "x" in result
        assert "y" in result

    @pytest.mark.asyncio
    async def test_overshoot_cuando_probabilidad_alta(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 100, 100

        mover_calls = []

        async def mock_mover(cdp, raton, x, y, duracion=0.5):
            mover_calls.append((x, y))
            raton.x, raton.y = x, y

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano._mover_raton", side_effect=mock_mover):
                with patch("humano.random.random", return_value=0.0):  # forzar overshoot
                    with patch("humano.random.randint", return_value=20):
                        with patch("humano.random.uniform", return_value=0.5):
                            with patch("humano.asyncio.sleep", new_callable=AsyncMock):
                                await _mover_a_elemento(cdp, raton, "#form",
                                                        Personalidad())

        # Con overshoot, debe haber 2 movimientos (overshoot + corrección)
        assert len(mover_calls) == 2

    @pytest.mark.asyncio
    async def test_sin_overshoot_un_solo_movimiento(self):
        cdp = AsyncMock(spec=CDPSession)
        raton = EstadoRaton()
        raton.x, raton.y = 100, 100

        mover_calls = []

        async def mock_mover(cdp, raton, x, y, duracion=0.5):
            mover_calls.append((x, y))
            raton.x, raton.y = x, y

        with patch("humano.esperar_elemento", new_callable=AsyncMock,
                    return_value={"x": 400, "y": 300, "width": 200, "height": 30}):
            with patch("humano._mover_raton", side_effect=mock_mover):
                with patch("humano.random.random", return_value=0.99):  # no overshoot
                    with patch("humano.random.randint", return_value=0):
                        with patch("humano.random.uniform", return_value=0.5):
                            await _mover_a_elemento(cdp, raton, "#form",
                                                    Personalidad())

        assert len(mover_calls) == 1


# =========================================================================
# _click_nativo
# =========================================================================

class TestClickNativo:
    @pytest.mark.asyncio
    async def test_envia_pressed_y_released(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=100):
                await _click_nativo(cdp, 400, 300)

        calls = cdp.send.call_args_list
        tipos = [c[0][1]["type"] for c in calls if c[0][0] == "Input.dispatchMouseEvent"]
        assert tipos == ["mousePressed", "mouseReleased"]

    @pytest.mark.asyncio
    async def test_coordenadas_correctas(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=100):
                await _click_nativo(cdp, 123, 456)

        for c in cdp.send.call_args_list:
            if c[0][0] == "Input.dispatchMouseEvent":
                assert c[0][1]["x"] == 123
                assert c[0][1]["y"] == 456
                assert c[0][1]["button"] == "left"

    @pytest.mark.asyncio
    async def test_pausa_entre_press_y_release(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        sleep_calls = []
        original_sleep = asyncio.sleep

        async def mock_sleep(t):
            sleep_calls.append(t)

        with patch("humano.asyncio.sleep", side_effect=mock_sleep):
            with patch("humano.random.randint", return_value=100):
                await _click_nativo(cdp, 0, 0)

        # Debe haber un sleep entre press y release
        assert len(sleep_calls) == 1
        assert 0.04 <= sleep_calls[0] <= 0.16  # 50-150ms


# =========================================================================
# _enviar_tecla
# =========================================================================

class TestEnviarTecla:
    @pytest.mark.asyncio
    async def test_envia_keydown_y_keyup(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.uniform", return_value=0.03):
                await _enviar_tecla(cdp, "ArrowDown")

        calls = cdp.send.call_args_list
        key_calls = [c for c in calls if c[0][0] == "Input.dispatchKeyEvent"]
        assert len(key_calls) == 2
        assert key_calls[0][0][1]["type"] == "keyDown"
        assert key_calls[1][0][1]["type"] == "keyUp"

    @pytest.mark.asyncio
    async def test_key_arrow_down(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.uniform", return_value=0.03):
                await _enviar_tecla(cdp, "ArrowDown")

        for c in cdp.send.call_args_list:
            if c[0][0] == "Input.dispatchKeyEvent":
                assert c[0][1]["key"] == "ArrowDown"

    @pytest.mark.asyncio
    async def test_key_enter(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.uniform", return_value=0.03):
                await _enviar_tecla(cdp, "Enter")

        key_calls = [c for c in cdp.send.call_args_list
                     if c[0][0] == "Input.dispatchKeyEvent"]
        assert key_calls[0][0][1]["key"] == "Enter"
        assert key_calls[0][0][1]["code"] == "Enter"


# =========================================================================
# _scroll_exploratorio
# =========================================================================

class TestScrollExploratorio:
    @pytest.mark.asyncio
    async def test_envia_mousewheel_events(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 400, 300

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=2):
                with patch("humano.random.uniform", return_value=0.1):
                    await _scroll_exploratorio(cdp, raton, 50, 150)

        wheel_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"
                       and c[0][1].get("type") == "mouseWheel"]
        assert len(wheel_calls) >= 2

    @pytest.mark.asyncio
    async def test_micro_movimientos_entre_scrolls(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 400, 300

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=3):
                with patch("humano.random.uniform", return_value=0.1):
                    await _scroll_exploratorio(cdp, raton, 50, 150)

        moved_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"
                       and c[0][1].get("type") == "mouseMoved"]
        assert len(moved_calls) >= 1  # micro-movimientos entre pasos

    @pytest.mark.asyncio
    async def test_tolerante_a_errores_cdp(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=Exception("fail"))
        raton = EstadoRaton()

        with patch("humano.asyncio.sleep", new_callable=AsyncMock):
            with patch("humano.random.randint", return_value=2):
                with patch("humano.random.uniform", return_value=0.1):
                    # No debería crashear
                    await _scroll_exploratorio(cdp, raton, 50, 150)


# =========================================================================
# _micro_movimiento
# =========================================================================

class TestMicroMovimiento:
    @pytest.mark.asyncio
    async def test_mueve_dentro_del_rango(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 400, 300

        destinos = []

        async def mock_mover(cdp, raton, x, y, duracion=0.5):
            destinos.append((x, y))
            raton.x, raton.y = x, y

        with patch("humano._mover_raton", side_effect=mock_mover):
            with patch("humano.random.uniform", return_value=0.2):
                await _micro_movimiento(cdp, raton, 20, 20, 0.1, 0.3)

        assert len(destinos) == 1
        x, y = destinos[0]
        # Destino debe estar dentro de ±20 del original
        assert 380 <= x <= 420
        assert 280 <= y <= 320

    @pytest.mark.asyncio
    async def test_coordenadas_nunca_negativas(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        raton.x, raton.y = 5, 5

        destinos = []

        async def mock_mover(cdp, raton, x, y, duracion=0.5):
            destinos.append((x, y))
            raton.x, raton.y = x, y

        with patch("humano._mover_raton", side_effect=mock_mover):
            with patch("humano.random.randint", return_value=-50):
                with patch("humano.random.uniform", return_value=0.2):
                    await _micro_movimiento(cdp, raton, 80, 80, 0.1, 0.3)

        x, y = destinos[0]
        assert x >= 0
        assert y >= 0


# =========================================================================
# _movimientos_idle_durante_espera
# =========================================================================

class TestMovimientosIdleDuranteEspera:
    @pytest.mark.asyncio
    async def test_se_detiene_cuando_evento_se_activa(self):
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        raton = EstadoRaton()
        fin = asyncio.Event()

        with patch("humano._micro_movimiento", new_callable=AsyncMock):
            with patch("humano.random.uniform", return_value=0.01):
                tarea = asyncio.create_task(
                    _movimientos_idle_durante_espera(cdp, raton, fin)
                )
                await asyncio.sleep(0.05)
                fin.set()
                await asyncio.sleep(0.05)

        assert tarea.done()

    @pytest.mark.asyncio
    async def test_no_ejecuta_si_evento_ya_activo(self):
        cdp = AsyncMock(spec=CDPSession)
        raton = EstadoRaton()
        fin = asyncio.Event()
        fin.set()

        micro_mock = AsyncMock()
        with patch("humano._micro_movimiento", micro_mock):
            with patch("humano.random.uniform", return_value=0.01):
                await _movimientos_idle_durante_espera(cdp, raton, fin)

        micro_mock.assert_not_called()
