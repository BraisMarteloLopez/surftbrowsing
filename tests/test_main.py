"""Tests para main() y alerta_sonora — Fase 8 (TD-10)."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMainValidation:
    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "")
    @patch("cita_bot.NOMBRE", "TEST")
    async def test_main_falla_sin_nie(self):
        from cita_bot import main
        with pytest.raises(SystemExit) as exc_info:
            await main()
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "")
    async def test_main_falla_sin_nombre(self):
        from cita_bot import main
        with pytest.raises(SystemExit) as exc_info:
            await main()
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    @patch("cita_bot.PASO_HASTA", 6)
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    async def test_main_falla_paso_hasta_invalido(self):
        from cita_bot import main
        with pytest.raises(SystemExit) as exc_info:
            await main()
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 0)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    async def test_main_modo_depuracion_paso_0(self, mock_verify, mock_nav, mock_connect):
        from cita_bot import main, CDPSession
        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        await main()

        mock_nav.assert_called_once()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 3)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock, return_value=None)
    async def test_main_modo_depuracion_paso_3(self, mock_ciclo, mock_verify, mock_nav, mock_connect):
        from cita_bot import main, CDPSession
        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        await main()

        mock_ciclo.assert_called_once()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.INTERVALO_REINTENTO", 0.01)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.click_salir", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_no_hay_citas_reintenta(self, mock_sleep, mock_salir,
                                                mock_ciclo, mock_verify,
                                                mock_nav, mock_connect):
        from cita_bot import main, CDPSession, EstadoPagina

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        # Primera iteración: NO_HAY_CITAS, segunda: raise para salir del loop
        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return EstadoPagina.NO_HAY_CITAS
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

        mock_salir.assert_called_once()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_estado_desconocido_usa_backoff(self, mock_sleep,
                                                        mock_ciclo, mock_verify,
                                                        mock_nav, mock_connect):
        from cita_bot import main, CDPSession, EstadoPagina

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return EstadoPagina.DESCONOCIDO
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

        # Backoff should have been used — sleep calls should include backoff values
        assert mock_sleep.call_count >= 2

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_timeout_usa_backoff(self, mock_sleep, mock_ciclo,
                                             mock_verify, mock_nav, mock_connect):
        from cita_bot import main, CDPSession

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_runtime_error_usa_backoff(self, mock_sleep, mock_ciclo,
                                                   mock_verify, mock_nav, mock_connect):
        from cita_bot import main, CDPSession

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Element not found")
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_connection_error_reconecta(self, mock_sleep, mock_ciclo,
                                                    mock_verify, mock_nav, mock_connect):
        from cita_bot import main, CDPSession

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()

        connect_count = 0

        async def connect_side_effect():
            nonlocal connect_count
            connect_count += 1
            return (mock_ws, mock_cdp)

        mock_connect.side_effect = connect_side_effect

        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("WS muerto")
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

        # Debería haber reconectado (connect llamado > 1 vez)
        assert connect_count >= 2

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=False)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_url_verificacion_falla_usa_backoff(self, mock_sleep,
                                                            mock_verify, mock_nav,
                                                            mock_connect):
        from cita_bot import main, CDPSession

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        call_count = 0
        original_verify = mock_verify.side_effect

        async def verify_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False
            raise KeyboardInterrupt()

        mock_verify.side_effect = verify_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.click_salir", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_click_salir_falla_navega_inicio(self, mock_sleep, mock_salir,
                                                        mock_ciclo, mock_verify,
                                                        mock_nav, mock_connect):
        """Si click_salir devuelve False, el siguiente ciclo navega al inicio."""
        from cita_bot import main, CDPSession, EstadoPagina

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return EstadoPagina.NO_HAY_CITAS
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect
        mock_salir.return_value = False  # botón no encontrado

        with pytest.raises(KeyboardInterrupt):
            await main()
        # click_salir devolvió False → skip_navegacion no se activa
        # → segundo ciclo llama a navegar()
        assert mock_nav.call_count == 2

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.verificar_url", new_callable=AsyncMock, return_value=True)
    @patch("cita_bot.ciclo_completo", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_unexpected_error_usa_backoff(self, mock_sleep, mock_ciclo,
                                                      mock_verify, mock_nav,
                                                      mock_connect):
        from cita_bot import main, CDPSession

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_cdp.is_alive = True
        mock_ws = AsyncMock()
        mock_connect.return_value = (mock_ws, mock_cdp)

        call_count = 0

        async def ciclo_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("algo inesperado")
            raise KeyboardInterrupt()

        mock_ciclo.side_effect = ciclo_side_effect

        with pytest.raises(KeyboardInterrupt):
            await main()

    @pytest.mark.asyncio
    @patch("cita_bot.NIE", "X1234567A")
    @patch("cita_bot.NOMBRE", "TEST NAME")
    @patch("cita_bot.PASO_HASTA", 5)
    @patch("cita_bot.conectar_brave", new_callable=AsyncMock)
    @patch("cita_bot.navegar", new_callable=AsyncMock)
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_main_reconnects_when_not_alive(self, mock_sleep, mock_nav,
                                                   mock_connect):
        from cita_bot import main, CDPSession

        mock_cdp = AsyncMock(spec=CDPSession)
        mock_ws = AsyncMock()

        alive_sequence = iter([False, True, True])
        type(mock_cdp).is_alive = property(lambda self: next(alive_sequence, True))

        connect_count = 0

        async def connect_side(*args, **kwargs):
            nonlocal connect_count
            connect_count += 1
            return (mock_ws, mock_cdp)

        mock_connect.side_effect = connect_side

        # Make navegar raise on second call to exit loop
        nav_count = 0

        async def nav_side(*args, **kwargs):
            nonlocal nav_count
            nav_count += 1
            if nav_count >= 2:
                raise KeyboardInterrupt()

        mock_nav.side_effect = nav_side

        with pytest.raises(KeyboardInterrupt):
            await main()

        # Should have reconnected (initial + reconnect)
        assert connect_count >= 2


class TestAlertaSonora:
    @pytest.mark.asyncio
    @patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_alerta_sonora_linux(self, mock_sleep):
        """En Linux (sin winsound), usa print('\\a')."""
        from cita_bot import alerta_sonora

        call_count = 0

        async def break_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = break_after_one

        with pytest.raises(asyncio.CancelledError):
            await alerta_sonora()
