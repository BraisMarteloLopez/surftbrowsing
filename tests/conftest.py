"""Fixtures compartidas para tests v2."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockWebSocket:
    """Simula un websockets.WebSocketClientProtocol para tests."""

    def __init__(self):
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._sent: list[str] = []
        self._closed = False
        self._close_event = asyncio.Event()
        self.send = AsyncMock(side_effect=self._do_send)
        self.close = AsyncMock(side_effect=self._do_close)

    async def _do_send(self, data: str):
        if self._closed:
            raise ConnectionError("WebSocket cerrado")
        self._sent.append(data)

    async def _do_close(self):
        self._closed = True
        self._close_event.set()

    def inject_response(self, msg_id: int, result: dict | None = None):
        response = {"id": msg_id}
        if result is not None:
            response["result"] = result
        self._incoming.put_nowait(json.dumps(response))

    def inject_event(self, method: str, params: dict | None = None):
        event = {"method": method}
        if params is not None:
            event["params"] = params
        self._incoming.put_nowait(json.dumps(event))

    def force_disconnect(self):
        self._closed = True
        self._incoming.put_nowait(None)

    def get_sent_payloads(self) -> list[dict]:
        return [json.loads(s) for s in self._sent]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed and self._incoming.empty():
            raise StopAsyncIteration
        item = await self._incoming.get()
        if item is None:
            raise ConnectionError("WebSocket desconectado")
        return item


@pytest.fixture
def mock_ws():
    return MockWebSocket()


@pytest_asyncio.fixture
async def mock_cdp(mock_ws):
    from cdp_core import CDPSession
    cdp = CDPSession(mock_ws)
    await cdp.start()
    await asyncio.sleep(0.01)
    yield cdp
    await cdp.close()


@pytest.fixture
def sample_config():
    """Config completa para tests de fase_0."""
    return {
        "url_inicio": "https://icp.administracionelectronica.gob.es/icpplus/index.html",
        "ids": {
            "dropdown_provincia": "form",
            "valor_madrid": "/icpplustiem/citar?p=28&locale=es",
            "boton_aceptar_f1": "btnAceptar",
            "dropdown_tramite": "tramiteGrupo[0]",
            "valor_tramite": "4112",
            "boton_aceptar_f2": "btnAceptar",
            "boton_entrar_f3": "btnEntrar",
            "input_nie": "txtIdCitado",
            "input_nombre": "txtDesCitado",
            "boton_aceptar_f4": "btnEnviar",
            "boton_solicitar_cita": "btnEnviar",
            "texto_no_hay_citas": "En este momento no hay citas disponibles.",
        },
    }


@pytest.fixture
def sample_ids(sample_config):
    return sample_config["ids"]
