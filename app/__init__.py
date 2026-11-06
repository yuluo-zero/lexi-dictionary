# -*- coding: utf-8 -*-
"""Lexi · 划词词典"""
import os
import sys

_VENDOR = os.path.join(os.path.dirname(__file__), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

__version__ = "1.1.1"
