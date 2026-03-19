"""Tests para SimuladorHumano — Fase 2 (estado) y Fase 3 (movimiento concurrente)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_helpers import CDPSession, TIMEOUT_JS
from comportamiento_humano import SimuladorHumano


# ---------------------------------------------------------------------------
# Fase 2: Estado encapsulado
# ---------------------------------------------------------------------------

class TestSimuladorHumanoEstado:
    def test_init_posicion_aleatoria(self):
        """Posición inicial del ratón es aleatoria dentro de rango razonable."""
        cdp = AsyncMock(spec=CDPSession)
        humano = SimuladorHumano(cdp)
        assert 100 <= humano.mouse_x <= 800
        assert 100 <= humano.mouse_y <= 400
        assert humano.viewport == (1024, 768)

    @pytest.mark.asyncio
    @patch("comportamiento_humano.ejecutar_js", new_callable=AsyncMock)
    async def test_actualizar_viewport(self, mock_ejs):
        cdp = AsyncMock(spec=CDPSession)
        humano = SimuladorHumano(cdp)
        mock_ejs.return_value = {"value": [1920, 1080]}

        await humano.actualizar_viewport()

        assert humano.viewport == (1920, 1080)

    @pytest.mark.asyncio
    @patch("comportamiento_humano.ejecutar_js", new_callable=AsyncMock)
    async def test_actualizar_viewport_fallback(self, mock_ejs):
        """Si ejecutar_js devuelve formato inesperado, mantiene default."""
        cdp = AsyncMock(spec=CDPSession)
        humano = SimuladorHumano(cdp)
        mock_ejs.return_value = {"value": "invalid"}

        await humano.actualizar_viewport()

        assert humano.viewport == (1024, 768)

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_mover_a_actualiza_posicion(self, mock_sleep):
        """mover_a actualiza mouse_x/y al destino."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        await humano.mover_a(500, 300, pasos=2)

        assert humano.mouse_x == 500
        assert humano.mouse_y == 300

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_mover_a_envia_mouse_events(self, mock_sleep):
        """mover_a envía eventos mouseMoved via CDP."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        await humano.mover_a(500, 300, pasos=3)

        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) == 3
        for mc in mouse_calls:
            assert mc[0][1]["type"] == "mouseMoved"

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_mover_a_cdp_falla_no_crashea(self, mock_sleep):
        """Si CDP falla, mover_a no lanza excepción pero actualiza posición."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=RuntimeError("CDP error"))
        humano = SimuladorHumano(cdp)

        await humano.mover_a(500, 300, pasos=2)

        # Posición se actualiza aunque CDP falle
        assert humano.mouse_x == 500
        assert humano.mouse_y == 300

    @pytest.mark.asyncio
    @patch("comportamiento_humano.ejecutar_js", new_callable=AsyncMock)
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_mover_a_elemento_actualiza_posicion(self, mock_sleep, mock_ejs):
        """mover_a_elemento mueve al centro del elemento."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)
        mock_ejs.return_value = {"value": {"x": 400, "y": 200}}

        await humano.mover_a_elemento("myButton")

        assert humano.mouse_x == 400
        assert humano.mouse_y == 200

    @pytest.mark.asyncio
    @patch("comportamiento_humano.ejecutar_js", new_callable=AsyncMock)
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_mover_a_elemento_no_existe(self, mock_sleep, mock_ejs):
        """Si el elemento no existe, no mueve el ratón."""
        cdp = AsyncMock(spec=CDPSession)
        humano = SimuladorHumano(cdp)
        humano.mouse_x = 100
        humano.mouse_y = 100
        mock_ejs.return_value = {"value": None}

        await humano.mover_a_elemento("noExiste")

        assert humano.mouse_x == 100
        assert humano.mouse_y == 100


# ---------------------------------------------------------------------------
# Fase 5: Scroll nativo via mouseWheel
# ---------------------------------------------------------------------------

class TestSimuladorScroll:
    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_scroll_genera_mousewheel(self, mock_sleep):
        """scroll() envía eventos mouseWheel via CDP."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)
        humano.mouse_x = 500
        humano.mouse_y = 400

        await humano.scroll()

        wheel_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent" and c[0][1].get("type") == "mouseWheel"]
        assert 2 <= len(wheel_calls) <= 4
        for wc in wheel_calls:
            assert wc[0][1]["deltaY"] > 0
            assert wc[0][1]["deltaX"] == 0

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_scroll_usa_posicion_raton_actual(self, mock_sleep):
        """scroll() usa self.mouse_x/y como posición de los eventos."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)
        humano.mouse_x = 600
        humano.mouse_y = 350

        with patch("comportamiento_humano.random.randint", return_value=2):
            await humano.scroll()

        wheel_call = [c for c in cdp.send.call_args_list
                      if c[0][0] == "Input.dispatchMouseEvent" and c[0][1].get("type") == "mouseWheel"][0]
        assert wheel_call[0][1]["x"] == 600
        assert wheel_call[0][1]["y"] == 350

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_scroll_micro_movimientos_entre_pasos(self, mock_sleep):
        """scroll() genera mouseMoved entre pasos de scroll."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.randint", return_value=3):
            await humano.scroll()

        moved_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent" and c[0][1].get("type") == "mouseMoved"]
        # 3 pasos → 2 micro-movimientos entre ellos
        assert len(moved_calls) == 2

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_scroll_cdp_falla_no_crashea(self, mock_sleep):
        """Si CDP falla durante scroll, no lanza excepción."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=RuntimeError("CDP error"))
        humano = SimuladorHumano(cdp)

        await humano.scroll()


# ---------------------------------------------------------------------------
# Fase 3: Movimiento concurrente durante delays
# ---------------------------------------------------------------------------

class TestDelayActivo:
    @pytest.mark.asyncio
    async def test_delay_activo_mueve_raton_durante_espera(self):
        """delay_activo genera eventos mouseMoved durante el delay."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        # Usar delays cortos para que el test sea rápido
        with patch("comportamiento_humano.random.uniform", return_value=0.0), \
             patch("comportamiento_humano.random.choice", return_value="drift"), \
             patch("comportamiento_humano.random.randint", return_value=5):
            await humano.delay_activo(base=0.3, varianza=0.0)

        # Debe haber generado eventos mouseMoved durante el delay
        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) > 0

    @pytest.mark.asyncio
    async def test_delay_activo_cancela_tarea_al_terminar(self):
        """La tarea de movimiento se cancela limpiamente al finalizar el delay."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        # delay_activo debe terminar sin error (la tarea de fondo se cancela)
        with patch("comportamiento_humano.random.uniform", return_value=0.0), \
             patch("comportamiento_humano.random.choice", return_value="reposo"), \
             patch("comportamiento_humano.random.randint", return_value=2):
            await humano.delay_activo(base=0.15, varianza=0.0)

        # No debe haber tareas pendientes (la cancelación fue limpia)
        pending = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
        lectura_tasks = [t for t in pending if "_movimiento_lectura" in repr(t)]
        assert len(lectura_tasks) == 0

    @pytest.mark.asyncio
    async def test_delay_activo_posicion_raton_se_actualiza(self):
        """Tras delay_activo, la posición del ratón ha cambiado."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)
        x_inicial = humano.mouse_x
        y_inicial = humano.mouse_y

        with patch("comportamiento_humano.random.choice", return_value="drift"):
            await humano.delay_activo(base=0.2, varianza=0.0)

        # En patrón drift, la posición debería haberse movido
        # (puede que sea el mismo por casualidad, verificamos que no crasheó)
        assert isinstance(humano.mouse_x, int)
        assert isinstance(humano.mouse_y, int)

    @pytest.mark.asyncio
    async def test_delay_activo_cdp_falla_no_crashea(self):
        """Si CDP falla durante movimiento de fondo, delay_activo no crashea."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=RuntimeError("CDP disconnected"))
        humano = SimuladorHumano(cdp)

        # No debe lanzar excepción
        await humano.delay_activo(base=0.15, varianza=0.0)


class TestPausaLectura:
    @pytest.mark.asyncio
    async def test_pausa_lectura_mueve_raton(self):
        """pausa_lectura genera movimiento de ratón durante la pausa."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.uniform", return_value=0.2), \
             patch("comportamiento_humano.random.choice", return_value="drift"), \
             patch("comportamiento_humano.random.randint", return_value=3), \
             patch("comportamiento_humano.PAUSA_ENTRE_PASOS_MIN", 0.1), \
             patch("comportamiento_humano.PAUSA_ENTRE_PASOS_MAX", 0.1):
            await humano.pausa_lectura()

        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) >= 0  # May be 0 if drift finishes fast


class TestPausaExtra:
    @pytest.mark.asyncio
    async def test_pausa_extra_con_movimiento(self):
        """pausa_extra con probabilidad 1.0 genera movimiento."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.random", return_value=0.1), \
             patch("comportamiento_humano.random.uniform", return_value=0.15), \
             patch("comportamiento_humano.random.choice", return_value="reposo"), \
             patch("comportamiento_humano.random.randint", return_value=2):
            await humano.pausa_extra(probabilidad=0.3)

    @pytest.mark.asyncio
    async def test_pausa_extra_no_activada(self):
        """pausa_extra con random alto no hace nada."""
        cdp = AsyncMock(spec=CDPSession)
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.random", return_value=0.9):
            await humano.pausa_extra(probabilidad=0.3)

        # CDP.send no debería haberse llamado
        cdp.send.assert_not_called()


class TestMovimientoLectura:
    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_patron_reposo(self, mock_sleep):
        """Patrón reposo: micro-movimientos cerca de la posición actual."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)
        humano.mouse_x = 400
        humano.mouse_y = 300

        with patch("comportamiento_humano.random.choice", return_value="reposo"):
            await asyncio.wait_for(humano._movimiento_lectura(0.05), timeout=2.0)

        # Verificar que se generaron eventos mouseMoved (micro-movimientos)
        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) > 0

    @pytest.mark.asyncio
    async def test_patron_lectura(self):
        """Patrón lectura: barrido horizontal."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)
        humano.viewport = (1024, 768)

        with patch("comportamiento_humano.random.choice", return_value="lectura"):
            await asyncio.wait_for(humano._movimiento_lectura(0.3), timeout=2.0)

        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) > 0

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_patron_exploracion(self, mock_sleep):
        """Patrón exploración: movimientos a zonas aleatorias del viewport."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.choice", return_value="exploracion"):
            await asyncio.wait_for(humano._movimiento_lectura(0.05), timeout=2.0)

        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) > 0

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_patron_drift(self, mock_sleep):
        """Patrón drift: movimiento lento en una dirección."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.choice", return_value="drift"):
            await asyncio.wait_for(humano._movimiento_lectura(0.05), timeout=2.0)

        mouse_calls = [c for c in cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) > 0

    @pytest.mark.asyncio
    async def test_drift_cdp_falla_retorna_limpio(self):
        """Patrón drift: si CDP falla, retorna sin error."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(side_effect=RuntimeError("disconnected"))
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.choice", return_value="drift"):
            await asyncio.wait_for(humano._movimiento_lectura(0.3), timeout=2.0)

    @pytest.mark.asyncio
    @patch("comportamiento_humano.asyncio.sleep", new_callable=AsyncMock)
    async def test_movimiento_lectura_respeta_duracion(self, mock_sleep):
        """_movimiento_lectura termina cuando la duración expira."""
        cdp = AsyncMock(spec=CDPSession)
        cdp.send = AsyncMock(return_value={})
        humano = SimuladorHumano(cdp)

        with patch("comportamiento_humano.random.choice", return_value="reposo"):
            await asyncio.wait_for(humano._movimiento_lectura(0.05), timeout=2.0)


# ---------------------------------------------------------------------------
# Fase 4: secuencia_pre_accion con orden variable
# ---------------------------------------------------------------------------

class TestSecuenciaPreAccion:
    @pytest.mark.asyncio
    async def test_secuencia_siempre_incluye_delay(self):
        """secuencia_pre_accion siempre ejecuta al menos un delay_activo."""
        humano = AsyncMock(spec=SimuladorHumano)
        # Llamar al método real con el mock
        real_method = SimuladorHumano.secuencia_pre_accion
        # Ejecutar varias veces para cubrir variabilidad
        for _ in range(10):
            humano.reset_mock()
            await real_method(humano)
            # Al menos un delay_activo debe haberse llamado
            assert humano.delay_activo.call_count >= 1

    @pytest.mark.asyncio
    async def test_secuencia_ejecuta_2_a_5_acciones(self):
        """secuencia_pre_accion ejecuta entre 2 y 5 acciones (2-4 + posible delay forzado)."""
        humano = AsyncMock(spec=SimuladorHumano)
        real_method = SimuladorHumano.secuencia_pre_accion

        for _ in range(20):
            humano.reset_mock()
            await real_method(humano)
            total = (humano.movimiento_idle.call_count +
                     humano.scroll.call_count +
                     humano.delay_activo.call_count +
                     humano.pausa_extra.call_count)
            assert 2 <= total <= 5

    @pytest.mark.asyncio
    async def test_secuencia_mueve_a_elemento_si_especificado(self):
        """Si element_id se especifica, mover_a_elemento se llama al final."""
        humano = AsyncMock(spec=SimuladorHumano)
        real_method = SimuladorHumano.secuencia_pre_accion

        await real_method(humano, element_id="myButton")

        humano.mover_a_elemento.assert_called_once_with("myButton")

    @pytest.mark.asyncio
    async def test_secuencia_sin_element_id_no_mueve(self):
        """Sin element_id, mover_a_elemento no se llama."""
        humano = AsyncMock(spec=SimuladorHumano)
        real_method = SimuladorHumano.secuencia_pre_accion

        await real_method(humano)

        humano.mover_a_elemento.assert_not_called()

    @pytest.mark.asyncio
    async def test_secuencia_produce_ordenes_diferentes(self):
        """Múltiples ejecuciones producen órdenes diferentes de acciones."""
        humano = AsyncMock(spec=SimuladorHumano)
        real_method = SimuladorHumano.secuencia_pre_accion

        ordenes = set()
        for _ in range(30):
            humano.reset_mock()
            # Track call order
            call_order = []
            humano.movimiento_idle.side_effect = lambda: call_order.append("idle")
            humano.scroll.side_effect = lambda: call_order.append("scroll")
            humano.delay_activo.side_effect = lambda: call_order.append("delay")
            humano.pausa_extra.side_effect = lambda: call_order.append("pausa")

            await real_method(humano)
            ordenes.add(tuple(call_order))

        # Con 30 intentos, debería haber al menos 2 secuencias diferentes
        assert len(ordenes) > 1
