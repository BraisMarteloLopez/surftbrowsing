"""Tests para BackoffController — Fase 6 (TD-09)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cita_bot import BackoffController


class TestBackoffController:
    def test_initial_state(self):
        bc = BackoffController()
        assert bc.errores_consecutivos == 0
        assert bc.tipo_ultimo_error is None
        assert bc.debe_alertar is False

    def test_backoff_exponencial(self):
        """Intervalos crecen exponencialmente: 5, 10, 20, 40, 80."""
        bc = BackoffController(intervalo_base=5.0)
        assert bc.registrar_error("timeout") == 5.0    # 5 * 2^0
        assert bc.registrar_error("timeout") == 10.0   # 5 * 2^1
        assert bc.registrar_error("timeout") == 20.0   # 5 * 2^2
        assert bc.registrar_error("timeout") == 40.0   # 5 * 2^3
        assert bc.registrar_error("timeout") == 80.0   # 5 * 2^4

    def test_backoff_max_cap(self):
        """El intervalo nunca excede max_intervalo."""
        bc = BackoffController(intervalo_base=100.0, max_intervalo=300.0)
        bc.registrar_error("timeout")   # 100
        bc.registrar_error("timeout")   # 200
        resultado = bc.registrar_error("timeout")  # 400 → capped a 300
        assert resultado == 300.0

    def test_reset_on_success(self):
        """registrar_exito() resetea contadores."""
        bc = BackoffController(intervalo_base=5.0)
        bc.registrar_error("timeout")
        bc.registrar_error("timeout")
        assert bc.errores_consecutivos == 2

        bc.registrar_exito()
        assert bc.errores_consecutivos == 0
        assert bc.tipo_ultimo_error is None

        # Siguiente error empieza desde 0
        assert bc.registrar_error("js_error") == 5.0

    def test_alerta_en_umbral(self):
        """debe_alertar es True tras N errores."""
        bc = BackoffController(intervalo_base=1.0, umbral_alerta=3)
        bc.registrar_error("timeout")
        assert bc.debe_alertar is False
        bc.registrar_error("timeout")
        assert bc.debe_alertar is False
        bc.registrar_error("timeout")
        assert bc.debe_alertar is True

    def test_alerta_no_antes_umbral(self):
        """debe_alertar es False con < umbral errores."""
        bc = BackoffController(umbral_alerta=10)
        for _ in range(9):
            bc.registrar_error("timeout")
        assert bc.debe_alertar is False

    def test_tipo_ultimo_error(self):
        """tipo_ultimo_error refleja el último error registrado."""
        bc = BackoffController()
        bc.registrar_error("timeout")
        assert bc.tipo_ultimo_error == "timeout"
        bc.registrar_error("js_error")
        assert bc.tipo_ultimo_error == "js_error"

    def test_tipo_reset_on_success(self):
        bc = BackoffController()
        bc.registrar_error("conexion")
        bc.registrar_exito()
        assert bc.tipo_ultimo_error is None

    def test_custom_parameters(self):
        """Parámetros personalizados funcionan correctamente."""
        bc = BackoffController(intervalo_base=2.0, max_intervalo=10.0, umbral_alerta=2)
        assert bc.registrar_error("x") == 2.0   # 2 * 2^0
        assert bc.registrar_error("x") == 4.0   # 2 * 2^1
        assert bc.debe_alertar is True
        assert bc.registrar_error("x") == 8.0   # 2 * 2^2
        assert bc.registrar_error("x") == 10.0  # 2 * 2^3 = 16 → capped 10
