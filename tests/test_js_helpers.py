"""Tests para safe_js_string() — Fase 2 (TD-03)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cita_bot import safe_js_string


class TestSafeJsString:
    def test_simple_string(self):
        assert safe_js_string("hello") == "hello"

    def test_empty_string(self):
        assert safe_js_string("") == ""

    def test_single_quote(self):
        assert safe_js_string("O'Brien") == "O\\'Brien"

    def test_backslash(self):
        assert safe_js_string("a\\b") == "a\\\\b"

    def test_newline(self):
        assert safe_js_string("a\nb") == "a\\nb"

    def test_carriage_return(self):
        assert safe_js_string("a\rb") == "a\\rb"

    def test_tab(self):
        assert safe_js_string("a\tb") == "a\\tb"

    def test_null_byte(self):
        assert safe_js_string("a\0b") == "a\\0b"

    def test_combined_special_chars(self):
        """Múltiples caracteres especiales juntos."""
        result = safe_js_string("it's a\nnew\\line")
        assert result == "it\\'s a\\nnew\\\\line"

    def test_backslash_before_quote(self):
        """El orden de escape es crucial: backslash primero."""
        # Input (Python): \\' → raw chars: \ '
        # Paso 1 (escape backslash): \\ '  → Python: \\\\\'
        # Paso 2 (escape quote): \\ \' → Python: \\\\\\'
        result = safe_js_string("\\'")
        # Resultado esperado: \\ seguido de \' → 3 chars en raw: \ \ \ '
        assert result == "\\\\\\'", f"Got: {result!r}"

    def test_nie_format(self):
        """NIE típico no necesita escape."""
        assert safe_js_string("X1234567A") == "X1234567A"

    def test_nombre_con_tildes(self):
        """Nombres con acentos no se alteran."""
        assert safe_js_string("JOSÉ GARCÍA LÓPEZ") == "JOSÉ GARCÍA LÓPEZ"

    def test_valor_madrid_url(self):
        """La URL de valor_madrid contiene caracteres seguros."""
        url = "/icpplustiem/citar?p=28&locale=es"
        assert safe_js_string(url) == url

    def test_injection_attempt(self):
        """Intento de inyección JS queda escapado."""
        malicious = "'; alert('XSS');//"
        result = safe_js_string(malicious)
        assert "alert" in result  # El texto sigue ahí
        assert result == "\\'; alert(\\'XSS\\');//"  # Pero escapado
