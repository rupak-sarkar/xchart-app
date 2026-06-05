"""Shared utility functions"""
import pandas as pd
import re
from engine.config import BAD_STRINGS

def is_bad_str(s):
    if not s: return True
    return str(s).strip().lower() in BAD_STRINGS

def safe_int(val, default=0):
    try:
        if val is None: return default
        if isinstance(val, float) and pd.isna(val): return default
        return int(float(val))
    except (ValueError, TypeError): return default

def safe_float(val, default=None):
    try:
        if val is None: return default
        if isinstance(val, float) and pd.isna(val): return default
        return float(val)
    except (ValueError, TypeError): return default

def fv_row(row, names):
    """Get first valid float from row by column name list"""
    if isinstance(names, str): names = [names]
    for n in names:
        v = row.get(n)
        if v is not None:
            try:
                if pd.notna(v): return float(v)
            except: pass
    return None

def sv_row(row, names):
    """Get first valid string from row by column name list"""
    if isinstance(names, str): names = [names]
    for n in names:
        v = row.get(n)
        if v is not None:
            try:
                if pd.notna(v) and str(v).strip(): return str(v)
            except: pass
    return None
