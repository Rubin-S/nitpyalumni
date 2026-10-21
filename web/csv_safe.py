"""Neutralise spreadsheet formulas in admin CSV exports (CSV injection).

User-controlled text such as names or addresses starting with = + - @ (or a
tab/CR) is executed as a formula by Excel/Sheets when an admin opens the file.
"""
import re
from decimal import Decimal

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# Phone numbers / signed numbers such as "+91 98765-43210" cannot form a formula.
_PLAIN_NUMBER = re.compile(r"[+\-]?[\d\s().\-]+")


def safe_cell(value):
    if value is None or isinstance(value, (bool, int, float, Decimal)):
        return value
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES) and not _PLAIN_NUMBER.fullmatch(text):
        return "'" + text
    return text


def safe_row(values):
    return [safe_cell(value) for value in values]
