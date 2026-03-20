"""Tests para CDPSession — Fase 3 (TD-01)."""

import asyncio
import json

import pytest
import pytest_asyncio

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdp_helpers import CDPSession


@pytest.mark.asyncio
async def test_send_receive_happy_path(mock_ws):
    """Flujo normal: send() envía y recibe respuesta."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    async def respond():
        await asyncio.sleep(0.05)
        mock_ws.inject_response(1, {"result": {"type": "string", "value": "ok"}})

    asyncio.create_task(respond())
    result = await cdp.send("Runtime.evaluate", {"expression": "1+1"}, timeout=2.0)
    assert result["id"] == 1
    assert result["result"]["result"]["value"] == "ok"

    payloads = mock_ws.get_sent_payloads()
    assert len(payloads) == 1
    assert payloads[0]["method"] == "Runtime.evaluate"
    await cdp.close()


@pytest.mark.asyncio
async def test_is_alive_initially_true(mock_ws):
    """CDPSession es alive tras arrancar."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)
    assert cdp.is_alive is True
    await cdp.close()


@pytest.mark.asyncio
async def test_listen_sets_alive_false_on_disconnect(mock_ws):
    """Cuando el WebSocket se desconecta, is_alive pasa a False."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)
    assert cdp.is_alive is True

    mock_ws.force_disconnect()
    await asyncio.sleep(0.1)
    assert cdp.is_alive is False
    await cdp.close()


@pytest.mark.asyncio
async def test_send_raises_when_disconnected(mock_ws):
    """send() lanza ConnectionError si la sesión está muerta."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    mock_ws.force_disconnect()
    await asyncio.sleep(0.1)

    with pytest.raises(ConnectionError, match="desconectada"):
        await cdp.send("Page.enable")
    await cdp.close()


@pytest.mark.asyncio
async def test_pending_futures_resolved_on_disconnect(mock_ws):
    """Futures pendientes reciben ConnectionError cuando el listener muere."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    # Crear un Future pendiente registrando un send que no recibirá respuesta
    send_task = asyncio.create_task(
        cdp.send("Runtime.evaluate", {"expression": "1"}, timeout=10.0)
    )
    await asyncio.sleep(0.05)

    # Forzar desconexión
    mock_ws.force_disconnect()

    with pytest.raises((ConnectionError, asyncio.CancelledError)):
        await send_task
    await cdp.close()


@pytest.mark.asyncio
async def test_pre_wait_event_resolved_on_disconnect(mock_ws):
    """Futures de eventos pre-registrados reciben error al desconectar."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    fut = cdp.pre_wait_event("Page.loadEventFired")

    mock_ws.force_disconnect()
    await asyncio.sleep(0.1)

    with pytest.raises(ConnectionError):
        fut.result()
    await cdp.close()


@pytest.mark.asyncio
async def test_pre_wait_event_raises_when_disconnected(mock_ws):
    """pre_wait_event() lanza ConnectionError si la sesión ya está muerta."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    mock_ws.force_disconnect()
    await asyncio.sleep(0.1)

    with pytest.raises(ConnectionError, match="desconectada"):
        cdp.pre_wait_event("Page.loadEventFired")
    await cdp.close()


@pytest.mark.asyncio
async def test_event_delivery(mock_ws):
    """Los eventos CDP se entregan correctamente al Future registrado."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    fut = cdp.pre_wait_event("Page.loadEventFired")

    async def emit():
        await asyncio.sleep(0.05)
        mock_ws.inject_event("Page.loadEventFired", {"timestamp": 123})

    asyncio.create_task(emit())
    result = await cdp.wait_future(fut, timeout=2.0)
    assert result["method"] == "Page.loadEventFired"
    await cdp.close()


@pytest.mark.asyncio
async def test_send_timeout(mock_ws):
    """send() lanza TimeoutError si no hay respuesta dentro del timeout."""
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)

    with pytest.raises(asyncio.TimeoutError):
        await cdp.send("Runtime.evaluate", {"expression": "1"}, timeout=0.1)
    await cdp.close()
