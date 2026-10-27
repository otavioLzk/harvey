"""Brazilian phone numbers — mobile numbers are the WhatsApp-reachable ones.

A Brazilian mobile is DDD (2 digits) + 9 + 8 digits; a landline is
DDD + a first digit 2-5 + 7 more. Only mobiles can be assumed to have
WhatsApp, so the lead list separates the two.
"""

import re
from dataclasses import dataclass


@dataclass
class BrPhone:
    e164: str = ""          # "+5511987654321"
    kind: str = ""          # "mobile" | "landline" | ""
    raw: str = ""

    @property
    def whatsapp(self) -> bool:
        return self.kind == "mobile"

    @property
    def wa_link(self) -> str:
        return f"https://wa.me/{self.e164.lstrip('+')}" if self.whatsapp else ""


def parse_br_phone(raw: str) -> BrPhone:
    """Normalise any common Brazilian formatting. Unparseable -> empty BrPhone."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) in (11, 12) and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 11 and digits[2] == "9":
        kind = "mobile"
    elif len(digits) == 10 and digits[2] in "2345":
        kind = "landline"
    else:
        return BrPhone(raw=raw or "")
    if digits[0] == "0" or digits[1] == "0":
        return BrPhone(raw=raw or "")
    return BrPhone(e164="+55" + digits, kind=kind, raw=raw or "")
