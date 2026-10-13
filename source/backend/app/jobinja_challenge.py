"""Solve Jobinja's cookie waiting page (__arcsjs) in pure Python, without a browser.

The waiting page carries two obfuscated strings and a one-key XOR function. Once the
two cookies are set, the same URL serves the real page with the download anchor. A
real browser (jobinja_browser.py) stays available as a fallback if the template
changes, but the common case no longer needs Chrome/Edge or Playwright installed.
"""
from __future__ import annotations

import json
import re
import time
from http.cookiejar import Cookie, CookieJar

COOKIE_NAMES = ("__arcsjs", "__arcsjsc")
COOKIE_DOMAIN = ".jobinja.ir"
COOKIE_MAX_AGE = 900
DEFAULT_XOR_KEY = 6
MAX_EXPRESSION_CHARS = 20000


class ChallengeError(Exception):
    """The waiting page did not match the known template."""


class _Undefined:
    def __repr__(self) -> str:
        return "undefined"


UNDEFINED = _Undefined()


class _Array:
    def __init__(self, items):
        self.items = items


class _Native:
    def __init__(self, source):
        self.source = source

    def member(self, key):
        return _Native(f"function {key}() {{ [native code] }}")

    def call(self, args):
        if "fromCharCode" in self.source:
            return chr(int(args[0]))
        if any(name in self.source for name in ("entries", "keys", "values")):
            return _Native("[object Array Iterator]")
        return _Native(self.source)


_ARRAY_NATIVE = {
    "fill": "function fill() { [native code] }",
    "entries": "function entries() { [native code] }",
    "keys": "function keys() { [native code] }",
    "values": "function values() { [native code] }",
    "constructor": "function Array() { [native code] }",
    "toString": "function toString() { [native code] }",
}
_STRING_NATIVE = {"constructor": "function String() { [native code] }"}


def _number(value) -> float:
    return float(value) + 0.0


def _to_string(value) -> str:
    if isinstance(value, str):
        return value
    if value is UNDEFINED:
        return "undefined"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(value, _Array):
        return ",".join(_to_string(item) for item in value.items)
    if isinstance(value, _Native):
        return value.source
    raise ChallengeError("unknown value")


def _to_primitive(value):
    if isinstance(value, _Array):
        return _to_string(value)
    if isinstance(value, _Native):
        return value.source
    if value is UNDEFINED or isinstance(value, bool):
        return _number(_to_number(value))
    if isinstance(value, (int, float)):
        return _number(value)
    return value


def _to_number(value) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return _number(value)
    if value is UNDEFINED:
        return float("nan")
    if isinstance(value, _Array):
        return _to_number(_to_string(value))
    if isinstance(value, _Native):
        return float("nan")
    text = value.strip()
    try:
        return _number(float(text)) if text else 0.0
    except ValueError:
        return float("nan")


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return not (float(value) == 0 or float(value) != float(value))
    if isinstance(value, str):
        return value != ""
    return value is not UNDEFINED


def _add(left, right):
    first, second = _to_primitive(left), _to_primitive(right)
    if isinstance(first, str) or isinstance(second, str):
        return _to_string(left) + _to_string(right)
    return _number(first + second)


def _member(base, key):
    name = _to_string(key)
    if isinstance(base, str):
        if name in _STRING_NATIVE:
            return _Native(_STRING_NATIVE[name])
        return base[int(name)] if name.isdigit() and int(name) < len(base) else UNDEFINED
    if isinstance(base, _Array):
        if name in _ARRAY_NATIVE:
            return _Native(_ARRAY_NATIVE[name])
        return UNDEFINED
    if isinstance(base, _Native):
        return base.member(name)
    return UNDEFINED


_TOKEN = re.compile(r"\s*(?:(?P<string>'[^']*')|(?P<number>\d+(?:\.\d+)?)|(?P<punct>[\[\]()+!]))")


class _Parser:
    """Recursive descent for the JSFuck subset the waiting page uses."""

    def __init__(self, source: str):
        self.tokens = []
        position = 0
        while position < len(source):
            match = _TOKEN.match(source, position)
            if not match or match.end() == match.start():
                raise ChallengeError("unsupported expression")
            self.tokens.append(match)
            position = match.end()
        self.index = 0

    def _peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _accept(self, text: str) -> bool:
        token = self._peek()
        if token is not None and token.group("punct") == text:
            self.index += 1
            return True
        return False

    def _expect(self, text: str) -> None:
        if not self._accept(text):
            raise ChallengeError("unexpected token")

    def parse(self):
        value = self._additive()
        if self.index != len(self.tokens):
            raise ChallengeError("trailing tokens")
        return value

    def _additive(self):
        value = self._unary()
        while self._accept("+"):
            value = _add(value, self._unary())
        return value

    def _unary(self):
        if self._accept("!"):
            return not _truthy(self._unary())
        if self._accept("+"):
            return _to_number(self._unary())
        return self._postfix()

    def _postfix(self):
        value = self._primary()
        while True:
            if self._accept("["):
                key = self._additive()
                self._expect("]")
                value = _member(value, key)
            elif self._accept("("):
                args = []
                if not self._accept(")"):
                    while True:
                        args.append(self._additive())
                        if not self._accept(","):
                            break
                    self._expect(")")
                if not isinstance(value, _Native):
                    raise ChallengeError("unsupported call")
                value = value.call(args)
            else:
                return value

    def _primary(self):
        token = self._peek()
        if token is None:
            raise ChallengeError("unexpected end")
        self.index += 1
        if token.group("string") is not None:
            return token.group("string")[1:-1]
        if token.group("number") is not None:
            return float(token.group("number"))
        if token.group("punct") == "(":
            value = self._additive()
            self._expect(")")
            return value
        if token.group("punct") == "[":
            items = []
            if not self._accept("]"):
                while True:
                    items.append(self._additive())
                    if not self._accept(","):
                        break
                self._expect("]")
            return _Array(items)
        raise ChallengeError("unsupported token")


_VALUE = re.compile(r"'(value_v1|value)'\s*:\s*eval\(\s*(\"(?:[^\"\\]|\\.)*\")\s*\)")
_XOR_KEY = re.compile(r"if\s*\(\s*!\s*[A-Za-z_$][\w$]*\s*\)\s*\{\s*[A-Za-z_$][\w$]*\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*;")
_XOR_NESTING = re.compile(r"([A-Za-z_$][\w$]*)\(\s*\1\s*\(")
_COOKIE_ASSIGNMENT = re.compile(r"__arc[a-z]+=([^;]+)")


def _xor(text: str, key: int, layers: int) -> str:
    for _ in range(layers):
        text = "".join(chr(key ^ ord(char)) for char in text)
    return text


def _evaluate(source: str) -> str:
    if len(source) > MAX_EXPRESSION_CHARS:
        raise ChallengeError("expression too large")
    value = _Parser(source).parse()
    if not isinstance(value, str):
        raise ChallengeError("expression is not a string")
    return value


def solve(html: str) -> dict[str, str]:
    """Return the cookies the waiting page would set, keyed by cookie name."""
    values = {}
    for key, literal in _VALUE.findall(html):
        values.setdefault(key, _evaluate(json.loads(literal)))
    if "value_v1" not in values or "value" not in values:
        raise ChallengeError("obfuscated values not found")
    key_match = _XOR_KEY.search(html)
    key = int(key_match.group(1), 0) if key_match else DEFAULT_XOR_KEY
    layers = 2 if _XOR_NESTING.search(html) else 1
    cookies = {COOKIE_NAMES[0]: _xor(values["value_v1"], key, layers),
               COOKIE_NAMES[1]: _xor(values["value"], key, layers)}
    if any(name not in html for name in COOKIE_NAMES):
        raise ChallengeError("cookie names not found")
    return cookies


def clear(html: str, cookies: CookieJar, trace: list[str]) -> None:
    """Solve the waiting page and store its cookies for the shared download session."""
    try:
        solved = solve(html)
        assignments = _COOKIE_ASSIGNMENT.findall(html)
    except ChallengeError as exc:
        trace.append(f"حل چالش بدون مرورگر ناموفق بود: {exc}.")
        raise
    expires = int(time.time()) + COOKIE_MAX_AGE
    for name in COOKIE_NAMES:
        cookies.set_cookie(Cookie(
            version=0, name=name, value=solved[name], port=None, port_specified=False,
            domain=COOKIE_DOMAIN, domain_specified=True, domain_initial_dot=True,
            path="/", path_specified=True, secure=False, expires=expires, discard=False,
            comment=None, comment_url=None, rest={},
        ))
    # ponytail: the page also names its cookie domain inline; only the count is reported.
    trace.append(f"چالش کوکی جابینجا بدون مرورگر حل شد؛ {len(assignments) or 2} کوکی موقت برای دامنهٔ جابینجا ست شد (مقادیر مخفی).")