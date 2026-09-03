"""Тесты локализации (services/i18n.py). Запуск: pytest tests/test_i18n.py -v"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.i18n import (t, resolve_lang, all_menu_button_texts, menu_key_from_text,
                           SUPPORTED_LANGS, DEFAULT_LANG, LANGUAGE_NAMES, _STRINGS)


# ═══════════ t() ═══════════

def test_t_returns_correct_language():
    assert t("btn_search", "ru") == "🔍 Поиск"
    assert t("btn_search", "en") == "🔍 Search"


def test_t_falls_back_to_default_for_unsupported_lang():
    assert t("btn_search", "fr") == t("btn_search", DEFAULT_LANG)


def test_t_falls_back_to_default_for_none():
    assert t("btn_search", None) == t("btn_search", DEFAULT_LANG)


def test_t_unknown_key_returns_key_itself():
    """Неизвестный ключ не должен падать — лучше показать сам ключ (заметный
    баг в логах), чем уронить хендлер."""
    assert t("this_key_does_not_exist", "ru") == "this_key_does_not_exist"


def test_t_formats_placeholders():
    result = t("insufficient_balance", "en", price=5, balance=2)
    assert "5" in result and "2" in result


def test_t_no_placeholders_needed_does_not_crash():
    assert t("banned", "ru") == "⛔ Вы заблокированы."


# ═══════════ Полнота словаря: каждый ключ должен иметь ОБА языка ═══════════

def test_every_key_has_all_supported_languages():
    missing = []
    for key, translations in _STRINGS.items():
        for lang in SUPPORTED_LANGS:
            if lang not in translations or not translations[lang]:
                missing.append((key, lang))
    assert not missing, f"Отсутствуют переводы: {missing}"


def test_every_string_pair_has_same_placeholders():
    """Если в ru-варианте есть {balance}, в en-варианте он тоже должен быть —
    иначе .format() либо упадёт, либо молча потеряет данные."""
    import re
    mismatched = []
    for key, translations in _STRINGS.items():
        if set(translations.keys()) != set(SUPPORTED_LANGS):
            continue
        placeholder_sets = {
            lang: set(re.findall(r"\{(\w+)\}", text))
            for lang, text in translations.items()
        }
        first_lang = SUPPORTED_LANGS[0]
        for lang in SUPPORTED_LANGS[1:]:
            if placeholder_sets[lang] != placeholder_sets[first_lang]:
                mismatched.append((key, placeholder_sets))
    assert not mismatched, f"Несовпадающие плейсхолдеры: {mismatched}"


# ═══════════ resolve_lang() ═══════════

class _FakeRow(dict):
    def keys(self):
        return dict.keys(self)


def test_resolve_lang_none_user():
    assert resolve_lang(None) == DEFAULT_LANG


def test_resolve_lang_not_set():
    assert resolve_lang(_FakeRow(language=None)) == DEFAULT_LANG


def test_resolve_lang_valid():
    assert resolve_lang(_FakeRow(language="en")) == "en"


def test_resolve_lang_invalid_falls_back():
    assert resolve_lang(_FakeRow(language="fr")) == DEFAULT_LANG


# ═══════════ Меню: сопоставление текста кнопки <-> действия ═══════════

def test_all_menu_button_texts_covers_both_languages():
    texts = all_menu_button_texts()
    assert "🔍 Поиск" in texts
    assert "🔍 Search" in texts


def test_menu_key_from_text_both_languages():
    assert menu_key_from_text("🔍 Поиск") == "btn_search"
    assert menu_key_from_text("🔍 Search") == "btn_search"
    assert menu_key_from_text("💎 Купить коины") == "btn_buy"
    assert menu_key_from_text("💎 Buy coins") == "btn_buy"


def test_menu_key_from_text_unknown_returns_none():
    assert menu_key_from_text("случайный текст") is None


def test_language_names_cover_all_supported():
    for lang in SUPPORTED_LANGS:
        assert lang in LANGUAGE_NAMES
