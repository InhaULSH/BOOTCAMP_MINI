"""Opt-in two-stage industry, company and keyword insights."""
from . import prompts as base
from dart_remote.insight_plan import DRAFT_INSTRUCTION

VERSION = 'bigin-user-2026-10-10-new2-v1'
TWO_STAGE = True
COMMON = base.COMMON
context = base.context


def instruction(function='insight'):
    return base.instruction(function) + '\n' + DRAFT_INSTRUCTION
