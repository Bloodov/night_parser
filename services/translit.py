"""
Транслитерация латиница <-> кириллица для поиска.

ВАЖНО: это ТРАНСЛИТЕРАЦИЯ (передача написания по звучанию), а не ПЕРЕВОД
смысла. "bitcoin" превратится в "биткоин" (так это слово реально пишут по-русски),
но не в "монета" — перевод смысла слов потребовал бы внешнего сервиса перевода
и работал бы гораздо менее предсказуемо для случайных названий чатов. Для
большинства реальных случаев (англицизмы, бренды, сленг) транслитерация даёт
то самое "то же слово, другим алфавитом", которое и нужно для поиска.

Транслитерация принципиально неточна (например, латинскую "c" по-разному
произносят в разных словах — "center" и "cat"), поэтому это эвристика для
РАСШИРЕНИЯ поиска (показать больше релевантного), а не точное сопоставление.
"""

import re
import itertools

# ── кириллица -> латиница ──
# Для однозначных букв — просто строка. Для неоднозначных (одна и та же
# кириллическая буква на практике происходит от РАЗНЫХ латинских букв в разных
# заимствованиях, например "крипто" от "crypto", а "контроль" от "control" —
# в обоих случаях "к", но в оригинале то "c", то "k") — список правдоподобных
# вариантов; script_variants() переберёт разумное количество их комбинаций.
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": ("i", "y"), "й": "y", "к": ("k", "c"), "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": ("ts", "c"), "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_MAX_CYR_TO_LAT_VARIANTS = 8  # защита от комбинаторного взрыва на длинных словах

# ── латиница -> кириллица: сначала длинные буквосочетания (жадный разбор) ──
# Правила, не зависящие от позиции в слове:
_LAT_TO_CYR_MULTI = [
    ("shch", "щ"), ("sch", "щ"),
    ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("tz", "ц"),
    ("ch", "ч"), ("sh", "ш"),
    ("ck", "к"),  # "hack" -> "хак", а не "хакк" (c->к + k->к слитно дают удвоение)
    ("th", "т"),  # частое упрощение при заимствовании ("python" -> "питон", не "пйтхон")
]
# Диграфы с "y" — применяются только НЕ в начале слова (см. latin_to_cyrillic):
# в начале слова "y" почти всегда согласная "й" (yes, york, young), а не часть
# гласного диграфа.
_LAT_TO_CYR_Y_DIGRAPHS = [
    ("yu", "ю"), ("ju", "ю"), ("iu", "ю"),
    ("ya", "я"), ("ja", "я"), ("ia", "я"),
    ("ye", "е"), ("je", "е"),
    ("yo", "ё"), ("jo", "ё"),
]
_LAT_TO_CYR_SINGLE = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "z": "з", "i": "и", "y": "й", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т",
    "u": "у", "f": "ф", "h": "х", "c": "к", "j": "дж", "x": "кс",
    "w": "в", "q": "к",
}

_LAT_RE = re.compile(r"^[a-z]+$")
_CYR_RE = re.compile(r"^[а-яё]+$")


def detect_script(text: str) -> str:
    """'lat' / 'cyr' / 'other' — по большинству латинских/кириллических букв
    в строке (используется и для транслитерации, и для сортировки результатов)."""
    text = text.lower()
    lat = sum(1 for ch in text if "a" <= ch <= "z")
    cyr = sum(1 for ch in text if "а" <= ch <= "я" or ch == "ё")
    if lat == 0 and cyr == 0:
        return "other"
    return "lat" if lat >= cyr else "cyr"


def cyrillic_to_latin(word: str) -> str | None:
    """Транслитерирует кириллическое слово в латиницу (для неоднозначных букв
    берёт первый вариант из таблицы). None, если слово не похоже на чисто
    кириллическое. Для поиска используйте cyrillic_to_latin_variants() —
    он учитывает все правдоподобные варианты, а не только первый."""
    variants = cyrillic_to_latin_variants(word)
    return next(iter(variants)) if variants else None


def cyrillic_to_latin_variants(word: str) -> set[str]:
    """Возвращает МНОЖЕСТВО правдоподобных латинских написаний кириллического
    слова, перебирая варианты для неоднозначных букв (см. _CYR_TO_LAT) —
    например, 'крипто' даёт и 'kripto', и 'crypto' среди прочих. Ограничено
    _MAX_CYR_TO_LAT_VARIANTS, чтобы длинные слова с несколькими неоднозначными
    буквами не порождали слишком много комбинаций."""
    lower = word.lower()
    if not _CYR_RE.match(lower):
        return set()

    options_per_letter = []
    for ch in lower:
        mapped = _CYR_TO_LAT.get(ch, ch)
        options_per_letter.append(mapped if isinstance(mapped, tuple) else (mapped,))

    variants = set()
    for combo in itertools.product(*options_per_letter):
        variants.add("".join(combo))
        if len(variants) >= _MAX_CYR_TO_LAT_VARIANTS:
            break
    return variants


def latin_to_cyrillic(word: str) -> str | None:
    """Транслитерирует латинское слово в кириллицу (жадный разбор буквосочетаний:
    сначала длинные вроде 'shch'/'yu'/'zh', потом одиночные буквы). None, если
    слово не похоже на чисто латинское.

    Особый случай: одиночная 'y' не в начале слова почти всегда звучит как
    гласная "и" (crypto, python, gym, style), а не согласная "й" — в отличие
    от 'y' в начале слова (yes, york). Буквосочетания вроде 'ya'/'ye'/'yo'/'yu'
    обрабатываются раньше как отдельные диграфы, так что до одиночной 'y'
    доходит только "чистый" случай гласного звучания."""
    lower = word.lower()
    if not _LAT_RE.match(lower):
        return None

    result = []
    i = 0
    n = len(lower)
    while i < n:
        matched = False
        for lat_seq, cyr_ch in _LAT_TO_CYR_MULTI:
            if lower.startswith(lat_seq, i):
                result.append(cyr_ch)
                i += len(lat_seq)
                matched = True
                break
        if matched:
            continue
        if i > 0:
            for lat_seq, cyr_ch in _LAT_TO_CYR_Y_DIGRAPHS:
                if lower.startswith(lat_seq, i):
                    result.append(cyr_ch)
                    i += len(lat_seq)
                    matched = True
                    break
            if matched:
                continue
        if lower[i] == "y" and i > 0:
            result.append("и")
        else:
            result.append(_LAT_TO_CYR_SINGLE.get(lower[i], lower[i]))
        i += 1
    return "".join(result)


def script_variants(word: str) -> set[str]:
    """Возвращает множество написаний слова: исходное + транслитерация(и) в
    противоположный алфавит (если применимо). Всегда содержит хотя бы исходное."""
    variants = {word}
    cyr = latin_to_cyrillic(word)
    if cyr and cyr != word:
        variants.add(cyr)
    variants |= cyrillic_to_latin_variants(word)
    return variants
