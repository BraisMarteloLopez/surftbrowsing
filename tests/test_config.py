"""Tests de validación de config.json — Fase 1 (TD-10)."""

import json
import os

import pytest

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.json",
)

REQUIRED_KEYS = [
    "url_inicio",
]

REQUIRED_IDS = [
    "dropdown_provincia",
    "valor_madrid",
    "boton_aceptar_f1",
    "dropdown_tramite",
    "valor_tramite",
    "boton_aceptar_f2",
    "boton_entrar_f3",
    "input_nie",
    "input_nombre",
    "boton_aceptar_f4",
    "boton_solicitar_cita",
    "texto_no_hay_citas",
]


@pytest.fixture
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_config_file_exists():
    assert os.path.isfile(CONFIG_PATH), f"config.json no encontrado en {CONFIG_PATH}"


def test_config_is_valid_json():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_required_top_level_keys(config):
    for key in REQUIRED_KEYS:
        assert key in config, f"Falta key obligatoria: {key}"
        assert config[key], f"Key '{key}' está vacía"


def test_ids_section_exists(config):
    assert "ids" in config, "Falta sección 'ids'"
    assert isinstance(config["ids"], dict)


def test_all_required_ids_present(config):
    ids = config["ids"]
    for key in REQUIRED_IDS:
        assert key in ids, f"Falta ID obligatorio: {key}"
        assert ids[key], f"ID '{key}' está vacío"


def test_url_inicio_is_valid_url(config):
    url = config["url_inicio"]
    assert url.startswith("http://") or url.startswith("https://"), \
        f"url_inicio no es una URL válida: {url}"
