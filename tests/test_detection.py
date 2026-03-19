"""Tests para evaluar_estado_pagina() — Fase 4 (TD-02)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cita_bot import EstadoPagina, evaluar_estado_pagina, CDPSession


def _make_ejecutar_js_mock(responses: list[dict]):
    """Crea un mock de ejecutar_js que devuelve respuestas en secuencia."""
    call_count = 0

    async def mock_ejecutar_js(cdp, expression, timeout=5.0):
        nonlocal call_count
        if call_count < len(responses):
            result = responses[call_count]
            call_count += 1
            return result
        return {}

    return mock_ejecutar_js


@pytest.fixture
def sample_ids():
    return {
        "boton_salir_nocita": "btnSalir",
        "texto_no_hay_citas": "En este momento no hay citas disponibles.",
    }


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_no_hay_citas_texto_exacto(mock_sleep, mock_ejs, sample_ids):
    """Texto original del portal → NO_HAY_CITAS."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 200},                # body length
        {"value": True},               # includes 'no hay citas disponibles'
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.NO_HAY_CITAS


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_hay_citas_contenido_diferente(mock_sleep, mock_ejs, sample_ids):
    """Contenido sin 'no hay citas' + URL válida → HAY_CITAS."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 500},                # body length (contenido sustancial)
        {"value": False},              # no incluye 'no hay citas disponibles'
        {"value": "https://icp.administracionelectronica.gob.es/icpplus/citar"},  # URL
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.HAY_CITAS


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_pagina_vacia_es_desconocido(mock_sleep, mock_ejs, sample_ids):
    """Body < 50 chars → DESCONOCIDO."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 10},                 # body length < 50
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.DESCONOCIDO


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_pagina_error_500_es_desconocido(mock_sleep, mock_ejs, sample_ids):
    """Página con error 500 y URL fuera del portal → DESCONOCIDO."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 200},                # body length
        {"value": False},              # no incluye 'no hay citas'
        {"value": "https://example.com/500"},  # URL fuera del portal
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.DESCONOCIDO


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_url_inesperada_es_desconocido(mock_sleep, mock_ejs, sample_ids):
    """URL sin 'icpplus' → DESCONOCIDO."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 300},                # body length
        {"value": False},              # no incluye 'no hay citas'
        {"value": "https://login.example.com/redirect"},  # URL inesperada
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.DESCONOCIDO


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_sin_boton_salir_sigue_siendo_no_hay_citas(mock_sleep, mock_ejs, sample_ids):
    """Texto 'no hay citas' sin botón Salir → NO_HAY_CITAS (el texto es la señal definitiva)."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 200},                # body length
        {"value": True},               # incluye 'no hay citas disponibles'
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.NO_HAY_CITAS


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_value_missing_from_result(mock_sleep, mock_ejs, sample_ids):
    """ejecutar_js devuelve dict vacío → DESCONOCIDO (body length = 0 < 50)."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {},                            # sin key "value" → default 0 < 50
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.DESCONOCIDO


@pytest.mark.asyncio
@patch("cita_bot.ejecutar_js")
@patch("cita_bot.asyncio.sleep", new_callable=AsyncMock)
async def test_icpplustiem_url_is_valid(mock_sleep, mock_ejs, sample_ids):
    """URL con 'icpplustiem' (subdominio del portal) → HAY_CITAS."""
    cdp = AsyncMock(spec=CDPSession)
    mock_ejs.side_effect = _make_ejecutar_js_mock([
        {"value": 500},
        {"value": False},
        {"value": "https://icp.administracionelectronica.gob.es/icpplustiem/citar?p=28"},
    ])
    result = await evaluar_estado_pagina(cdp, sample_ids)
    assert result == EstadoPagina.HAY_CITAS
