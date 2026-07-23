"""Shared regex patterns and TD parameter name utilities."""
import re

SEQNUMPATTERN = re.compile(r'_?\d+$')   # trailing sequence number, e.g. "Beam_3" → strips "_3"
SEQNAMEPATTERN = re.compile(r'_(\d+)')  # embedded sequence number, e.g. "Beam_3_Color" → strips "_3"


def legalPopName(name: str, prefix: str = 'ch') -> str:
    """
    Generate a valid POP attribute/group name by:
    - Replacing all characters outside [A-Za-z0-9_] with underscores
    - Ensuring the first character is a letter (POPs reject names starting
      with a digit or underscore) by prepending the given prefix
    """
    cleaned = re.sub(r'[^A-Za-z0-9_]', '_', name)

    if not cleaned or not cleaned[0].isalpha():
        cleaned = prefix + cleaned

    return cleaned


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
