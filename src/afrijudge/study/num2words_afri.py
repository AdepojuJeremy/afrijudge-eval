"""Cardinal number words for the arithmetic materials."""

import re

EN = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
HA = "sifili ɗaya biyu uku huɗu biyar shida bakwai takwas tara goma".split()
IG = "efu otu abụọ atọ anọ ise isii asaa asatọ itoolu iri".split()
YO = ("òdo", "ọ̀kan", "èjì", "ẹ̀ta", "ẹ̀rin", "àrún-ún", "ẹ̀fà", "èje", "ẹ̀jọ", "ẹ̀sán")
YO_TEENS = (
    "mẹ́wàá",
    "mọ́kànlá",
    "méjìlá",
    "mẹ́tàlá",
    "mẹ́rìnlá",
    "mẹ́ẹ̀dógún",
    "mẹ́rìndínlógún",
    "mẹ́tàdínlógún",
    "méjìdínlógún",
    "mọ́kàndínlógún",
)
YO_BASES = {
    20: "ogún",
    30: "ọgbọ̀n",
    40: "ogójì",
    50: "àádọ́ta",
    60: "ọgọ́ta",
    70: "àádọ́rin",
    80: "ọgọ́rin",
    90: "àádọ́rùn-ún",
    100: "ọgọ́rùn-ún",
    120: "ọgọ́fà",
    140: "ọgọ́je",
    160: "ọgọ́jọ",
    180: "ọgọ́sàn-án",
    200: "igba",
    300: "ọ̀ọ́dúnrún",
    400: "irinwó",
    500: "ẹ̀ẹ́dẹ́gbẹ̀ta",
    600: "ẹgbẹ̀ta",
    700: "ẹ̀ẹ́dẹ́gbẹ̀rin",
    800: "ẹgbẹ̀rin",
    900: "ẹ̀ẹ́dẹ́gbẹ̀rún",
    1000: "ẹgbẹ̀rún",
}


def _english(n: int) -> str:
    if n < 20:
        return EN[n]
    if n < 100:
        tens, rem = divmod(n, 10)
        word = "twenty thirty forty fifty sixty seventy eighty ninety".split()[tens - 2]
        return word + (f"-{EN[rem]}" if rem else "")
    unit, size = ("thousand", 1000) if n >= 1000 else ("hundred", 100)
    whole, rem = divmod(n, size)
    return f"{_english(whole)} {unit}" + (f" {_english(rem)}" if rem else "")


def _hausa(n: int) -> str:
    if n <= 10:
        return HA[n]
    if n < 100:
        whole, rem = divmod(n, 10)
        word = "goma ashirin talatin arba'in hamsin sittin saba'in tamanin casa'in".split()[
            whole - 1
        ]
        return word + (f" sha {HA[rem]}" if whole == 1 else f" da {HA[rem]}") if rem else word
    unit, size = ("dubu", 1000) if n >= 1000 else ("ɗari", 100)
    whole, rem = divmod(n, size)
    return f"{unit} {_hausa(whole)}" + (f" da {_hausa(rem)}" if rem else "")


def _igbo(n: int) -> str:
    if n <= 10:
        return IG[n]
    if n < 100:
        whole, rem = divmod(n, 10)
        word = f"iri {IG[whole]}" if whole > 1 else "iri"
        return word + (f" na {IG[rem]}" if rem else "")
    unit, size = ("puku", 1000) if n >= 1000 else ("narị", 100)
    whole, rem = divmod(n, size)
    if whole == 1:
        word = f"otu {unit}"
    else:
        word = f"{unit} {_igbo(whole)}"
    return word + (f" na {_igbo(rem)}" if rem else "")


def _yoruba(n: int) -> str:
    if n < 10:
        return YO[n]
    if n < 20:
        return YO_TEENS[n - 10]
    if n in YO_BASES:
        return YO_BASES[n]
    if n < 100:
        rounded = 10 * ((n + 5) // 10)
        if rounded > n:
            return f"{YO[rounded - n]} ó dín ní {YO_BASES[rounded]}"
        return f"{YO[n - rounded]} ó lé ní {YO_BASES[rounded]}"
    size = 1000 if n >= 1000 else 100 if n >= 200 else 20
    whole, rem = divmod(n, size)
    base = f"ẹgbẹ̀rún {_yoruba(whole)}" if n >= 2000 else YO_BASES[whole * size]
    return base + (f" àti {_yoruba(rem)}" if rem else "")


NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
COMPLEX_NOTATION = re.compile(r"\d\s*[./:−–-]\s*\d|[+=×÷*/^<>]")
MATH_SYMBOL = re.compile(r"[\d+=×÷*/^<>−–%$£€₦¥]")
CURRENCY = {
    "$": ("dollars", "dala", "dọ́là", "dọla"),
    "£": ("pounds", "fam", "pọ́ọ̀n", "paụnd"),
    "€": ("euros", "yuro", "yúrò", "yuro"),
    "₦": ("naira", "naira", "náírà", "naira"),
    "¥": ("yen", "yen", "yẹ́n", "yen"),
    "%": ("percent", "kashi bisa ɗari", "ní ọgọ́rùn-ún", "pasentị"),
}
COMPILERS = {"en": _english, "ha": _hausa, "yo": _yoruba, "ig": _igbo}


def number_text(n: int, lang: str) -> str:
    if type(n) is not int or not 0 <= n <= 10_000:
        raise ValueError(f"Number outside the supported integer range: {n}")
    return COMPILERS[lang](n)


def quantities(text: str) -> set[int]:
    return {int(raw.replace(",", "")) for raw in NUMBER.findall(text)}


def spoken_question(text: str, lang: str) -> str:
    if COMPLEX_NOTATION.search(text):
        raise ValueError("Unsupported decimal, range, equation, or clock notation")
    idx = tuple(COMPILERS).index(lang)
    forms = {symbol: names[idx] for symbol, names in CURRENCY.items()}

    def currency(match):
        symbol, raw = match.groups()
        words = number_text(int(raw.replace(",", "")), lang)
        return f"{forms[symbol]} {words}" if lang == "ha" else f"{words} {forms[symbol]}"

    text = re.sub(r"([$£€₦¥])\s*(" + NUMBER.pattern + r")", currency, text)
    text = re.sub(
        r"(" + NUMBER.pattern + r")\s*(%)",
        lambda m: f"{number_text(int(m[1].replace(',', '')), lang)} {forms[m[2]]}",
        text,
    )
    text = NUMBER.sub(lambda m: number_text(int(m[0].replace(",", "")), lang), text)
    if MATH_SYMBOL.search(text):
        raise ValueError("Question retained digits or arithmetic symbols")
    return text
