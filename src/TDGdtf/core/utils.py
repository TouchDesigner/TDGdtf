"""Shared regex patterns and TD parameter name utilities."""
import re

SEQNUMPATTERN = re.compile(r'_?\d+$')   # trailing sequence number, e.g. "Beam_3" → strips "_3"
SEQNAMEPATTERN = re.compile(r'_(\d+)')  # embedded sequence number, e.g. "Beam_3_Color" → strips "_3"


def legalTdParName(name: str) -> str:
    """
    Generate a valid TouchDesigner parameter name by:
    - Removing all special characters (no underscores allowed)
    - Ensuring first character is a capitalized letter
    - Making everything else lowercase
    """
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', name)

    if not cleaned or not cleaned[0].isalpha():
        cleaned = 'Ch' + cleaned

    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:].lower()

    return cleaned
