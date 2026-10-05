"""Math-font Latin aliases for evidence comparison, never source mutation."""
import unicodedata


def canonical_math_letters(text):
    result = []
    for char in text:
        # Mathematical styled LATIN letters only. Do not NFKC the document:
        # superscripts, fractions, circled digits and units retain meaning.
        if 0x1D400 <= ord(char) <= 0x1D6A5 or char == '\u210e':
            plain = unicodedata.normalize('NFKC', char)
            if len(plain) == 1 and plain.isascii() and plain.isalpha():
                char = plain
        result.append(char)
    return ''.join(result)
