"""Тесты транслитерации (services/translit.py). Запуск: pytest tests/ -v"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.translit import (latin_to_cyrillic, cyrillic_to_latin,
                               cyrillic_to_latin_variants, detect_script, script_variants)


# ═══════════ latin_to_cyrillic: ключевые кейсы из реального использования ═══════════

def test_bitcoin():
    assert latin_to_cyrillic("bitcoin") == "биткоин"


def test_crypto():
    """Основной пример из запроса: 'crypto' должно совпадать с 'крипто'."""
    assert latin_to_cyrillic("crypto") == "крипто"


def test_chat():
    assert latin_to_cyrillic("chat") == "чат"


def test_python():
    assert latin_to_cyrillic("python") == "питон"


def test_hack_no_double_letter():
    """'ck' должно давать одну 'к', а не удвоение через c->к + k->к."""
    assert latin_to_cyrillic("hack") == "хак"


def test_word_initial_y_is_consonant():
    """В начале слова 'y' — согласная 'й', а не часть гласного диграфа."""
    assert latin_to_cyrillic("yes") == "йес"
    assert latin_to_cyrillic("york") == "йорк"
    assert latin_to_cyrillic("yandex") == "йандекс"


def test_mid_word_y_is_vowel():
    """В середине слова одиночная 'y' обычно звучит как гласная 'и'."""
    assert latin_to_cyrillic("gym") == "гим"


def test_non_latin_returns_none():
    assert latin_to_cyrillic("крипто") is None
    assert latin_to_cyrillic("bit123") is None
    assert latin_to_cyrillic("") is None


# ═══════════ cyrillic_to_latin ═══════════

def test_cyr_to_lat_basic():
    assert cyrillic_to_latin("чат") == "chat"
    assert cyrillic_to_latin("шоп") == "shop"


def test_cyr_to_lat_complex_letters():
    assert "yandeks" in cyrillic_to_latin_variants("яндекс")
    # "к" неоднозначна (k/c) — оба варианта должны присутствовать
    variants = cyrillic_to_latin_variants("хакер")
    assert "khaker" in variants
    assert "khacer" in variants


def test_non_cyrillic_returns_none():
    assert cyrillic_to_latin("crypto") is None
    assert cyrillic_to_latin("") is None


# ═══════════ detect_script ═══════════

def test_detect_script_latin():
    assert detect_script("bitcoin") == "lat"


def test_detect_script_cyrillic():
    assert detect_script("биткоин") == "cyr"


def test_detect_script_mixed_majority_wins():
    assert detect_script("bit коин") == "cyr"  # 5 кириллических букв vs 3 латинских


def test_detect_script_no_letters():
    assert detect_script("12345") == "other"


# ═══════════ script_variants: сквозной сценарий для поиска ═══════════

def test_script_variants_includes_original():
    variants = script_variants("crypto")
    assert "crypto" in variants


def test_script_variants_includes_translit():
    variants = script_variants("crypto")
    assert "крипто" in variants


def test_script_variants_roundtrip_reasonable():
    """Не обязано быть идентичным после round-trip (транслитерация не биективна),
    но оба направления должны присутствовать и не быть пустыми."""
    lat_variants = script_variants("bitcoin")
    assert "bitcoin" in lat_variants and "биткоин" in lat_variants

    # "крипта" содержит неоднозначную "к" (k/c) — должно быть несколько
    # латинских вариантов в дополнение к исходному кириллическому написанию.
    cyr_variants = script_variants("крипта")
    assert "крипта" in cyr_variants
    assert "kripta" in cyr_variants
    assert "cripta" in cyr_variants
    assert len(cyr_variants) > 1


def test_crypto_cyrillic_reverse_direction():
    """Регресс-тест на исходный пример из запроса: поиск 'крипто' должен
    находить и латинские чаты 'crypto' — не только наоборот."""
    assert "crypto" in script_variants("крипто")


def test_variant_combinatorics_capped():
    """Слово с несколькими неоднозначными буквами не должно порождать
    неограниченное число комбинаций."""
    from services.translit import _MAX_CYR_TO_LAT_VARIANTS
    variants = cyrillic_to_latin_variants("константинополь")  # много "к"/"и"
    assert len(variants) <= _MAX_CYR_TO_LAT_VARIANTS
