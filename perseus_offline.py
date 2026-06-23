#!/usr/bin/env python3
"""
Perseus Minimalist v0.1 — Download and browse the Perseus Digital Library locally.

This script downloads Greek and Latin texts, dictionaries (LSJ, Lewis & Short),
and reference works from the Perseus Digital Library GitHub repositories,
then provides a local web server for browsing and searching everything offline.

Usage:
    python perseus_offline.py download    # Download all data
    python perseus_offline.py serve       # Start the local web viewer
    python perseus_offline.py all         # Download then serve
"""

import argparse
import html
import http.server
import json
import os
import re
import shutil
import sqlite3
import sys
import textwrap
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
import io
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote, unquote

# ── Configuration ──────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "perseus_data"
DB_PATH = DATA_DIR / "perseus_index.db"
WWW_DIR = DATA_DIR / "www"

REPOS = {
    "greek": {
        "url": "https://github.com/PerseusDL/canonical-greekLit/archive/refs/heads/master.zip",
        "dir": "canonical-greekLit",
        "label": "Greek Texts",
    },
    "latin": {
        "url": "https://github.com/PerseusDL/canonical-latinLit/archive/refs/heads/master.zip",
        "dir": "canonical-latinLit",
        "label": "Latin Texts",
    },
    "lexica": {
        "url": "https://github.com/PerseusDL/lexica/archive/refs/heads/master.zip",
        "dir": "lexica",
        "label": "Dictionaries (LSJ, Lewis & Short)",
    },
}

KNOWN_AUTHORS = {
    # Greek authors mapped from TLG codes (sample — will be populated from data)
}

NS = {"tei": "http://www.tei-c.org/ns/1.0"}


# ── Utility functions ──────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def download_zip(url, target_dir, repo_key):
    """Download and extract a GitHub repository ZIP."""
    log(f"Downloading {repo_key} from {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PerseusOffline/1.0"})
        resp = urllib.request.urlopen(req, timeout=300)
        data = resp.read()
    except Exception as e:
        log(f"  ERROR downloading {repo_key}: {e}")
        return False

    log(f"  Extracting {repo_key} ...")
    z = zipfile.ZipFile(io.BytesIO(data))
    
    # Determine the internal root folder name
    members = z.namelist()
    root_folder = members[0].split("/")[0] if members else ""
    
    # Extract to a temp directory first, then swap
    temp_dest = target_dir / (repo_key + "_tmp")
    if temp_dest.exists():
        shutil.rmtree(temp_dest)
    
    for member in members:
        # Strip the outer directory
        parts = member.split("/", 1)
        if len(parts) < 2:
            continue
        new_path = parts[1]
        if not new_path:
            continue
        full_path = temp_dest / new_path
        if member.endswith("/"):
            full_path.mkdir(parents=True, exist_ok=True)
        else:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(full_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    
    # Extraction succeeded — now copy temp → real
    dest = target_dir / repo_key
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(temp_dest, dest)
    shutil.rmtree(temp_dest)
    
    log(f"  Done extracting {repo_key} to {dest}")
    return True


# ── TEI XML Parsing ────────────────────────────────────────────────────────

def extract_tei_text(xml_path):
    """Extract plain text from a TEI XML file."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception:
        return None, None, None

    # Get metadata
    title = ""
    author = ""
    lang = ""
    
    title_elem = root.find(".//tei:title", NS)
    if title_elem is not None and title_elem.text:
        title = title_elem.text.strip()
    
    author_elem = root.find(".//tei:author", NS)
    if author_elem is not None:
        name = author_elem.find("tei:name", NS) or author_elem.find("tei:persName", NS)
        if name is not None and name.text:
            author = name.text.strip()
        elif author_elem.text:
            author = author_elem.text.strip()
    
    lang_elem = root.find(".//tei:text//tei:body", NS)
    if lang_elem is not None:
        lang = lang_elem.get("{http://www.w3.org/XML/1998/namespace}lang", "")
    
    # Extract all text from body, preserving paragraph breaks
    body = root.find(".//tei:body", NS)
    if body is None:
        body = root.find(".//tei:text", NS)
    
    paragraphs = []
    if body is not None:
        for elem in body.iter():
            # Skip non-text elements like notes, refs
            if elem.tag in (
                "{http://www.tei-c.org/ns/1.0}note",
                "{http://www.tei-c.org/ns/1.0}ref",
            ):
                continue
            if elem.tag in (
                "{http://www.tei-c.org/ns/1.0}p",
                "{http://www.tei-c.org/ns/1.0}l",
                "{http://www.tei-c.org/ns/1.0}head",
            ):
                text = "".join(elem.itertext()).strip()
                if text:
                    paragraphs.append(text)
    
    full_text = "\n\n".join(paragraphs)
    return full_text, author, title


def beta_to_greek(beta):
    """Convert Beta Code to Unicode Greek (NFC normalized)."""
    if not beta:
        return beta
    
    import unicodedata
    
    # Letter mappings
    letter_map = {
        'a': '\u03b1', 'b': '\u03b2', 'g': '\u03b3', 'd': '\u03b4',
        'e': '\u03b5', 'z': '\u03b6', 'h': '\u03b7', 'q': '\u03b8',
        'i': '\u03b9', 'k': '\u03ba', 'l': '\u03bb', 'm': '\u03bc',
        'n': '\u03bd', 'c': '\u03be', 'o': '\u03bf', 'p': '\u03c0',
        'r': '\u03c1', 't': '\u03c4', 'u': '\u03c5',
        'f': '\u03c6', 'x': '\u03c7', 'y': '\u03c8', 'w': '\u03c9',
    }
    cap_map = {
        'A': '\u0391', 'B': '\u0392', 'G': '\u0393', 'D': '\u0394',
        'E': '\u0395', 'Z': '\u0396', 'H': '\u0397', 'Q': '\u0398',
        'I': '\u0399', 'K': '\u039a', 'L': '\u039b', 'M': '\u039c',
        'N': '\u039d', 'C': '\u039e', 'O': '\u039f', 'P': '\u03a0',
        'R': '\u03a1', 'S': '\u03a3', 'T': '\u03a4', 'U': '\u03a5',
        'F': '\u03a6', 'X': '\u03a7', 'Y': '\u03a8', 'W': '\u03a9',
    }
    
    smooth = '\u0313'
    rough = '\u0314'
    acute = '\u0301'
    grave = '\u0300'
    circum = '\u0342'
    iota_sub = '\u0345'
    
    result = []
    i = 0
    capitalize_next = False
    pending_breathing = None
    pending_accent = None
    pending_iota = False
    
    while i < len(beta):
        ch = beta[i]
        
        # Capital marker — may be followed by diacritics before the letter
        if ch == '*' and i + 1 < len(beta):
            capitalize_next = True
            i += 1
            # Collect any diacritics that immediately follow *
            while i < len(beta) and beta[i] in ')(/\\=+|':
                d = beta[i]
                if d == ')':
                    pending_breathing = smooth
                elif d == '(':
                    pending_breathing = rough
                elif d == '/':
                    pending_accent = acute
                elif d == '\\':
                    pending_accent = grave
                elif d == '=':
                    pending_accent = circum
                elif d == '+':
                    pending_accent = '\u0308'
                elif d == '|':
                    pending_iota = True
                i += 1
            continue
        
        # Check if this is a Greek letter
        base = None
        if ch in letter_map:
            base = letter_map[ch]
        elif ch in cap_map:
            base = cap_map[ch]
        elif ch == 's':
            is_final = (i + 1 >= len(beta) or beta[i+1] in ' ,.;:()\n\t\'"')
            base = '\u03c2' if is_final else '\u03c3'
        else:
            # Not a letter — emit pending diacritics as literal chars if any
            if pending_breathing or pending_accent or pending_iota:
                # These diacritics didn't precede a letter — emit the original chars
                pass  # They were already consumed, so we just drop them
            pending_breathing = None
            pending_accent = None
            pending_iota = False
            result.append(ch)
            i += 1
            continue
        
        # We have a letter — apply any pending diacritics from * sequence
        breathing = pending_breathing
        accent = pending_accent
        has_iota = pending_iota
        pending_breathing = None
        pending_accent = None
        pending_iota = False
        
        i += 1
        
        # Check for breathing mark (comes after letter in normal Beta Code)
        if breathing is None and i < len(beta):
            next_ch = beta[i]
            if next_ch == ')':
                breathing = smooth
                i += 1
            elif next_ch == '(':
                breathing = rough
                i += 1
        
        # Check for accent mark (comes after breathing)
        if accent is None and i < len(beta):
            next_ch = beta[i]
            if next_ch == '/':
                accent = acute
                i += 1
            elif next_ch == '\\':
                accent = grave
                i += 1
            elif next_ch == '=':
                accent = circum
                i += 1
            elif next_ch == '+':
                accent = '\u0308'  # diaeresis
                i += 1
        
        # Check for iota subscript (after accent)
        if not has_iota and i < len(beta) and beta[i] == '|':
            has_iota = True
            i += 1
        
        # Build the character
        if capitalize_next:
            base = base.upper()
            capitalize_next = False
        
        marks = []
        if breathing:
            marks.append(breathing)
        if accent:
            marks.append(accent)
        if has_iota:
            marks.append(iota_sub)
        
        greek_ch = base + ''.join(marks)
        result.append(greek_ch)
    
    result_str = ''.join(result)
    return unicodedata.normalize('NFC', result_str)
    
    # Letter mappings
    letter_map = {
        'a': '\u03b1', 'b': '\u03b2', 'g': '\u03b3', 'd': '\u03b4',
        'e': '\u03b5', 'z': '\u03b6', 'h': '\u03b7', 'q': '\u03b8',
        'i': '\u03b9', 'k': '\u03ba', 'l': '\u03bb', 'm': '\u03bc',
        'n': '\u03bd', 'c': '\u03be', 'o': '\u03bf', 'p': '\u03c0',
        'r': '\u03c1', 's': '\u03c3', 't': '\u03c4', 'u': '\u03c5',
        'f': '\u03c6', 'x': '\u03c7', 'y': '\u03c8', 'w': '\u03c9',
    }
    cap_map = {
        'A': '\u0391', 'B': '\u0392', 'G': '\u0393', 'D': '\u0394',
        'E': '\u0395', 'Z': '\u0396', 'H': '\u0397', 'Q': '\u0398',
        'I': '\u0399', 'K': '\u039a', 'L': '\u039b', 'M': '\u039c',
        'N': '\u039d', 'C': '\u039e', 'O': '\u039f', 'P': '\u03a0',
        'R': '\u03a1', 'S': '\u03a3', 'T': '\u03a4', 'U': '\u03a5',
        'F': '\u03a6', 'X': '\u03a7', 'Y': '\u03a8', 'W': '\u03a9',
    }
    
    smooth = '\u0313'
    rough = '\u0314'
    acute = '\u0301'
    grave = '\u0300'
    circum = '\u0342'
    iota_sub = '\u0345'
    
    result = []
    i = 0
    capitalize_next = False
    
    while i < len(beta):
        ch = beta[i]
        
        # Capital marker
        if ch == '*' and i + 1 < len(beta):
            capitalize_next = True
            i += 1
            continue
        
        # Check if this is a Greek letter
        base = None
        if ch in letter_map:
            base = letter_map[ch]
        elif ch in cap_map:
            base = cap_map[ch]
        elif ch == 's':
            # Check if this is word-final sigma
            is_final = (i + 1 >= len(beta) or beta[i+1] in ' ,.;:()\n\t\'"')
            base = '\u03c2' if is_final else '\u03c3'
        else:
            result.append(ch)
            i += 1
            continue
        
        # Check for breathing mark (comes after letter in Beta Code)
        breathing = None
        if i + 1 < len(beta):
            next_ch = beta[i + 1]
            if next_ch == ')':
                breathing = smooth
                i += 1
            elif next_ch == '(':
                breathing = rough
                i += 1
        
        # Check for accent mark (comes after breathing)
        accent = None
        if i + 1 < len(beta):
            next_ch = beta[i + 1]
            if next_ch == '/':
                accent = acute
                i += 1
            elif next_ch == '\\':
                accent = grave
                i += 1
            elif next_ch == '=':
                accent = circum
                i += 1
            elif next_ch == '+':
                accent = '\u0308'  # diaeresis
                i += 1
        
        # Check for iota subscript (after accent)
        has_iota = False
        if i + 1 < len(beta) and beta[i + 1] == '|':
            has_iota = True
            i += 1
        
        # Build the character
        if capitalize_next:
            base = base.upper()
            capitalize_next = False
        
        # Apply combining diacritics in correct order: breathing, accent, iota_sub
        marks = []
        if breathing:
            marks.append(breathing)
        if accent:
            marks.append(accent)
        if has_iota:
            marks.append(iota_sub)
        
        greek_ch = base + ''.join(marks)
        result.append(greek_ch)
        i += 1
    
    return ''.join(result)


# ── Morphological Analysis (Latin) ─────────────────────────────────────────

# Tag decoding maps
POS_MAP = {
    'V': 'verb', 'N': 'noun', 'ADJ': 'adjective', 'ADV': 'adverb',
    'CONJ': 'conjunction', 'PREP': 'preposition', 'PRON': 'pronoun',
    'INTERJ': 'interjection', 'NUM': 'numeral', 'PACK': 'particle',
}
TENSE_MAP = {
    'PRES': 'present', 'IMPF': 'imperfect', 'FUT': 'future',
    'PERF': 'perfect', 'PLUP': 'pluperfect', 'FUTP': 'future perfect',
}
VOICE_MAP = {'ACTIVE': 'active', 'PASSIVE': 'passive', 'DEPONENT': 'deponent', 'DEP': 'deponent'}
MOOD_MAP = {
    'IND': 'indicative', 'SUBJ': 'subjunctive', 'SUB': 'subjunctive',
    'IMP': 'imperative', 'INF': 'infinitive', 'PPL': 'participle',
    'GER': 'gerund', 'GERUND': 'gerundive', 'SUP': 'supine',
}
NUMBER_MAP = {'S': 'singular', 'P': 'plural'}
GENDER_MAP = {'M': 'masculine', 'F': 'feminine', 'N': 'neuter'}
CASE_MAP = {
    'NOM': 'nominative', 'GEN': 'genitive', 'DAT': 'dative',
    'ACC': 'accusative', 'ABL': 'ablative', 'VOC': 'vocative', 'LOC': 'locative',
}
DEGREE_MAP = {'POS': 'positive', 'COMP': 'comparative', 'SUPER': 'superlative'}

# Hardcoded irregular Latin verb forms (sum/esse and its compounds)
# These are too irregular to be generated by DICTLINE + INFLECTS rules
IRREGULAR_LATIN_FORMS = {
    # sum, esse, fui, futurus — to be
    'sum': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'es': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'est': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'sumus': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'estis': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'sunt': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'eram': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'eras': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'erat': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'eramus': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'eratis': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'erant': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'ero': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'eris': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'erit': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'erimus': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'eritis': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'erunt': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'fui': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'fuisti': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'fuit': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'fuimus': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'fuistis': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'fuerunt': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'fuere': {'lemma': 'sum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'sim': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '1', 'number': 'S'},
    'sis': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '2', 'number': 'S'},
    'sit': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '3', 'number': 'S'},
    'simus': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '1', 'number': 'P'},
    'sitis': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '2', 'number': 'P'},
    'sint': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '3', 'number': 'P'},
    'essem': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '1', 'number': 'S'},
    'esses': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '2', 'number': 'S'},
    'esset': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '3', 'number': 'S'},
    'essemus': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '1', 'number': 'P'},
    'essetis': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '2', 'number': 'P'},
    'essent': {'lemma': 'sum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '3', 'number': 'P'},
    'esse': {'lemma': 'sum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    'fore': {'lemma': 'sum', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    # eo, ire, ii/ivi, iturus — to go
    'eo': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'is': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'it': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'imus': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'itis': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'eunt': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'ibam': {'lemma': 'eo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'ibat': {'lemma': 'eo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'ibo': {'lemma': 'eo', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'ibit': {'lemma': 'eo', 'pos': 'V', 'tense': 'FUT', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'ii': {'lemma': 'eo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'ivit': {'lemma': 'eo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'iit': {'lemma': 'eo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'ire': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    'iens': {'lemma': 'eo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'PPL', 'person': '', 'number': ''},
    # possum, posse, potui — to be able
    'possum': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'potes': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'potest': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'possumus': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'potestis': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'possunt': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'potui': {'lemma': 'possum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'potuisti': {'lemma': 'possum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'potuit': {'lemma': 'possum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'posse': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    'potens': {'lemma': 'possum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'PPL', 'person': '', 'number': ''},
    # volo, velle, volui — to wish
    'volo': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'vis': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'vult': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'volumus': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'vultis': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'volunt': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'volebam': {'lemma': 'volo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'volebat': {'lemma': 'volo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'volui': {'lemma': 'volo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'voluisti': {'lemma': 'volo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'voluit': {'lemma': 'volo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'vellem': {'lemma': 'volo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '1', 'number': 'S'},
    'vellet': {'lemma': 'volo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '3', 'number': 'S'},
    'velle': {'lemma': 'volo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    # nolo, nolle, nolui — to be unwilling
    'nolo': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'nonvis': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'nonvult': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'nolumus': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'nonvultis': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'nolunt': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'P'},
    'nolui': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'noluit': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'nollem': {'lemma': 'nolo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '1', 'number': 'S'},
    'nollet': {'lemma': 'nolo', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'SUBJ', 'person': '3', 'number': 'S'},
    'nolle': {'lemma': 'nolo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    # malo, malle, malui — to prefer
    'malo': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'mavis': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'S'},
    'mavult': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'malumus': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'P'},
    'mavultis': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '2', 'number': 'P'},
    'malunt': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'malui': {'lemma': 'malo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '1', 'number': 'S'},
    'maluit': {'lemma': 'malo', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'malle': {'lemma': 'malo', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'INF', 'person': '', 'number': ''},
    # Compound forms of sum (prefix + esse)
    'abest': {'lemma': 'absum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'abfuit': {'lemma': 'absum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'adest': {'lemma': 'adsum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'aderat': {'lemma': 'adsum', 'pos': 'V', 'tense': 'IMPF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'adfuit': {'lemma': 'adsum', 'pos': 'V', 'tense': 'PERF', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'interest': {'lemma': 'intersum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'praeest': {'lemma': 'praesum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'prodest': {'lemma': 'prosum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'superest': {'lemma': 'supersum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'deest': {'lemma': 'desum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'obest': {'lemma': 'obsum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
    'subest': {'lemma': 'subsum', 'pos': 'V', 'tense': 'PRES', 'voice': 'ACTIVE', 'mood': 'IND', 'person': '3', 'number': 'S'},
}

# DICTLINE.GEN fixed-width column positions
# Columns 0-72: stems (space-separated, typically 1-4 forms)
# Columns 73-77: POS code
# Columns 78-84: Inflection type code
# Columns 85+: Meaning, flags, frequency info
DICT_POS_START = 73
DICT_POS_END = 78
DICT_TYPE_START = 78
DICT_TYPE_END = 85
DICT_MEANING_START = 85

# INFLECTS.LAT fixed-width column positions
# Columns 0-4: POS
# Columns 5-9: Conjugation/declension code (e.g. "1 1", "3 2")
# Columns 10-14: Tense
# Columns 15-21: Voice (padded to 6-7 chars: "ACTIVE", "PASSIVE")
# Columns 22-26: Mood
# Columns 27-29: Person
# Columns 30-32: Number
# Columns 33-35: Stem type (verb only: 1=present, 2=present_var, 3=perfect)
# Columns 36+: Ending info (len + string) + age/freq codes


def parse_dictline_stems(stems_area):
    """Parse the stems area (columns 0-72) of a DICTLINE entry."""
    parts = stems_area.rstrip().split()
    # Return up to 4 stems (for verbs: present, present_var, perfect, participial)
    return parts[:4] if parts else ['']


def load_latin_morphology():
    """
    Load Whitaker's Words data and build morphology index.
    
    Returns:
        dict with keys:
            'lemmas': list of (lemma, pos, type_code, meaning, stems)
            'stem_set': set of all known stem forms (for fast lookup)
            'verb_rules': list of (conj_code, tense, voice, mood, person, number, stem_type, ending)
            'uniques': dict of word_form -> (pos, conj, tense, voice, mood, person, number, meaning)
    """
    morph_dir = DATA_DIR / "morphology"
    
    lemmas = []
    stem_set = set()
    
    # ── Parse DICTLINE.GEN ──
    dictline_path = morph_dir / "DICTLINE.GEN"
    if not dictline_path.exists():
        log("  DICTLINE.GEN not found at {}".format(dictline_path))
        return None
    
    with open(str(dictline_path), "r", encoding="latin-1") as f:
        for line in f:
            line = line.rstrip('\n\r')
            if len(line) < DICT_MEANING_START:
                continue
            pos = line[DICT_POS_START:DICT_POS_END].strip()
            if not pos:
                continue
            type_code = line[DICT_TYPE_START:DICT_TYPE_END].strip()
            stems = parse_dictline_stems(line[:DICT_POS_START])
            meaning = line[DICT_MEANING_START:].strip()
            lemma = stems[0] if stems else ''
            if lemma:
                lemmas.append((lemma, pos, type_code, meaning, stems))
                for s in stems:
                    if s and s != 'zzz':
                        stem_set.add(s)
    
    log("  Parsed {} lemmas from DICTLINE.GEN".format(len(lemmas)))
    log("  Collected {} unique stems".format(len(stem_set)))
    
    # ── Parse INFLECTS.LAT ──
    inflects_path = morph_dir / "INFLECTS.LAT"
    verb_rules = []
    noun_rules = []
    
    if inflects_path.exists():
        with open(str(inflects_path), "r", encoding="latin-1") as f:
            for line in f:
                line = line.rstrip('\n\r')
                if not line.strip() or line.strip().startswith('--'):
                    continue
                pos = line[0:5].strip()
                conj_code = line[5:10].strip()
                
                if pos == 'V':
                    tense = line[10:15].strip()
                    voice = line[16:23].strip()
                    mood = line[24:27].strip()
                    person = line[29:30].strip() if len(line) > 29 else ''
                    number = line[31:32].strip() if len(line) > 31 else ''
                    stem_type = line[33:35].strip()
                    
                    # Parse ending from the rest
                    end_part = line[36:].strip()
                    end_parts = end_part.split()
                    ending = ''
                    if len(end_parts) >= 2:
                        # First is ending length (digit), second is ending string
                        ending = end_parts[1]
                    
                    verb_rules.append((conj_code, tense, voice, mood, person, number, stem_type, ending))
                
                elif pos in ('N', 'ADJ', 'PRON', 'NUM', 'VPAR'):
                    # Format: NOM S C  1 1 a
                    # Positions: case(10-13) number(14-15) gender(16-17) stem_type(18-19) ending_len(20-21) ending(23+)
                    case = line[10:14].strip() if len(line) > 10 else ''
                    number = line[14:16].strip() if len(line) > 14 else ''
                    gender = line[16:18].strip() if len(line) > 16 else ''
                    stem_type = line[18:20].strip() if len(line) > 18 else ''
                    # Ending length at 20-22, ending string starts at position 23
                    ending_len_str = line[20:22].strip() if len(line) > 20 else '0'
                    try:
                        ending_len = int(ending_len_str)
                    except ValueError:
                        ending_len = 0
                    if ending_len > 0 and len(line) >= 23 + ending_len:
                        ending = line[23:23 + ending_len].strip()
                    else:
                        ending = ''
                    
                    noun_rules.append((conj_code, case, number, gender, stem_type, ending))
    
    log("  Parsed {} verb rules from INFLECTS.LAT".format(len(verb_rules)))
    log("  Parsed {} noun/adjective rules from INFLECTS.LAT".format(len(noun_rules)))
    
    # ── Parse UNIQUES.LAT ──
    uniques_path = morph_dir / "UNIQUES.LAT"
    uniques = {}
    
    if uniques_path.exists():
        with open(str(uniques_path), "r", encoding="latin-1") as f:
            lines = f.readlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip('\n\r')
            if not line.strip() or line.strip().startswith('--'):
                i += 1
                continue
            # Line is the word form
            word_form = line.strip()
            i += 1
            if i >= len(lines):
                break
            # Next line is the analysis
            analysis = lines[i].rstrip('\n\r')
            i += 1
            if i < len(lines):
                meaning = lines[i].rstrip('\n\r')
                i += 1
            else:
                meaning = ''
            
            # Parse analysis line
            if analysis and analysis[0:5].strip() == 'V':
                pos = analysis[0:5].strip()
                conj = analysis[5:10].strip()
                tense = analysis[10:15].strip()
                voice = analysis[15:22].strip()
                mood = analysis[22:27].strip()
                person = analysis[27:30].strip()
                number = analysis[30:33].strip()
                uniques[word_form] = {
                    'pos': pos, 'conj': conj, 'tense': tense,
                    'voice': voice, 'mood': mood, 'person': person,
                    'number': number, 'meaning': meaning,
                }
    
    log("  Parsed {} unique forms from UNIQUES.LAT".format(len(uniques)))
    
    # ── Build ending map for fast lookup ──
    # Map: ending_string -> list of (pos, conj_code, tense, voice, mood, person, number, stem_type)
    verb_endings = defaultdict(list)
    for conj_code, tense, voice, mood, person, number, stem_type, ending in verb_rules:
        if ending:
            verb_endings[ending].append((conj_code, tense, voice, mood, person, number, stem_type))
    
    # Map: ending_string -> list of (conj_code, case, number, gender, stem_type)
    noun_endings = defaultdict(list)
    for conj_code, case, number, gender, stem_type, ending in noun_rules:
        if ending:
            noun_endings[ending].append((conj_code, case, number, gender, stem_type))
    
    log("  Built {} unique verb endings".format(len(verb_endings)))
    log("  Built {} unique noun endings".format(len(noun_endings)))
    
    return {
        'lemmas': lemmas,
        'stem_set': stem_set,
        'verb_rules': verb_rules,
        'verb_endings': dict(verb_endings),
        'noun_rules': noun_rules,
        'noun_endings': dict(noun_endings),
        'uniques': uniques,
    }


def analyze_latin_word(word, morph_data):
    """
    Analyze a Latin word using Whitaker's Words morphology data.
    
    Returns list of analysis dicts, each containing:
        word, lemma, pos, tense, voice, mood, person, number, definition
    """
    if not morph_data:
        return []
    
    word = word.strip().lower()
    if not word:
        return []
    
    results = []
    
    # 1. Check hardcoded irregular forms first (sum/esse, eo, volo, etc.)
    if word in IRREGULAR_LATIN_FORMS:
        irr = IRREGULAR_LATIN_FORMS[word]
        results.append({
            'word': word,
            'lemma': irr['lemma'],
            'pos': irr['pos'],
            'tense': irr['tense'],
            'voice': irr['voice'],
            'mood': irr['mood'],
            'person': irr['person'],
            'number': irr['number'],
            'definition': '',
        })
        return results
    
    # 2. Check UNIQUES first (irregular forms from data)
    if word in morph_data['uniques']:
        u = morph_data['uniques'][word]
        # Find the lemma by matching meaning/conj
        lemma = _find_lemma_by_conj(morph_data['lemmas'], u['conj'])
        results.append({
            'word': word,
            'lemma': lemma or word,
            'pos': u['pos'],
            'tense': u['tense'],
            'voice': u['voice'],
            'mood': u['mood'],
            'person': u['person'],
            'number': u['number'],
            'definition': u['meaning'][:200] if u['meaning'] else '',
        })
        return results
    
    # 3. Try verb analysis: split word into stem + ending
    stem_set = morph_data['stem_set']
    verb_endings = morph_data['verb_endings']
    lemmas = morph_data['lemmas']
    
    for split_pos in range(2, len(word)):
        stem = word[:split_pos]
        ending = word[split_pos:]
        
        if stem in stem_set and ending in verb_endings:
            # Find which lemma this stem belongs to
            for lemma_entry in lemmas:
                lemma, pos, type_code, meaning, stems = lemma_entry
                if pos != 'V':
                    continue
                # Check if this stem belongs to this lemma
                if stem in [s for s in stems if s and s != 'zzz']:
                    # Find matching inflection rules
                    for rule in verb_endings[ending]:
                        conj_code, tense, voice, mood, person, number, stem_type = rule
                        # Check that the conjugation matches
                        rule_conj = conj_code.split()[0] if conj_code else ''
                        lemma_conj = type_code.split()[-1] if type_code else ''
                        if rule_conj and rule_conj == lemma_conj:
                            # Override voice for deponent verbs
                            display_voice = voice
                            if 'DEP' in meaning:
                                display_voice = 'DEP'
                            results.append({
                                'word': word,
                                'lemma': lemma,
                                'pos': pos,
                                'tense': tense,
                                'voice': display_voice,
                                'mood': mood,
                                'person': person,
                                'number': number,
                                'type_code': type_code,
                                'stems': stems,
                                'definition': meaning[:200],
                            })
                            break
    
    # 3. Try noun/adjective/pronoun analysis (declension patterns)
    noun_endings = morph_data['noun_endings']
    noun_pos = {'N', 'ADJ', 'PRON', 'NUM', 'VPAR'}
    if not results:
        for split_pos in range(2, len(word)):
            stem = word[:split_pos]
            ending = word[split_pos:]
            
            if stem in stem_set and ending in noun_endings:
                for lemma_entry in lemmas:
                    lemma, pos, type_code, meaning, stems = lemma_entry
                    if pos not in noun_pos:
                        continue
                    if stem in [s for s in stems if s and s != 'zzz']:
                        # Extract declension number from type_code
                        # V/N: "1" → "1", ADJ: "J 3" → "3"
                        lemma_decl = type_code.split()[-1] if type_code else ''
                        for rule in noun_endings[ending]:
                            conj_code, case, number, gender, stem_type = rule
                            rule_decl = conj_code.split()[0] if conj_code else ''
                            if rule_decl and rule_decl == lemma_decl:
                                results.append({
                                    'word': word,
                                    'lemma': lemma,
                                    'pos': pos,
                                    'case': case,
                                    'number': number,
                                    'gender': gender,
                                    'type_code': type_code,
                                    'stems': stems,
                                    'definition': meaning[:200],
                                })
                                break
    
    return results


def _find_lemma_by_conj(lemmas, conj_code):
    """Find a lemma matching a given conjugation code."""
    conj_digit = conj_code.split()[0] if conj_code else ''
    for lemma, pos, type_code, meaning, stems in lemmas:
        if pos == 'V' and type_code == conj_digit:
            return lemma
    return None


def format_morph_tags(analysis):
    """Format morphological analysis tags into a human-readable string."""
    pos_code = analysis.get('pos', '')
    pos = POS_MAP.get(pos_code, pos_code)
    
    tags = []
    
    if analysis.get('person'):
        p = analysis['person']
        tags.append({'1': '1st', '2': '2nd', '3': '3rd'}.get(p, p + 'rd'))
    
    if analysis.get('number'):
        tags.append(NUMBER_MAP.get(analysis['number'], analysis['number']))
    
    if analysis.get('tense'):
        tags.append(TENSE_MAP.get(analysis['tense'], analysis['tense']))
    
    if analysis.get('mood'):
        tags.append(MOOD_MAP.get(analysis['mood'], analysis['mood']))
    
    if analysis.get('voice'):
        tags.append(VOICE_MAP.get(analysis['voice'], analysis['voice']))
    
    if analysis.get('case'):
        tags.append(CASE_MAP.get(analysis['case'], analysis['case']))
    
    if analysis.get('gender') and analysis['gender'] in GENDER_MAP:
        tags.append(GENDER_MAP[analysis['gender']])
    
    tags_str = ' '.join(tags) if tags else ''
    return '{} {}'.format(pos, tags_str).strip()


def clean_latin_definition(raw_def, lemma_info=None):
    """
    Clean a raw dictionary definition into a concise summary.
    
    Extracts just the headword, principal parts, and general meaning,
    stripping away the long citation lists and specific usage examples.
    
    If lemma_info (from DICTLINE) is provided, uses its short meaning.
    """
    if not raw_def:
        return ''
    
    # Try to use Whitaker's Words short definition if available
    if lemma_info and len(lemma_info) < 300:
        # Format: "1 DEP X X X A O follow; escort; ..."
        # Strip the leading flag codes (number + uppercase words) to get just the definition
        clean = lemma_info
        # Remove leading number and all-caps flag words
        import re as _re
        # Pattern: starts with digit(s) followed by uppercase words, then lowercase definition
        clean = _re.sub(r'^\d+\s+[A-Z]+\s+', '', clean)
        # Remove any remaining flag codes (patterns of uppercase letters) before the definition
        # Flag codes are usually: X, A, B, C, D, E, F, L, O, S, T, N, M, P etc. in groups
        clean = _re.sub(r'\b[A-Z](?:\s+[A-Z]){2,}\s+', '', clean)
        # Remove trailing semicolons and whitespace
        clean = clean.strip().strip(';|').strip()
        if clean and len(clean) < 300:
            return clean
    
    # Fallback: extract summary from Lewis & Short entry
    # We want just the headword info and general meaning, NOT citations
    
    text = raw_def
    
    # Remove the etymological info in brackets (contains author names)
    text = re.sub(r'\[.*?\]', '', text)
    
    # Strip parenthetical notes that are just cross-references
    text = re.sub(r'\([^)]*\b(cf\.|id\.|ib\.|ibid\.|l\.l\.|s\.v\.|sqq?\.)[^)]*\)', '', text)
    
    # Find the first citation author name and truncate there
    # These are the boundaries between definition and citations
    author_pattern = r'(?:^|[.;])\s*(?=(?:Plaut|Cic|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.|Id\.|Ib\.)\.)'
    author_match = re.search(author_pattern, text)
    if author_match:
        text = text[:author_match.start() + 1]  # Keep up to the boundary
        # Also filter any "Lit." "Absol." sense markers that appear after this
        sense_pattern = r'(?:^|[.;])\s*(?=(?:Absol|Transf?|Metaph?|Esp\.|Freq\.|Poet\.|In\s+gen\.|In\s+partic\.|In\s+pass\.|With\s+acc\.|With\s+dat\.|With\s+gen\.|With\s+abl\.|With\s+inf\.|With\s+ut|With\s+ne|With\s+clause)\b)'
        sense_match = re.search(sense_pattern, text)
        if sense_match and sense_match.start() > 0:
            text = text[:sense_match.start() + 1]
    
    # If we still have pipe symbols, take only the first few segments
    pipes = [i for i, ch in enumerate(text) if ch == '|']
    if len(pipes) >= 3:
        text = text[:pipes[2]]
    elif len(pipes) == 2:
        text = text[:pipes[1]]
    
    # Clean up multiple spaces, trim
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation artifacts
    text = re.sub(r'[;,.]+$', '', text).strip()
    
    # Limit length
    if len(text) > 400:
        text = text[:397] + '...'
    
    return text


def format_full_entry(raw_def, truncate=True):
    """
    Format a raw Lewis & Short entry into clean, readable HTML.
    Splits on pipe separators and formats each section nicely.
    
    If truncate=True (default), long citation sections are shortened.
    If truncate=False, the complete entry is shown (for dictionary modal).
    """
    if not raw_def:
        return ''
    
    text = raw_def
    
    # Split on pipe separators
    sections = [s.strip() for s in text.split('|')]
    
    html_parts = []
    for i, section in enumerate(sections):
        if not section:
            continue
        
        # Headword section (first one)
        if i == 0:
            # Extract headword (first word before any space/punctuation)
            headword_match = re.match(r'^([^\s,;:]+)', section)
            headword = headword_match.group(1) if headword_match else ''
            rest = section[len(headword):].strip() if headword else section
            html_parts.append(
                '<div style="font-size:1.1em;font-weight:700;color:#4a2c1a;margin-bottom:4px;">{}</div>'
                '<div style="font-size:0.9em;color:#444;margin-bottom:8px;">{}</div>'.format(headword, rest)
            )
        
        # Principal parts and grammar sections
        elif i <= 4:
            cleaned = re.sub(r'\s+', ' ', section).strip()
            if cleaned:
                display = cleaned
                if truncate and len(display) > 300:
                    display = display[:297] + '...'
                html_parts.append(
                    '<div style="margin:2px 0;color:#2f2a24;line-height:1.5;font-size:0.92em;">{}</div>'.format(display)
                )
        
        # Specific senses — format citations nicely
        else:
            # Try to split into sense label and content, but only if the label
            # looks like a real sense heading (short, starts with uppercase, ends with period)
            sense_label = ''
            content = section
            sense_match = re.match(
                r'^((?:Lit|In\s+gen\.|In\s+partic\.|In\s+pass\.|In\s+reflex\.|'
                r'With\s+acc\.|With\s+dat\.|With\s+gen\.|With\s+abl\.|With\s+inf\.|'
                r'With\s+ut|With\s+ne|With\s+quo|With\s+clause|'
                r'Absol\.|Poet\.|Transf\.|Metaph?\.|Esp\.|Freq\.|Usually|Often)'
                r'[.:])\s*',
                section, re.IGNORECASE
            )
            if sense_match:
                sense_label = sense_match.group(1).strip()
                content = section[sense_match.end():].strip()
            
            html_parts.append('<div style="margin:8px 0 4px 8px;border-left:2px solid #c9a87c;padding-left:10px;">')
            
            if sense_label:
                html_parts.append(
                    '<div style="font-weight:600;color:#7a5a3a;font-size:0.88em;margin-bottom:2px;">{}</div>'.format(sense_label)
                )
            
            # Split into individual citations on comma/semicolon before author or "id."
            display = content
            if truncate and len(display) > 800:
                display = display[:797] + '...'
            
            # Protect parenthetical groups from being split
            paren_map = {}
            def protect_paren(m):
                key = '\x00P{}\x00'.format(len(paren_map))
                paren_map[key] = m.group(0)
                return key
            display = re.sub(r'\([^)]*\)', protect_paren, display)
            
            # Split on: (comma/semicolon) + (space) + (major author abbreviation)
            # Only split on major authors, NOT on id./ib. which are internal references
            # Also don't split on period since it breaks up sentence endings before id./ib.
            citation_parts = re.split(
                r'(?<=[,;])\s+(?='
                r'(?:Cic|Plaut|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.)\.)',
                display
            )
            
            # Restore parenthetical groups
            citation_parts = [re.sub(r'\x00P\d+\x00', lambda m: paren_map.get(m.group(0), m.group(0)), p) for p in citation_parts]
            
            # Merge consecutive citation parts that start with id./ib. (internal references)
            merged = [citation_parts[0]] if citation_parts else []
            for part in citation_parts[1:]:
                if part.strip().startswith(('id.', 'ib.', 'ibid.')) and merged:
                    merged[-1] = merged[-1] + ', ' + part
                else:
                    merged.append(part)
            citation_parts = merged
            
            # The first part is usually the definition text before citations
            if len(citation_parts) > 1:
                first = citation_parts[0].strip()
                # If the first part doesn't start with an author/id, show it as definition
                if not re.match(r'^(?:Cic|Plaut|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.|id\.|ib\.|ibid\.)', first):
                    # Bold any author references in the definition text
                    first = re.sub(
                        r'\b((?:Cic|Plaut|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.)\.)',
                        r'<b style="color:#5a3a1a;">\1</b>', first
                    )
                    html_parts.append(
                        '<div style="color:#2f2a24;font-size:0.9em;line-height:1.55;margin-bottom:6px;">{}</div>'.format(first)
                    )
                    citation_parts = citation_parts[1:]
            
            if len(citation_parts) <= 1:
                # No citations parseable — show as single block
                display = re.sub(
                    r'\b((?:Cic|Plaut|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.)\.)'
                    r'(?:\s*(?:ap\.|ex|et|in|ad|de|apud|vid\.|cf\.|s\.\s*v\.|l\.\s*l\.|sqq?\.|init\.|med\.|fin\.|inf\.)?)',
                    r'<b style="color:#5a3a1a;">\1</b>',
                    display
                )
                display = re.sub(r'\b(id\.|ib\.|ibid\.)\b', r'<i style="color:#7a6a5a;">\1</i>', display)
                html_parts.append(
                    '<div style="color:#444;font-size:0.85em;line-height:1.65;">{}</div>'.format(display)
                )
            else:
                for ci, part in enumerate(citation_parts):
                    part = part.strip()
                    if not part:
                        continue
                    # Bold the author at the start
                    part = re.sub(
                        r'^((?:Cic|Plaut|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.)\.)',
                        r'<b style="color:#5a3a1a;">\1</b>',
                        part
                    )
                    # Highlight id./ib. references
                    part = re.sub(r'\b(id\.|ib\.|ibid\.)\b', r'<i style="color:#7a6a5a;">\1</i>', part)
                    # Also bold any other author names within the citation
                    part = re.sub(
                        r'\b((?:Cic|Plaut|Ter|Verg|Hor|Ov|Liv|Caes|Catull|Tib|Prop|Plin|Quint|Tac|Suet|Stat|Lucr|Juv|Mart|Sen|Curt|Just|Gell|Nep|Phaedr|Enn|Lucil|Pacuv|Acc|Afran|Caecil|Apul|Amm|Eutr|Fest|Prisc|Charis|Diom|Don|Serv|Schol|Aug|Hier|Ambros|Greg|Isid|H\.)\.)'
                        r'(?:\s*(?:ap\.|ex|et|in|ad|de|apud|vid\.|cf\.|s\.\s*v\.|l\.\s*l\.|sqq?\.|init\.|med\.|fin\.|inf\.)?)',
                        r'<b style="color:#5a3a1a;">\1</b>',
                        part
                    )
                    html_parts.append(
                        '<div style="margin:3px 0;color:#444;font-size:0.85em;line-height:1.5;padding-left:4px;">'
                        '&bull; {}</div>'.format(part)
                    )
            
            
            html_parts.append('</div>')
    
    if not html_parts:
        return '<div style="color:#555;">{}</div>'.format(text[:500])
    
    return ''.join(html_parts)


def format_lemma_summary(lemma, pos_code, type_code, stems, meaning):
    """
    Format a clean lemma summary line like:
    "sequor, sequi, secutus sum (3, dep.)"
    """
    # Generate principal parts from stems
    if pos_code == 'V' and stems:
        stem1 = stems[0] if len(stems) > 0 else ''
        stem2 = stems[1] if len(stems) > 1 else stem1
        stem3 = stems[2] if len(stems) > 2 and stems[2] != 'zzz' else ''
        stem4 = stems[3] if len(stems) > 3 and stems[3] != 'zzz' else ''
        
        parts = [lemma]
        
        # Determine conjugation info suffix
        is_dep = 'DEP' in meaning
        conj_num = type_code.split()[0] if type_code else '?'
        
        # Infinitive (2nd principal part)
        if is_dep and conj_num == '3':
            infin = stem1 + 'i'
        elif conj_num == '1':
            infin = stem1 + 'are'
        elif conj_num == '2':
            infin = stem2 + 're' if stem2 and stem2 != stem1 else stem1 + 'ere'
        elif conj_num == '3':
            infin = stem1 + 'ere'
        elif conj_num == '4':
            infin = stem1 + 'ire'
        else:
            infin = stem2 if stem2 != stem1 else ''
        
        if infin:
            parts.append(infin)
        
        # Perfect (3rd principal part)
        if stem3:
            parts.append(stem3 + 'i')
        
        # Participial/supine (4th principal part)
        if stem4:
            if is_dep:
                parts.append(stem4 + 'us sum')
            else:
                parts.append(stem4 + 'um')
        
        # Conjugation info in parentheses
        info_parts = []
        if conj_num:
            conj_names = {'1': '1st', '2': '2nd', '3': '3rd', '4': '4th'}
            info_parts.append(conj_names.get(conj_num, conj_num))
        if is_dep:
            info_parts.append('dep.')
        
        if info_parts:
            parts[-1] = parts[-1] + ' (' + ', '.join(info_parts) + ')'
        
        return ', '.join(parts)
    
    elif pos_code == 'N' and stems:
        # For nouns: nominative, genitive ending, gender
        stem1 = stems[0] if len(stems) > 0 else lemma
        stem2 = stems[1] if len(stems) > 1 else ''
        
        decl_num = type_code.split()[0] if type_code else '?'
        decl_names = {'1': '1st', '2': '2nd', '3': '3rd', '4': '4th', '5': '5th'}
        
        # Determine gender from meaning flags (M, F, N near the start of meaning)
        gender_hint = ''
        if meaning:
            gender_match = re.search(r'\b([MFN])\s+[TF]', meaning)
            if gender_match:
                g = gender_match.group(1)
                gender_hint = {'M': 'm', 'F': 'f', 'N': 'n'}.get(g, '')
        
        gen_form = ''
        if stem2 and stem2 != stem1:
            # Try to generate genitive form
            for decl_test, gen_end in [('1', 'ae'), ('2', 'i'), ('3', 'is'), ('4', 'us'), ('5', 'ei')]:
                if decl_num == decl_test:
                    gen_form = stem2 + gen_end
                    break
        
        if gen_form:
            return '{}, {} ({}{})'.format(
                lemma, gen_form,
                decl_names.get(decl_num, decl_num),
                ', ' + gender_hint if gender_hint else ''
            )
        else:
            return '{} ({}{})'.format(
                lemma,
                decl_names.get(decl_num, decl_num),
                ', ' + gender_hint if gender_hint else ''
            )
    
    elif pos_code == 'ADJ' and stems:
        # For adjectives: all stem forms
        stem1 = stems[0] if len(stems) > 0 else lemma
        return '{} (adj.)'.format(lemma)
    
    return lemma


# ── Greek Definition Formatting ────────────────────────────────────────────

_LSJ_AUTHOR_ABBRS = (
    'Hom', 'Hes', 'Pi', 'Pind', 'Bacch', 'Aesch', 'Soph', 'Eur', 'Ar', 'Aristoph',
    'Hdt', 'Thuc', 'Xen', 'Pl', 'Plat', 'Arist', 'Aristot', 'Dem', 'Demosth',
    'Lys', 'Isocr', 'Isae', 'Aeschin', 'Lycurg', 'Dinarch', 'Antiph',
    'Andoc', 'Hyperid', 'Polyb', 'Diod', 'Plut', 'Luc', 'Lucian',
    'Paus', 'Strab', 'Arr', 'App', 'Dio Cass', 'Hdn', 'Herodian',
    'Ael', 'Alciphr', 'Aret', 'Ath', 'Athen', 'Charit', 'Clem Al',
    'Dioscor', 'Epict', 'Galen', 'Heliod', 'Hippoc', 'Jos', 'Jus',
    'Longus', 'Menand', 'Origen', 'Philo', 'Philostr', 'Plot',
    'Plut', 'Poll', 'Polyb', 'Porph', 'Procop', 'Ptol', 'Quint Sm',
    'Sext Emp', 'Stob', 'Them', 'Theocr', 'Theophr', 'Xenoph',
    'IG', 'CIG', 'CIL', 'OGI', 'SIG', 'BGU', 'P', 'PAmh', 'PCair',
    'PFlor', 'PGrenf', 'PLond', 'POxy', 'PSI', 'PTebt',
    'ABV', 'ARV', 'DK', 'FGrHist', 'LSJ', 'RE', 'TAM',
)

# Also include common patterns
_LSJ_AUTHOR_RE = re.compile(
    r'\b((?:' + '|'.join(_LSJ_AUTHOR_ABBRS) + r')\.(?:\s+(?:ap\.|et|ex|in|ad|de|apud|vid\.|cf\.|s\.\s*v\.|l\.\s*l\.|sqq?\.|init\.|med\.|fin\.|inf\.)?)?)'
)


def beta_def_to_greek(text):
    """Convert a string containing Beta Code to Unicode Greek.
    Applies beta_to_greek to the whole string."""
    return beta_to_greek(text)


def clean_greek_definition(raw_def, lemma_greek=''):
    """Extract a short clean definition from an LSJ entry.
    Handles both clean English (<tr> extracted) and Beta Code entries.
    """
    if not raw_def:
        return ''
    text = re.sub(r'\s+', ' ', raw_def).strip()
    
    # Detect Beta Code (letter + diacritic + letter = three-char pattern)
    has_beta = bool(re.search(r'[a-zA-Z][)(/\\=][a-zA-Z]', text))
    if has_beta:
        text = beta_to_greek(text)
    
    first = text.split('|')[0].strip()
    first = re.sub(r'[,;\s]+$', '', first).strip()
    if not first:
        return text[:200]
    return first[:250]


def format_greek_entry(raw_def, truncate=True):
    """Format a raw LSJ entry as HTML. Converts Beta Code to Greek."""
    if not raw_def:
        return ''
    text = re.sub(r'\s+', ' ', raw_def).strip()
    
    # Detect Beta Code (letter + diacritic + letter = three-char pattern)
    has_beta = bool(re.search(r'[a-zA-Z][)(/\\=][a-zA-Z]', text))
    
    if has_beta:
        # Full Beta Code → Greek conversion for entries without <tr> elements
        text = beta_to_greek(text)
    
    sections = [s.strip() for s in text.split('|')]
    html_parts = []
    for i, section in enumerate(sections):
        if not section:
            continue
        if i == 0:
            hw = re.match(r'^([^\s,;:]+)', section)
            headword = hw.group(1) if hw else ''
            rest = section[len(headword):].strip() if headword else section
            html_parts.append(
                '<div style="font-size:1.1em;font-weight:700;color:#4a2c1a;margin-bottom:4px;">{}</div>'
                '<div style="font-size:0.9em;color:#444;margin-bottom:8px;">{}</div>'.format(
                    html.escape(headword), html.escape(rest)))
        elif i <= 3:
            cleaned = re.sub(r'\s+', ' ', section).strip()
            if cleaned:
                if truncate and len(cleaned) > 200:
                    cleaned = cleaned[:197] + '...'
                html_parts.append(
                    '<div style="margin:2px 0;color:#2f2a24;line-height:1.5;font-size:0.92em;">{}</div>'.format(
                        html.escape(cleaned)))
        else:
            display = re.sub(r'\s+', ' ', section).strip()
            if not display:
                continue
            if truncate and len(display) > 400:
                display = display[:397] + '...'
            display = _LSJ_AUTHOR_RE.sub(r'<b style="color:#5a3a1a;">\1</b>', display)
            display = re.sub(r'(?<=[,;.])\s+(?=\d+\.\d+)', r'<br>', display)
            display = re.sub(r'(?<=[.;])\s+(?=[A-Z][a-z]+\.\s)', r'<br>', display)
            html_parts.append(
                '<div style="margin:6px 0 4px 8px;border-left:2px solid #c9a87c;padding-left:10px;'
                'color:#333;font-size:0.9em;line-height:1.6;">{}</div>'.format(display))
    if not html_parts:
        return '<div style="color:#555;">{}</div>'.format(html.escape(text[:500]))
    return ''.join(html_parts)


def parse_lsj_entry(xml_path):
    """Extract dictionary entries from LSJ/Lewis & Short XML (TEI P4 format)."""
    entries = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception:
        return entries

    # TEI P4 dictionary format uses <entryFree> (not <entry>), and no namespace
    for entry in root.iter("entryFree"):
        # Get the headword from the first <orth> element
        orth = entry.find("orth")
        if orth is not None and orth.text:
            raw = orth.text.strip()
        else:
            continue
        
        if not raw:
            continue
        
        # Detect if this is a Beta Code (Greek) entry or a Latin entry
        # Beta Code entries contain diacritic markers like ), (, /, \, =, *, |
        has_beta_marks = any(m in raw for m in ')(/\\=*|')
        
        import unicodedata
        
        if has_beta_marks:
            # Greek entry: convert Beta Code to Unicode Greek
            headword_greek = beta_to_greek(raw)
            headword_greek = ' '.join(headword_greek.split())
            headword = raw  # Keep original Beta Code as headword
            
            # Plain form from the Greek version (diacritic-stripped, lowered)
            nfkd = unicodedata.normalize('NFKD', headword_greek)
            headword_plain = ''.join(
                c for c in nfkd.lower() if unicodedata.category(c) != 'Mn'
            )
            headword_plain = headword_plain.replace('\u03c2', '\u03c3')
            
            # ── For Greek (LSJ): extract English definitions from <tr> elements ──
            # <tr> (translation) elements contain the actual English definitions
            tr_texts = []
            for tr in entry.iter("tr"):
                t = tr.text.strip() if tr.text else ''
                tail = tr.tail.strip() if tr.tail else ''
                combined = (t + ' ' + tail).strip()
                if combined:
                    tr_texts.append(combined)
            
            if tr_texts:
                full_def = " | ".join(tr_texts[:8])
                if len(tr_texts) > 8:
                    full_def += f" ... (+{len(tr_texts)-8} more)"
            else:
                # Fallback: use sense text (as before)
                all_sense_texts = []
                for sense in entry.iter("sense"):
                    sense_text = "".join(sense.itertext()).strip()
                    if sense_text:
                        all_sense_texts.append(sense_text)
                direct_text_parts = []
                for child in entry:
                    if child.tag not in ("sense", "entryFree", "entry"):
                        t = "".join(child.itertext()).strip()
                        if t:
                            direct_text_parts.append(t)
                def_parts = direct_text_parts + all_sense_texts
                full_def = " | ".join(def_parts[:8])
                if len(def_parts) > 8:
                    full_def += f" ... (+{len(def_parts)-8} more)"
        else:
            # Latin entry: no Beta Code conversion needed
            headword = raw
            headword_greek = ""  # No Greek version for Latin headwords
            
            # Plain form: diacritic-stripped, lowered
            nfkd = unicodedata.normalize('NFKD', raw)
            headword_plain = ''.join(
                c for c in nfkd.lower() if unicodedata.category(c) != 'Mn'
            )
            
            # ── For Latin: keep existing approach ──
            all_sense_texts = []
            for sense in entry.iter("sense"):
                sense_text = "".join(sense.itertext()).strip()
                if sense_text:
                    all_sense_texts.append(sense_text)
            direct_text_parts = []
            for child in entry:
                if child.tag not in ("sense", "entryFree", "entry"):
                    t = "".join(child.itertext()).strip()
                    if t:
                        direct_text_parts.append(t)
            def_parts = direct_text_parts + all_sense_texts
            full_def = " | ".join(def_parts[:8])
            if len(def_parts) > 8:
                full_def += f" ... (+{len(def_parts)-8} more)"
        
        # Truncate very long definitions for display
        if len(full_def) > 800:
            full_def = full_def[:797] + "..."
        
        entries.append((headword, headword_greek, headword_plain, full_def))
    
    return entries


# ── Database indexing ──────────────────────────────────────────────────────

def init_db():
    """Create the SQLite database schema."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS texts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT NOT NULL,
            author      TEXT,
            title       TEXT,
            lang        TEXT,
            category    TEXT,
            filepath    TEXT,
            full_text   TEXT,
            word_count  INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS dictionary_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            headword        TEXT NOT NULL,
            headword_greek  TEXT,
            headword_plain  TEXT,
            definition      TEXT,
            source          TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_texts_author ON texts(author);
        CREATE INDEX IF NOT EXISTS idx_texts_title ON texts(title);
        CREATE INDEX IF NOT EXISTS idx_texts_lang ON texts(lang);
        CREATE INDEX IF NOT EXISTS idx_dict_headword ON dictionary_entries(headword);
        CREATE INDEX IF NOT EXISTS idx_dict_headword_plain ON dictionary_entries(headword_plain);
        
        CREATE VIRTUAL TABLE IF NOT EXISTS texts_fts USING fts5(
            author, title, full_text, content='texts', content_rowid='id'
        );
        
        CREATE VIRTUAL TABLE IF NOT EXISTS dict_fts USING fts5(
            headword, headword_greek, headword_plain, definition, content='dictionary_entries', content_rowid='id'
        );
    """)
    conn.commit()
    return conn


def index_greek_latin_texts(conn, data_dir, category):
    """Walk through Greek/Latin text directories and index all TEI XML files."""
    source_dir = data_dir / category
    if not source_dir.exists():
        log(f"  Source directory not found: {source_dir}")
        return
    
    # Clean old entries of this category before re-indexing
    lang = "grc" if category == "greek" else "lat"
    cur = conn.cursor()
    cur.execute("DELETE FROM texts WHERE lang = ?", (lang,))
    deleted = cur.rowcount
    if deleted:
        log(f"  Cleared {deleted} old {category} entries")

    xml_files = list(source_dir.rglob("*.xml"))
    log(f"  Found {len(xml_files)} XML files in {category}")
    
    cur = conn.cursor()
    count = 0
    
    for xml_path in xml_files:
        # Skip non-TEI files
        if xml_path.stat().st_size == 0:
            continue
        
        text, author, title = extract_tei_text(xml_path)
        if text and len(text) > 50:  # Skip very tiny fragments
            rel_path = str(xml_path.relative_to(DATA_DIR))
            lang = "grc" if category == "greek" else "lat"
            
            # Determine a better title from filename if missing
            if not title:
                title = xml_path.stem
            
            cur.execute(
                "INSERT INTO texts (filename, author, title, lang, category, filepath, full_text, word_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    xml_path.name,
                    author or "Unknown",
                    title,
                    lang,
                    category,
                    rel_path,
                    text,
                    len(text.split()),
                ),
            )
            count += 1
            
            if count % 100 == 0:
                log(f"    Indexed {count} texts...")
    
    log(f"  Indexed {count} texts from {category}")
    return count


def index_lexica(conn, data_dir):
    """Index dictionary entries from the lexica repository."""
    lex_dir = data_dir / "lexica" / "CTS_XML_TEI" / "perseus" / "pdllex"
    if not lex_dir.exists():
        log(f"  Lexica directory not found: {lex_dir}")
        return

    cur = conn.cursor()
    total_entries = 0

    # Clean old entries before re-indexing (in case of re-run)
    for src in ('LSJ', 'Lewis & Short'):
        cur.execute("DELETE FROM dictionary_entries WHERE source = ?", (src,))
        log(f"  Cleared {cur.rowcount} old {src} entries")

    # Process LSJ (Greek-English)
    lsj_dir = lex_dir / "grc" / "lsj"
    if lsj_dir.exists():
        for xml_file in sorted(lsj_dir.glob("*.xml")):
            if xml_file.name == "README.md":
                continue
            log(f"  Parsing LSJ: {xml_file.name}")
            entries = parse_lsj_entry(xml_file)
            for headword, headword_greek, headword_plain, definition in entries:
                cur.execute(
                    "INSERT INTO dictionary_entries (headword, headword_greek, headword_plain, definition, source) VALUES (?, ?, ?, ?, ?)",
                    (headword, headword_greek, headword_plain, definition, "LSJ"),
                )
            total_entries += len(entries)
            log(f"    {len(entries)} entries from {xml_file.name}")

    # Process Lewis & Short (Latin-English)
    ls_dir = lex_dir / "lat" / "ls"
    if ls_dir.exists():
        for xml_file in sorted(ls_dir.glob("*.xml")):
            log(f"  Parsing Lewis & Short: {xml_file.name}")
            entries = parse_lsj_entry(xml_file)
            for headword, headword_greek, headword_plain, definition in entries:
                cur.execute(
                    "INSERT INTO dictionary_entries (headword, headword_greek, headword_plain, definition, source) VALUES (?, ?, ?, ?, ?)",
                    (headword, headword_greek, headword_plain, definition, "Lewis & Short"),
                )
            total_entries += len(entries)
            log(f"    {len(entries)} entries from {xml_file.name}")

    log(f"  Total dictionary entries indexed: {total_entries}")
    return total_entries


def rebuild_fts(conn):
    """Rebuild FTS indexes from the main tables."""
    log("  Rebuilding full-text search indexes...")
    cur = conn.cursor()
    # Drop and recreate FTS tables to avoid content-sync issues
    cur.executescript("""
        DROP TABLE IF EXISTS texts_fts;
        DROP TABLE IF EXISTS dict_fts;
        
        CREATE VIRTUAL TABLE texts_fts USING fts5(
            author, title, full_text, content='texts', content_rowid='id'
        );
        CREATE VIRTUAL TABLE dict_fts USING fts5(
            headword, headword_greek, headword_plain, definition,
            content='dictionary_entries', content_rowid='id'
        );
        
        INSERT INTO texts_fts (rowid, author, title, full_text)
        SELECT id, author, title, full_text FROM texts;
        
        INSERT INTO dict_fts (rowid, headword, headword_greek, headword_plain, definition)
        SELECT id, headword, headword_greek, headword_plain, definition FROM dictionary_entries;
    """)
    conn.commit()
    log("  FTS indexes built.")


# ── Web Server ─────────────────────────────────────────────────────────────

HTML_CSS = """
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', 'Linux Libertine', Georgia, serif; 
           background: #f5f0eb; color: #1a1a1a; line-height: 1.7; }
    .container { max-width: 1000px; margin: 0 auto; padding: 10px; }
    
    header { background: #4a2c1a; color: #f5f0eb; padding: 20px 0; 
             border-bottom: 4px solid #c9a87c; }
    header h1 { font-size: 1.8em; font-weight: 400; letter-spacing: 1px; }
    header p { opacity: 0.8; font-size: 0.9em; margin-top: 4px; }
    
    nav { background: #fff; padding: 12px 0; border-bottom: 1px solid #ddd; 
          position:sticky; top:0; z-index:100; box-shadow:0 1px 6px rgba(0,0,0,0.06); }
    nav a { color: #4a2c1a; text-decoration: none; margin-right: 20px; 
            font-weight: 500; padding: 4px 8px; border-radius: 3px; }
    nav a:hover { background: #f5f0eb; }
    nav a.active { background: #4a2c1a; color: #f5f0eb; }

    /* In-text search highlight */
    .search-hl { background:#f0d878; border-radius:2px; padding:0 1px; }
    .search-hl-active { background:#e8b830; border-radius:2px; padding:0 1px; }
    
    .search-box { display: flex; gap: 8px; margin: 20px 0; flex-wrap: wrap; }
    .search-box input[type=text] { flex: 1; padding: 10px 14px; font-size: 1em;
        min-width: 200px;
        border: 2px solid #c9a87c; border-radius: 4px; background: #fff; }
    .search-box input[type=text]:focus { outline: none; border-color: #8b6914; }
    .search-box select { padding: 10px; border: 2px solid #c9a87c; border-radius: 4px;
        background: #fff; font-size: 0.9em; cursor: pointer; }
    .search-box select:focus { outline: none; border-color: #8b6914; }
    .search-box button { padding: 10px 24px; background: #4a2c1a; color: #fff;
        border: none; border-radius: 4px; font-size: 1em; cursor: pointer; white-space: nowrap; }
    .search-box button:hover { background: #6b4226; }
    
    .browse-links { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 20px 0; }
    .browse-card { background: #fff; border-radius: 6px; padding: 20px; 
                   box-shadow: 0 1px 4px rgba(0,0,0,0.1); text-decoration: none; color: inherit; }
    .browse-card:hover { box-shadow: 0 3px 12px rgba(0,0,0,0.15); transform: translateY(-1px); }
    .browse-card h3 { color: #4a2c1a; margin-bottom: 6px; }
    .browse-card p { font-size: 0.85em; color: #666; }
    
    .stats { display: flex; gap: 20px; margin: 24px 0; flex-wrap: wrap; }
    .stat-box { background: #fff; padding: 16px 24px; border-radius: 6px; 
                flex: 1; min-width: 140px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
    .stat-box .num { font-size: 1.8em; font-weight: 700; color: #4a2c1a; }
    .stat-box .label { font-size: 0.8em; color: #888; margin-top: 2px; }
    
    .result-item { background: #fff; border-radius: 4px; padding: 14px 18px; 
                   margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .result-item h4 { color: #4a2c1a; }
    .result-item .meta { font-size: 0.8em; color: #888; margin: 4px 0; }
    .result-item .snippet { font-size: 0.9em; color: #444; max-height: 80px; 
                            overflow: hidden; }
    .result-item .snippet em { background: #fce8c8; font-style: normal; }
    .result-item .dict-def { font-size: 0.9em; color: #333; }
    
    .text-viewer { background: #fff; padding: 20px 20px; border-radius: 6px;
                   box-shadow: 0 1px 4px rgba(0,0,0,0.1); line-height: 1.9; }
    .text-viewer .text-title { font-size: 1.6em; border-bottom: 2px solid #c9a87c;
                               padding-bottom: 10px; margin-bottom: 20px; }
    .text-viewer .text-author { color: #666; font-style: italic; margin-bottom: 16px; }
    .text-viewer p { margin-bottom: 12px; text-indent: 0; }
    .text-viewer .text-grc { font-family: 'Linux Libertine', 'Gentium Plus', 'Palatino Linotype', serif; }
    
    .dict-entry { padding: 10px 0; border-bottom: 1px solid #eee; }
    .dict-entry .headword { font-weight: 700; color: #4a2c1a; font-size: 1.1em; }
    .dict-entry .source { font-size: 0.75em; color: #aaa; margin-left: 8px; }
    
    .pagination { margin: 20px 0; text-align: center; }
    .pagination a { display: inline-block; padding: 6px 14px; margin: 0 3px; 
                    background: #fff; border: 1px solid #ddd; border-radius: 3px;
                    text-decoration: none; color: #4a2c1a; }
    .pagination a:hover { background: #4a2c1a; color: #fff; }
    
    .perseus-footer { text-align: center; font-size: 0.8em; color: #999;
                      padding: 30px 0 20px; }
    .perseus-footer a { color: #4a2c1a; }
    
    @media (max-width: 700px) {
        .browse-links { grid-template-columns: 1fr; }
        .stats { flex-direction: column; }
        .text-viewer { padding: 16px; }
    }
</style>
"""

HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Perseus Minimalist v0.1</title>
<link rel="icon" type="image/png" href="/static/perseus_logo.png">
""" + HTML_CSS + """
</head>
<body>
<header><div class="container"><h1><a href="/" style="text-decoration:none;color:inherit;"><img src="/static/perseus_logo.png" style="height:1.1em;width:1.1em;border-radius:50%;vertical-align:middle;margin-right:6px;" alt=""></a> <a href="/" style="text-decoration:none;color:inherit;">Perseus Minimalist</a> <span style="font-size:0.5em;color:#c9a87c;">v0.1</span></h1>
<p>Classical Texts — Greek &amp; Latin — Local Edition</p></div></header>
<nav><div class="container">
<a href="/" class="active">Home</a>
<a href="/browse?lang=grc">Greek Texts</a>
<a href="/browse?lang=lat">Latin Texts</a>
<a href="/dictionary">Dictionaries</a>
<a href="/about">About</a>
</div></nav>
<div class="container">
"""

HTML_FOOTER = """
<script>
(function() {
    var links = document.querySelectorAll('nav a');
    var path = window.location.pathname;
    links.forEach(function(a) {
        a.classList.remove('active');
        var href = a.getAttribute('href');
        if (href === '/dictionary' && path === '/dictionary') a.classList.add('active');
        else if (href === '/about' && path === '/about') a.classList.add('active');
        else if ((href === '/browse?lang=grc' || href === '/browse?lang=lat') && (path === '/browse' || path === '/read')) {
            var lang = new URLSearchParams(window.location.search).get('lang');
            // For /read pages, read language from the viewer data attribute
            if (path === '/read' || !lang) {
                var viewer = document.querySelector('.text-viewer');
                if (viewer) lang = viewer.getAttribute('data-lang');
            }
            var targetLang = href === '/browse?lang=grc' ? 'grc' : 'lat';
            if (lang === targetLang) a.classList.add('active');
        }
        else if (href === '/' && path === '/') a.classList.add('active');
    });
})();
</script>
<div class="perseus-footer">
<p><a href="https://github.com/Yusufalibozkir/Perseus_minimalist">Perseus Minimalist v0.1</a>
 — Classical texts from the <a href="http://www.perseus.tufts.edu/">Perseus Digital Library</a>, 
licensed under CC BY-SA 4.0.</p>
</div>
</div></body></html>"""


# ── Morphology Data Cache ──────────────────────────────────────────────────

_morphology_cache = None

def get_morphology_data():
    """Lazy-load morphology data, returns None if not available."""
    global _morphology_cache
    if _morphology_cache is None:
        try:
            _morphology_cache = load_latin_morphology()
        except Exception as e:
            log("  Morphology data not available: {}".format(e))
            _morphology_cache = False  # Don't retry on every request
    return _morphology_cache if _morphology_cache else None


# ── Greek NLP (CLTK) Cache ────────────────────────────────────────────────

_greek_nlp_cache = None

def get_greek_nlp():
    """Lazy-load CLTK Greek NLP pipeline. Returns None if not available."""
    global _greek_nlp_cache
    if _greek_nlp_cache is None:
        try:
            from cltk import NLP
            log("  Loading CLTK Greek NLP pipeline (may take ~10s on first call)...")
            _greek_nlp_cache = NLP(language_code='grc', suppress_banner=True)
            log("  Greek NLP pipeline ready.")
        except Exception as e:
            log("  Greek NLP not available: {}".format(e))
            _greek_nlp_cache = False
    return _greek_nlp_cache if _greek_nlp_cache else None


GRC_UPOS_LABELS = {
    'NOUN': 'Noun', 'VERB': 'Verb', 'ADJ': 'Adjective', 'ADV': 'Adverb',
    'PRON': 'Pronoun', 'DET': 'Determiner', 'ADP': 'Preposition',
    'CCONJ': 'Conjunction', 'SCONJ': 'Conjunction', 'CONJ': 'Conjunction',
    'PART': 'Particle', 'INTJ': 'Interjection', 'NUM': 'Numeral',
    'AUX': 'Auxiliary', 'X': 'Other',
}

PERSON_LABELS = {'1': '1st', '2': '2nd', '3': '3rd',
                 'First': '1st', 'Second': '2nd', 'Third': '3rd',
                 'First person': '1st', 'Second person': '2nd', 'Third person': '3rd'}

def format_greek_morph_tags(upos_tag, features_set):
    """Format CLTK Greek morphology features into a human-readable string.

    upos_tag: UDPartOfSpeechTag with .tag and .name
    features_set: UDFeatureTagSet iterable
    """
    pos_name = GRC_UPOS_LABELS.get(upos_tag.tag, upos_tag.name.capitalize() if upos_tag.name else upos_tag.tag)

    collected = {}
    for _key, tag_list in features_set:
        for tag in tag_list:
            d = tag.model_dump()
            collected[d['key']] = d['value_label']

    parts = [pos_name]

    # Order: Person → Number → Tense → Mood → Voice → Case → Gender → Degree → VerbForm
    for feat_key, label_key in [
        ('Person', None), ('Number', None), ('Tense', None),
        ('Mood', None), ('Voice', None), ('Case', None),
        ('Gender', None), ('Degree', None), ('Aspect', None),
    ]:
        val = collected.get(feat_key)
        if val:
            if feat_key == 'Person':
                val = PERSON_LABELS.get(val, val)
            parts.append(val)

    # Filter out technical VerbForm labels that would confuse
    # But keep Infinitive / Participle as they're meaningful
    vf = collected.get('VerbForm')
    if vf and vf not in ('Finite',):
        parts.append(vf)

    return ' '.join(parts)


class PerseusHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the offline Perseus viewer."""

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        path = self.path.split("?")[0]
        qs = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    qs[k] = urllib.parse.unquote_plus(v)

        try:
            if path == "/":
                self.handle_home(qs)
            elif path == "/browse":
                self.handle_browse(qs)
            elif path == "/read":
                self.handle_read(qs)
            elif path == "/search":
                self.handle_search(qs)
            elif path == "/dictionary":
                self.handle_dictionary(qs)
            elif path == "/lookup":
                self.handle_lookup(qs)
            elif path == "/parse":
                self.handle_parse(qs)
            elif path == "/about":
                self.handle_about()
            elif path.startswith("/static/"):
                self.serve_static(path)
            else:
                self.send_error(404, "Not Found")
        except Exception as e:
            try:
                self.send_error(500, "Internal server error")
            except Exception:
                pass

    def _html(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((HTML_HEADER + body + HTML_FOOTER).encode("utf-8"))

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def get_db(self):
        return sqlite3.connect(str(DB_PATH))

    def handle_home(self, qs):
        conn = self.get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM texts")
        total_texts = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM texts WHERE lang='grc'")
        greek_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM texts WHERE lang='lat'")
        latin_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM dictionary_entries")
        dict_entries = cur.fetchone()[0]
        
        cur.execute("SELECT SUM(word_count) FROM texts")
        total_words = cur.fetchone()[0] or 0
        
        conn.close()
        
        body = f"""
        <div class="stats">
            <div class="stat-box"><div class="num">{total_texts:,}</div><div class="label">Texts</div></div>
            <div class="stat-box"><div class="num">{greek_count:,}</div><div class="label">Greek Works</div></div>
            <div class="stat-box"><div class="num">{latin_count:,}</div><div class="label">Latin Works</div></div>
            <div class="stat-box"><div class="num">{dict_entries:,}</div><div class="label">Dictionary Entries</div></div>
            <div class="stat-box"><div class="num">{total_words:,}</div><div class="label">Total Words</div></div>
        </div>
        
        <form class="search-box" action="/search" method="get">
            <input type="text" name="q" placeholder="Search texts (e.g., 'amicitia', 'ἀρετή', 'Cicero')" 
                   value="{qs.get('q', '')}">
            <select name="scope">
                <option value="all">All fields</option>
                <option value="author">Author</option>
                <option value="title">Title</option>
            </select>
            <select name="lang">
                <option value="">All languages</option>
                <option value="grc">Greek only</option>
                <option value="lat">Latin only</option>
            </select>
            <button type="submit">Search</button>
        </form>
        
        <h2 style="margin-top:24px;color:#4a2c1a;">Browse by Collection</h2>
        <div class="browse-links">
            <a class="browse-card" href="/browse?lang=grc">
                <h3>🏛️ Greek Texts</h3>
                <p>{greek_count:,} works • Browse and search the Greek corpus</p>
            </a>
            <a class="browse-card" href="/browse?lang=lat">
                <h3>🏛️ Latin Texts</h3>
                <p>{latin_count:,} works • Browse and search the Latin corpus</p>
            </a>
            <a class="browse-card" href="/dictionary">
                <h3>📖 Dictionaries</h3>
                <p>{dict_entries:,} entries • LSJ (Greek–English) &amp; Lewis &amp; Short (Latin–English)</p>
            </a>
            <a class="browse-card" href="/search?q=">
                <h3>🔍 Full-Text Search</h3>
                <p>Search across the entire classical corpus</p>
            </a>
        </div>
        """
        self._html(body)

    def handle_browse(self, qs):
        lang = qs.get("lang", "grc")
        page = int(qs.get("page", "1"))
        per_page = 50
        offset = (page - 1) * per_page
        search = qs.get("q", "").strip()
        
        conn = self.get_db()
        cur = conn.cursor()
        
        lang_name = {"grc": "Greek", "lat": "Latin"}.get(lang, lang)
        
        if search:
            # Search only author and title fields, not full_text
            # Use LIKE with prefix-prioritized ordering
            like_q = f"%{search}%"
            prefix_q = f"{search}%"
            cur.execute(
                "SELECT id, author, title, word_count, lang FROM texts "
                "WHERE lang = ? AND (author LIKE ? OR title LIKE ?) "
                "ORDER BY "
                "CASE WHEN author LIKE ? OR title LIKE ? THEN 0 ELSE 1 END, "
                "author, title "
                "LIMIT ? OFFSET ?",
                (lang, like_q, like_q, prefix_q, prefix_q, per_page, offset),
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM texts "
                "WHERE lang = ? AND (author LIKE ? OR title LIKE ?)",
                (lang, like_q, like_q),
            )
            total = cur.fetchone()[0]
        else:
            cur.execute(
                "SELECT id, author, title, word_count, lang FROM texts "
                "WHERE lang = ? ORDER BY author, title LIMIT ? OFFSET ?",
                (lang, per_page, offset),
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM texts WHERE lang = ?", (lang,)
            )
            total = cur.fetchone()[0]
        
        conn.close()
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        
        body = f"""
        <h2 style="color:#4a2c1a;margin:16px 0;">{lang_name} Texts</h2>
        <p style="margin-bottom:12px;color:#666;">{total:,} works found</p>
        
        <form class="search-box" action="/browse" method="get" style="margin:12px 0;">
            <input type="hidden" name="lang" value="{lang}">
            <input type="text" name="q" placeholder="Filter by author or title..." value="{search}">
            <button type="submit">Filter</button>
        </form>
        """
        
        for row in rows:
            tid, author, title, wc, _ = row
            body += f"""
            <div class="result-item">
                <h4><a href="/read?id={tid}" style="color:#4a2c1a;text-decoration:none;">{title}</a></h4>
                <div class="meta">{author} · {wc:,} words</div>
            </div>"""
        
        if total_pages > 1:
            body += '<div class="pagination">'
            for p in range(max(1, page - 3), min(total_pages, page + 3) + 1):
                active_attr = ' style="background:#4a2c1a;color:#fff;"' if p == page else ""
                body += f'<a href="/browse?lang={lang}&page={p}"{active_attr}>{p}</a>'
            body += '</div>'
        
        self._html(body)

    def handle_lookup(self, qs):
        """JSON API: look up a word in the dictionaries and return definitions."""
        import unicodedata
        word = qs.get("word", "").strip().lower()
        if not word:
            self._json({"results": []})
            return
        
        # Strip common punctuation from the word
        word_clean = word.strip(".,;:!?·\"'()[]{}«»-—")
        if not word_clean:
            self._json({"results": []})
            return
        
        # Create a diacritic-stripped version for matching
        # (Latin headwords use macrons, breves etc.)
        def strip_diacritics(s):
            """Remove combining diacritical marks and normalize sigma."""
            nfkd = unicodedata.normalize('NFKD', s)
            result = ''.join(c for c in nfkd if unicodedata.category(c) != 'Mn')
            return result.replace('\u03c2', '\u03c3')
        
        word_plain = strip_diacritics(word_clean)
        word_nfc = unicodedata.normalize('NFC', word_clean)
        word_plain_nfc = unicodedata.normalize('NFC', word_plain)

        def candidate_headwords(s, lang_code):
            """Generate lookup candidates for common inflected forms."""
            candidates = []

            def add(value):
                if value and value not in candidates:
                    candidates.append(value)

            add(s)

            if lang_code == "lat":
                endings = (
                    "ibus", "arum", "orum", "ium", "uum",
                    "ae", "am", "as", "em", "es", "ei", "is", "os", "ud", "um", "us",
                    "nt", "re", "ri", "te", "ti", "tur",
                    "a", "e", "i", "o", "s", "t", "u",
                )
                for ending in endings:
                    if len(s) > len(ending) + 2 and s.endswith(ending):
                        stem = s[:-len(ending)]
                        add(stem)
                        add(stem + "a")
                        add(stem + "e")
                        add(stem + "i")
                        add(stem + "o")
                        add(stem + "or")
                        add(stem + "s")
                        add(stem + "tio")
                        add(stem + "us")
            elif lang_code == "grc":
                endings = (
                    "ουσι", "ουσαν", "ουσιν", "ουσης", "ουσα",
                    "οις", "αις", "ους", "ων", "ας", "ης", "ος", "ον",
                    "οι", "αι", "ει", "ου", "οιν", "ην",
                    "ῃ", "ῳ", "ε", "α", "ς", "ν",
                )
                for ending in endings:
                    if len(s) > len(ending) + 1 and s.endswith(ending):
                        stem = s[:-len(ending)]
                        add(stem)
                        add(stem + "α")
                        add(stem + "η")
                        add(stem + "ε")
                        add(stem + "ος")
                        add(stem + "ον")
                        add(stem + "ω")
                        add(stem + "ω")

            return candidates[:12]
        
        # Determine which dictionary source to prefer based on language
        lang = qs.get("lang", "")
        source_filter = ""
        if lang == "grc":
            source_filter = "LSJ"
        elif lang == "lat":
            source_filter = "Lewis & Short"
        
        conn = self.get_db()
        cur = conn.cursor()

        results = []
        candidates = candidate_headwords(word_plain_nfc, lang)
        
        def query_with_filter(base_sql, params):
            """Run query with optional source filter. Tries filtered first, falls back to unfiltered."""
            params = tuple(params)
            try:
                if source_filter:
                    # Insert AND source=? before ORDER BY or LIMIT (whichever comes first)
                    if "ORDER BY" in base_sql:
                        insert_pos = base_sql.index("ORDER BY")
                    else:
                        insert_pos = base_sql.index("LIMIT")
                    filtered_sql = base_sql[:insert_pos] + "AND source = ? " + base_sql[insert_pos:]
                    cur.execute(filtered_sql, params + (source_filter,))
                    rows = cur.fetchall()
                    if rows:
                        return rows
            except Exception:
                pass
            # Fallback: also respects source filter
            try:
                if source_filter:
                    if "ORDER BY" in base_sql:
                        insert_pos = base_sql.index("ORDER BY")
                    else:
                        insert_pos = base_sql.index("LIMIT")
                    fallback_sql = base_sql[:insert_pos] + "AND source = ? " + base_sql[insert_pos:]
                    cur.execute(fallback_sql, params + (source_filter,))
                else:
                    cur.execute(base_sql, params)
            except Exception:
                return []
            return cur.fetchall()
        
        # Strategy 1: Exact match on headword
        results = query_with_filter("""
            SELECT headword, headword_greek, definition, source
            FROM dictionary_entries
            WHERE headword = ?
            LIMIT 5
        """, (word_nfc,))
        
        # Strategy 2: Match on plain (diacritic-stripped) headword
        if not results:
            results = query_with_filter("""
                SELECT headword, headword_greek, definition, source
                FROM dictionary_entries
                WHERE headword_plain = ?
                LIMIT 5
            """, (word_plain_nfc,))

        # Strategy 3: Candidate lemma-style matches for common inflections
        if not results and len(candidates) > 1:
            placeholders = ",".join("?" for _ in candidates[1:])
            # Prefer exact headword_plain matches over prefix matches of shorter words
            results = query_with_filter(f"""
                SELECT headword, headword_greek, definition, source
                FROM dictionary_entries
                WHERE headword_plain IN ({placeholders})
                ORDER BY
                    CASE
                        WHEN headword_plain = ? THEN 0
                        ELSE 1
                    END,
                    LENGTH(headword) ASC
                LIMIT 5
            """, tuple(candidates[1:]) + (candidates[1],))

        # Strategy 4: LIKE match on plain headword
        if not results:
            results = query_with_filter("""
                SELECT headword, headword_greek, definition, source
                FROM dictionary_entries
                WHERE headword_plain LIKE ?
                ORDER BY LENGTH(headword) ASC
                LIMIT 5
            """, (f"{word_plain_nfc}%",))

        # Strategy 5: Progressive truncation for inflected forms
        # First pass: look for exact headword_plain matches
        if not results and len(word_plain_nfc) > 4:
            for trunc_len in range(len(word_plain_nfc) - 1, 2, -1):
                stem = word_plain_nfc[:trunc_len]
                results = query_with_filter("""
                    SELECT headword, headword_greek, definition, source
                    FROM dictionary_entries
                    WHERE headword_plain = ?
                    LIMIT 3
                """, (stem,))
                if results:
                    break
            # Second pass: try all truncation levels, keep the best match
            if not results:
                best = []
                for trunc_len in range(len(word_plain_nfc) - 1, 2, -1):
                    stem = word_plain_nfc[:trunc_len]
                    rows = query_with_filter("""
                        SELECT headword, headword_greek, definition, source
                        FROM dictionary_entries
                        WHERE headword_plain LIKE ?
                        ORDER BY LENGTH(headword) ASC
                        LIMIT 6
                    """, (f"{stem}%",))
                    if rows:
                        best = rows
                        break

        # Strategy 6: Prefix matches from candidate stems
        if not results:
            for candidate in candidates[1:]:
                results = query_with_filter("""
                    SELECT headword, headword_greek, definition, source
                    FROM dictionary_entries
                    WHERE headword_plain LIKE ?
                    ORDER BY LENGTH(headword) ASC
                    LIMIT 5
                """, (f"{candidate}%",))
                if results:
                    break

        # Strategy 7: LIKE match on Greek headword
        if not results:
            like_q = f"%{word_nfc}%"
            results = query_with_filter("""
                SELECT headword, headword_greek, definition, source
                FROM dictionary_entries
                WHERE headword_greek LIKE ?
                LIMIT 5
            """, (like_q,))

        # Strategy 8: Search definitions for inflected forms
        if not results and len(word_clean) > 3:
            like_q = f"%{word_nfc}%"
            results = query_with_filter("""
                SELECT headword, headword_greek, definition, source
                FROM dictionary_entries
                WHERE definition LIKE ?
                LIMIT 5
            """, (like_q,))
        
        conn.close()
        
        entries = []
        seen = set()
        full = qs.get("full", "")
        for headword, headword_greek, definition, source in results:
            key = f"{headword}::{source}"
            if key in seen:
                continue
            seen.add(key)
            # Full view shows complete definition, hover shows truncated
            if full:
                def_text = definition
            else:
                def_text = definition[:200] + "…" if len(definition) > 200 else definition
            entries.append({
                "headword": headword,
                "headword_greek": headword_greek or "",
                "definition": def_text,
                "source": source,
            })
        
        self._json({"results": entries, "word": word_clean})

    def handle_parse(self, qs):
        """JSON API: morphological analysis + dictionary definition."""
        word = qs.get("word", "").strip().lower()
        if not word:
            self._json({"results": []})
            return
        
        # Strip punctuation
        word_clean = word.strip(".,;:!?·\"'()[]{}«»-—")
        if not word_clean:
            self._json({"results": []})
            return
        
        lang = qs.get("lang", "")
        results = []
        seen_lemmas = set()
        
        # Get morphology data (lazy-loaded)
        morph = get_morphology_data()
        
        if lang == "lat" and morph:
            analyses = analyze_latin_word(word_clean, morph)
            
            for a in analyses:
                lemma = a.get('lemma', '')
                definition = a.get('definition', '')
                tags_display = format_morph_tags(a)
                
                # Try to get dictionary definition and proper headword
                dict_info = self._lookup_lemma_full(lemma, "Lewis & Short")
                dict_headword = dict_info[0] if dict_info else None
                dict_def = dict_info[1] if dict_info else None
                display_lemma = dict_headword or lemma
                
                # Skip duplicate lemmas
                if display_lemma in seen_lemmas:
                    continue
                seen_lemmas.add(display_lemma)
                
                # Generate clean short definition
                ww_meaning = a.get('definition', '')
                short_def = clean_latin_definition(dict_def, ww_meaning)
                full_def = dict_def or ww_meaning
                
                # Generate formatted summary line (principal parts, etc.)
                lemma_pos = a.get('pos', '')
                lemma_type = a.get('type_code', '')
                lemma_stems = a.get('stems', [])
                lemma_meaning = a.get('definition', '')
                summary_line = format_lemma_summary(
                    display_lemma, lemma_pos, lemma_type, lemma_stems, lemma_meaning
                )
                
                # Generate nicely formatted full entry HTML
                formatted_entry = format_full_entry(full_def) if dict_def else ''
                
                results.append({
                    "word": word_clean,
                    "lemma": display_lemma,
                    "summary": summary_line,
                    "definition": full_def,
                    "formatted_entry": formatted_entry,
                    "short_definition": short_def,
                    "source": "Lewis & Short" if dict_headword else "Whitaker's Words",
                    "morphology": {
                        "pos": POS_MAP.get(a.get('pos', ''), a.get('pos', '')),
                        "person": a.get('person', ''),
                        "number": NUMBER_MAP.get(a.get('number', ''), a.get('number', '')),
                        "tense": TENSE_MAP.get(a.get('tense', ''), a.get('tense', '')),
                        "mood": MOOD_MAP.get(a.get('mood', ''), a.get('mood', '')),
                        "voice": VOICE_MAP.get(a.get('voice', ''), a.get('voice', '')),
                        "case": CASE_MAP.get(a.get('case', ''), a.get('case', '')),
                        "tags_display": tags_display,
                    },
                })
        
        elif lang == "grc":
            greek_nlp = get_greek_nlp()
            if greek_nlp:
                try:
                    doc = greek_nlp.analyze(text=word_clean)
                    if doc.sentences and doc.sentences[0].words:
                        w = doc.sentences[0].words[0]
                        lemma = w.lemma or word_clean
                        upos = w.upos
                        features = w.features

                        tags_display = format_greek_morph_tags(upos, features)

                        # Look up lemma in LSJ
                        dict_info = self._lookup_greek_lemma(lemma)
                        if dict_info:
                            headword_beta, headword_greek, dict_def = dict_info
                            display_lemma = headword_greek or headword_beta or lemma
                        else:
                            display_lemma = lemma
                            dict_def = None

                        # Skip duplicates
                        if display_lemma not in seen_lemmas:
                            seen_lemmas.add(display_lemma)

                        full_def = dict_def or ''

                        # Clean short definition (convert Beta Code to Greek, strip citations)
                        short_def = ''
                        formatted_entry = ''
                        if dict_def:
                            short_def = clean_greek_definition(dict_def, display_lemma)
                            formatted_entry = format_greek_entry(dict_def, truncate=False)

                        # Build morphology dict
                        morph_dict = {'pos': upos.name.capitalize() if upos.name else upos.tag}
                        if features:
                            for _key, tag_list in features:
                                for tag in tag_list:
                                    d = tag.model_dump()
                                    k = d['key'].lower()
                                    v = d['value_label']
                                    if k == 'person':
                                        v = PERSON_LABELS.get(v, v)
                                    morph_dict[k] = v
                        morph_dict['tags_display'] = tags_display

                        results.append({
                            "word": word_clean,
                            "lemma": display_lemma,
                            "summary": display_lemma,
                            "definition": full_def,
                            "formatted_entry": formatted_entry,
                            "short_definition": short_def,
                            "source": "LSJ" if dict_info else "CLTK",
                            "morphology": morph_dict,
                        })

                        # If CLTK found no LSJ match, also try a dictionary-only
                        # lookup on the raw word to supplement
                        if not dict_info:
                            lookup = self._lookup_greek_lemma(word_clean)
                            if lookup:
                                hw_beta, hw_greek, fallback_def = lookup
                                results.append({
                                    "word": word_clean,
                                    "lemma": hw_greek or hw_beta or word_clean,
                                    "summary": hw_greek or hw_beta or word_clean,
                                    "definition": fallback_def,
                                    "formatted_entry": '',
                                    "short_definition": fallback_def[:200] if fallback_def else '',
                                    "source": "LSJ",
                                    "morphology": {},
                                })
                except Exception as e:
                    log("Greek NLP error for '{}': {}".format(word_clean, e))
        
        # Fallback: if no morphological analysis, use dictionary lookup
        if not results:
            # Use the existing lookup method
            self.handle_lookup(qs)
            return
        
        self._json({"results": results, "word": word_clean})

    def _lookup_lemma(self, lemma, source):
        """Look up a dictionary definition for a lemma using stem matching."""
        result = self._lookup_lemma_full(lemma, source)
        return result[1] if result else None

    def _lookup_lemma_full(self, lemma, source):
        """Look up a dictionary headword and definition for a lemma.
        Tries exact match, then common headword forms, then prefix match.
        Returns (headword, definition) or None."""
        import unicodedata
        try:
            conn = self.get_db()
            cur = conn.cursor()
            
            # Build candidate headword forms
            candidates = [lemma]
            # For Latin stems, try common dictionary headword endings
            # 1st/2nd conj: stem+o, 3rd conj: stem+o/stem+or, 4th: stem+io
            for suffix in ['or', 'o', 'er', 'ior', 'iora', 'ius', 'is', 'e']:
                candidates.append(lemma + suffix)
            # Also try common noun/adjective endings
            for suffix in ['a', 'us', 'um', 'er']:
                candidates.append(lemma + suffix)
            
            # Deduplicate
            seen = set()
            unique_candidates = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique_candidates.append(c)
            
            # Try each candidate as an exact match
            placeholders = ','.join('?' for _ in unique_candidates)
            cur.execute(
                "SELECT headword, definition FROM dictionary_entries "
                "WHERE headword_plain IN ({}) AND source = ? "
                "ORDER BY LENGTH(headword) ASC "
                "LIMIT 3".format(placeholders),
                tuple(unique_candidates) + (source,),
            )
            rows = cur.fetchall()
            if rows:
                conn.close()
                # Prefer headwords that are common Latin verbs (end in o/or)
                for headword, definition in rows:
                    hw = headword.lower()
                    if hw.endswith('or') or hw.endswith('o'):
                        return (headword, definition)
                return (rows[0][0], rows[0][1])
            
            # Fallback: prefix match
            cur.execute(
                "SELECT headword, definition FROM dictionary_entries "
                "WHERE (headword_plain LIKE ? OR headword LIKE ?) AND source = ? "
                "ORDER BY LENGTH(headword) ASC "
                "LIMIT 3",
                (lemma + '%', lemma + '%', source),
            )
            rows = cur.fetchall()
            conn.close()
            if rows:
                # Prefer headwords ending in 'or' (deponent) or 'o' (regular verb)
                for headword, definition in rows:
                    hw = headword.lower()
                    if hw.endswith('or') or hw.endswith('o'):
                        return (headword, definition)
                return (rows[0][0], rows[0][1])
            
            conn.close()
            return None
        except Exception:
            return None

    def _lookup_greek_lemma(self, lemma):
        """Look up a Greek lemma in LSJ by matching headword_greek.

        Tries exact match on headword_greek, then diacritic-stripped plain,
        then progressive truncation for compound/derived forms.
        Returns (headword_beta, headword_greek, definition) or None.
        """
        import unicodedata
        try:
            # Build plain (diacritic-stripped) version of the lemma
            nfkd = unicodedata.normalize('NFKD', lemma)
            lemma_plain = ''.join(c for c in nfkd.lower() if unicodedata.category(c) != 'Mn')

            conn = self.get_db()
            cur = conn.cursor()

            # Strategy 1: Exact match on headword_greek
            cur.execute(
                "SELECT headword, headword_greek, definition FROM dictionary_entries "
                "WHERE headword_greek = ? AND source = 'LSJ' LIMIT 3",
                (lemma,),
            )
            rows = cur.fetchall()
            if rows:
                conn.close()
                return (rows[0][0], rows[0][1], rows[0][2])

            # Strategy 2: Match on headword_plain (diacritic-stripped)
            cur.execute(
                "SELECT headword, headword_greek, definition FROM dictionary_entries "
                "WHERE headword_plain = ? AND source = 'LSJ' LIMIT 3",
                (lemma_plain,),
            )
            rows = cur.fetchall()
            if rows:
                conn.close()
                return (rows[0][0], rows[0][1], rows[0][2])

            # Strategy 3: Progressive truncation for compound/derived forms
            # (e.g. προελαύνω → ἐλαύνω, συλλαμβάνω → λαμβάνω)
            if len(lemma_plain) > 4:
                for trunc_len in range(len(lemma_plain) - 2, 3, -1):
                    stem = lemma_plain[:trunc_len]
                    cur.execute(
                        "SELECT headword, headword_greek, definition FROM dictionary_entries "
                        "WHERE headword_plain = ? AND source = 'LSJ' LIMIT 2",
                        (stem,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        conn.close()
                        return (rows[0][0], rows[0][1], rows[0][2])

            # Strategy 4: Prefix match
            cur.execute(
                "SELECT headword, headword_greek, definition FROM dictionary_entries "
                "WHERE (headword_greek LIKE ? OR headword_plain LIKE ?) AND source = 'LSJ' "
                "ORDER BY LENGTH(headword) ASC LIMIT 3",
                (lemma + '%', lemma_plain + '%'),
            )
            rows = cur.fetchall()
            conn.close()
            if rows:
                return (rows[0][0], rows[0][1], rows[0][2])

            return None
        except Exception:
            return None

    def handle_read(self, qs):
        tid = qs.get("id", "")
        if not tid:
            self.send_error(400, "Missing id parameter")
            return
        
        conn = self.get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT author, title, lang, filepath, full_text FROM texts WHERE id = ?",
            (tid,),
        )
        row = cur.fetchone()
        conn.close()
        
        if not row:
            self.send_error(404, "Text not found")
            return
        
        author, title, lang, filepath, full_text = row
        
        # Render text as plain paragraphs (no span wrapping — handled by JS client-side)
        paragraphs = full_text.split("\n\n")
        text_html = ""
        grc_class = ' class="text-grc"' if lang == "grc" else ""
        for p in paragraphs:
            p = p.strip()
            if p:
                text_html += f"<p{grc_class}>{p}</p>\n"
        
        body = f"""
        <div class="text-viewer" data-lang="{lang}">
            <div class="text-title">{title}</div>
            <div class="text-author">{author}</div>
            <div class="meta" style="font-size:0.8em;color:#999;margin-bottom:16px;">
                {filepath} · {lang.upper()}
            </div>
            <div class="_textContent">{text_html}</div>
        </div>
        <div id="dictPopup" style="display:none;position:fixed;z-index:1000;
            background:#fff;border:1px solid #c9a87c;border-radius:6px;
            padding:10px 14px;max-width:420px;max-height:300px;overflow-y:auto;
            box-shadow:0 4px 16px rgba(0,0,0,0.15);font-size:0.85em;line-height:1.5;
            pointer-events:none;"></div>
        <div id="fullPopup" style="display:none;position:fixed;z-index:2000;
            background:#fffdfa;border:1px solid #c9a87c;border-radius:12px;
            padding:24px 28px;width:min(920px, calc(100vw - 32px));max-height:84vh;overflow-y:auto;
            box-shadow:0 16px 48px rgba(0,0,0,0.22);font-size:0.98em;line-height:1.72;
            pointer-events:auto;top:50%;left:50%;transform:translate(-50%,-50%);"></div>
        <div id="fullOverlay" style="display:none;position:fixed;z-index:1999;
            top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);"></div>
        <div id="dictHighlight" style="display:none;position:fixed;z-index:999;
            background:rgba(201,168,124,0.25);border-radius:3px;
            pointer-events:none;transition:opacity 0.15s;"></div>
        <script>
        (function() {{
            // ── Inject toolbar into nav (must run first to create elements) ──
            (function() {{
                var nav = document.querySelector('nav .container');
                if (!nav) return;
                var tb = document.createElement('div');
                tb.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 0 2px;margin-top:4px;border-top:1px solid #eee;';
                var lang = (document.querySelector('.text-viewer')?.getAttribute('data-lang') || 'lat');
                tb.innerHTML =
                    '<span style="display:inline-flex;align-items:center;gap:4px;font-size:0.82em;color:#4a2c1a;">' +
                    '<span style="font-size:1em;">&#x1F50D;</span>' +
                    '<input type="text" id="searchInput" placeholder="Find in text..." style="width:130px;padding:3px 7px;font-size:0.82em;border:1px solid #d4c5b0;border-radius:4px;background:#fff;outline:none;color:#333;">' +
                    '<span id="searchCount" style="font-size:0.75em;color:#999;"></span>' +
                    '<button id="searchPrev" type="button" style="cursor:pointer;background:none;border:none;padding:1px 5px;font-size:0.85em;color:#7a5a3a;" title="Previous">&uarr;</button>' +
                    '<button id="searchNext" type="button" style="cursor:pointer;background:none;border:none;padding:1px 5px;font-size:0.85em;color:#7a5a3a;" title="Next">&darr;</button>' +
                    '<button id="searchClear" type="button" style="cursor:pointer;background:none;border:none;padding:1px 5px;font-size:0.85em;color:#aaa;" title="Clear">&times;</button></span>' +
                    '<span style="color:#ddd;">|</span>' +
                    '<label style="cursor:pointer;user-select:none;display:inline-flex;align-items:center;gap:4px;font-size:0.82em;white-space:nowrap;color:#4a2c1a;" title="Enable hover dictionary lookup">' +
                    '<input type="checkbox" id="dictToggle" style="cursor:pointer;" data-lang="' + lang + '">' +
                    ' Toggle hovering dictionary</label>';
                nav.appendChild(tb);
            }})();
            
            var toggle = document.getElementById('dictToggle');
            var popup = document.getElementById('dictPopup');
            var fullPopup = document.getElementById('fullPopup');
            var fullOverlay = document.getElementById('fullOverlay');
            var highlight = document.getElementById('dictHighlight');
            var viewer = document.querySelector('.text-viewer');
            var hoverTimer = null;
            var currentWord = null;
            var mouseInViewer = false;
            var lastClickTime = 0;
            var lookupCache = {{}};
            
            function getWordInfo(x, y) {{
                var range = document.caretRangeFromPoint
                    ? document.caretRangeFromPoint(x, y)
                    : (function() {{
                        var pos = document.caretPositionFromPoint(x, y);
                        if (!pos) return null;
                        var r = document.createRange();
                        r.setStart(pos.offsetNode, pos.offset);
                        r.collapse(true);
                        return r;
                    }})();
                if (!range) return null;
                var node = range.startContainer;
                if (node.nodeType !== 3) return null;
                var text = node.textContent;
                var offset = range.startOffset;
                var start = offset;
                while (start > 0 && /\\S/.test(text[start - 1])) start--;
                var end = offset;
                while (end < text.length && /\\S/.test(text[end])) end++;
                if (start >= end) return null;
                var word = text.substring(start, end);
                var clean = word.replace(/^[.,;:!?·"'()]+/, '').replace(/[.,;:!?·"'()]+$/, '');
                if (!clean) return null;
                var wordRange = document.createRange();
                wordRange.setStart(node, start + word.indexOf(clean));
                wordRange.setEnd(node, start + word.indexOf(clean) + clean.length);
                return {{ word: clean, range: wordRange }};
            }}

            function getSelectedWordInfo() {{
                var sel = window.getSelection ? window.getSelection() : null;
                if (!sel || sel.rangeCount === 0) return null;
                var text = sel.toString().trim();
                if (!text) return null;
                var clean = text.replace(/^[.,;:!?Â·"'()\\[\\]{{}}]+/, '').replace(/[.,;:!?Â·"'()\\[\\]{{}}]+$/, '');
                if (!clean) return null;
                try {{
                    var range = sel.getRangeAt(0).cloneRange();
                    if (range.collapsed) return null;
                    return {{ word: clean, range: range }};
                }} catch (err) {{
                    return {{ word: clean, range: null }};
                }}
            }}
            
            function showHighlight(r) {{
                var rect = r.getBoundingClientRect();
                if (!rect || rect.width === 0) return;
                highlight.style.display = 'block';
                highlight.style.left = (rect.left - 3) + 'px';
                highlight.style.top = (rect.top - 4) + 'px';
                highlight.style.width = (rect.width + 6) + 'px';
                highlight.style.height = (rect.height + 8) + 'px';
                highlight.style.borderRadius = '4px';
            }}
            
            function hideHighlight() {{
                highlight.style.display = 'none';
            }}
            
            function clearWord() {{
                if (hoverTimer) {{ clearTimeout(hoverTimer); hoverTimer = null; }}
                hideHighlight();
                popup.style.display = 'none';
                currentWord = null;
            }}
            
            function doLookup(word, callback, lang, full) {{
                var key = word + '|' + lang + '|' + (full ? 'full' : 'short');
                if (lookupCache[key]) {{
                    callback(lookupCache[key]);
                    return;
                }}
                var xhr = new XMLHttpRequest();
                var url = '/parse?word=' + encodeURIComponent(word) + '&lang=' + encodeURIComponent(lang);
                if (full) url += '&full=1';
                xhr.open('GET', url, true);
                xhr.onload = function() {{
                    if (xhr.status === 200) {{
                        var data = JSON.parse(xhr.responseText);
                        lookupCache[key] = data;
                        callback(data);
                    }} else {{
                        callback(null);
                    }}
                }};
                xhr.onerror = function() {{ callback(null); }};
                xhr.send();
            }}
            
            function buildParseEntryHtml(result, full) {{
                var html = '<div style="padding:6px 0;border-bottom:1px solid #f0ebe4;">';
                // Lemma with summary (principal parts)
                var lemmaDisplay = result.summary || result.lemma;
                html += '<div style="font-weight:700;color:#4a2c1a;font-size:1em;">' + lemmaDisplay;
                if (result.word && result.lemma !== result.word) {{
                    html += ' <span style="font-weight:400;font-size:0.8em;color:#999;">(' + result.word + ')</span>';
                }}
                html += ' <span style="font-weight:400;font-size:0.75em;color:#aaa;">' + result.source + '</span>';
                html += '</div>';
                // Morphology tags
                if (result.morphology && result.morphology.tags_display) {{
                    html += '<div style="margin-top:1px;font-style:italic;font-size:0.85em;color:#7a5a3a;">' +
                        result.morphology.tags_display + '</div>';
                }}
                // Short clean definition
                var def = result.short_definition || result.definition || '';
                if (!full && def.length > 200) def = def.substring(0, 200) + '...';
                if (def) {{
                    html += '<div style="margin-top:4px;color:#2f2a24;white-space:pre-wrap;font-size:0.9em;">' +
                        '— ' + def + '</div>';
                }}
                html += '</div>';
                return html;
            }}
            
            function buildFallbackEntryHtml(entry, full) {{
                var hw = entry.headword_greek
                    ? entry.headword_greek + ' <span style="font-size:0.75em;color:#aaa;">(' + entry.headword + ')</span>'
                    : entry.headword;
                var def = full ? entry.definition : (entry.definition.length > 200 ? entry.definition.substring(0, 200) + '...' : entry.definition);
                return '<div style="padding:6px 0;border-bottom:1px solid #f0ebe4;">' +
                    '<div style="font-weight:700;color:#4a2c1a;font-size:1em;">' +
                    hw + ' <span style="font-weight:400;font-size:0.75em;color:#aaa;">' +
                    entry.source + '</span></div>' +
                    '<div style="margin-top:2px;color:#333;white-space:pre-wrap;font-size:0.9em;">' + def + '</div></div>';
            }}
            
            viewer.addEventListener('mouseenter', function() {{
                mouseInViewer = true;
            }});
            
            viewer.addEventListener('mouseleave', function() {{
                mouseInViewer = false;
                clearWord();
            }});
            
            viewer.addEventListener('mousemove', function(e) {{
                if (!toggle.checked) {{
                    clearWord();
                    return;
                }}
                var info = getWordInfo(e.clientX, e.clientY);
                if (!info) {{
                    hideHighlight();
                    return;
                }}
                var word = info.word;
                showHighlight(info.range);
                if (word === currentWord) return;
                currentWord = word;
                var hoverX = e.clientX;
                var hoverY = e.clientY;
                if (hoverTimer) {{ clearTimeout(hoverTimer); hoverTimer = null; }}
                popup.style.display = 'none';
                hoverTimer = setTimeout(function() {{
                    if (!mouseInViewer) return;
                    popup.innerHTML = '<div style="text-align:center;color:#999;padding:8px;">Looking up <em>' + word + '</em>…</div>';
                    popup.style.display = 'block';
                    popup.style.left = Math.max(10, Math.min(hoverX - 10, window.innerWidth - 430)) + 'px';
                    popup.style.top = Math.max(10, hoverY - 30) + 'px';
                    doLookup(word, function(data) {{
                        if (currentWord !== word || !mouseInViewer) return;
                        if (data && data.results && data.results.length > 0) {{
                            var html = '';
                            for (var i = 0; i < data.results.length; i++) {{
                                if (data.results[i].lemma) {{
                                    html += buildParseEntryHtml(data.results[i], false);
                                }} else {{
                                    html += buildFallbackEntryHtml(data.results[i], false);
                                }}
                            }}
                            popup.innerHTML = html;
                        }} else {{
                            popup.innerHTML = '<div style="color:#999;padding:6px;text-align:center;">No entry for <em>' + word + '</em></div>';
                        }}
                    }}, toggle.dataset.lang, false);
                }}, 500);
            }});
            
            viewer.addEventListener('dblclick', function(e) {{
                var info = getSelectedWordInfo() || getWordInfo(e.clientX, e.clientY);
                if (!info) return;
                var word = info.word;
                popup.style.display = 'none';
                if (info.range) showHighlight(info.range);
                doLookup(word, function(data) {{
                    if (!data || !data.results || data.results.length === 0) {{
                        fullPopup.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px;padding-bottom:12px;border-bottom:2px solid #c9a87c;">' +
                            '<div><div style="font-size:0.75em;letter-spacing:0.08em;text-transform:uppercase;color:#9a7a52;margin-bottom:6px;">Word Lookup</div>' +
                            '<div style="font-size:1.45em;font-weight:700;color:#4a2c1a;line-height:1.2;">' + word + '</div></div>' +
                            '<button type="button" style="cursor:pointer;font-size:1.4em;line-height:1;color:#8a8a8a;background:none;border:none;padding:0;" onclick="document.getElementById(\\'fullPopup\\').style.display=\\'none\\';document.getElementById(\\'fullOverlay\\').style.display=\\'none\\';" aria-label="Close">&times;</button></div>' +
                            '<div style="padding:16px 18px;background:#fcfaf7;border:1px solid #eadfce;border-radius:10px;color:#2f2a24;line-height:1.7;">' +
                            'No entry found for <em>' + word + '</em>.</div>';
                        fullPopup.style.display = 'block';
                        fullOverlay.style.display = 'block';
                        return;
                    }}
                    var hasMorphology = data.results[0] && data.results[0].morphology;
                    var r0 = data.results[0];
                    var displayLemma = r0.summary || r0.lemma || r0.headword || word;
                    var html = '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px;padding-bottom:12px;border-bottom:2px solid #c9a87c;">' +
                        '<div><div style="font-size:0.75em;letter-spacing:0.08em;text-transform:uppercase;color:#9a7a52;margin-bottom:6px;">' +
                        (hasMorphology ? 'Morphological Analysis' : 'Dictionary Entry') +
                        '</div>' +
                        '<div style="font-size:1.45em;font-weight:700;color:#4a2c1a;line-height:1.2;">' + word + '</div></div>' +
                        '<button type="button" style="cursor:pointer;font-size:1.4em;line-height:1;color:#8a8a8a;background:none;border:none;padding:0;" onclick="document.getElementById(\\'fullPopup\\').style.display=\\'none\\';document.getElementById(\\'fullOverlay\\').style.display=\\'none\\';" aria-label="Close">&times;</button></div>';
                    for (var i = 0; i < data.results.length; i++) {{
                        var r = data.results[i];
                        html += '<article style="margin-bottom:18px;padding:16px 18px;background:#fcfaf7;border:1px solid #eadfce;border-radius:10px;">';
                        var articleLemma = r.summary || r.lemma || r.headword || '(unknown)';
                        html += '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;border-bottom:1px solid #efe6d8;padding-bottom:8px;">' +
                            '<div style="font-weight:700;color:#4a2c1a;font-size:1.15em;line-height:1.35;">' + articleLemma + '</div>' +
                            '<div style="font-weight:600;font-size:0.78em;letter-spacing:0.04em;text-transform:uppercase;color:#9a7a52;">' + r.source + '</div></div>';
                        if (r.morphology && r.morphology.tags_display) {{
                            html += '<div style="margin-top:8px;font-style:italic;color:#7a5a3a;">' +
                                r.morphology.tags_display + '</div>';
                        }}
                        // Clean short definition
                        var shortDef = r.short_definition || '';
                        if (shortDef) {{
                            html += '<div style="margin-top:10px;color:#2f2a24;white-space:pre-wrap;font-size:1rem;line-height:1.75;">' +
                                '<div style="font-size:0.8em;font-weight:600;color:#9a7a52;margin-bottom:4px;">Definition</div>' +
                                '— ' + shortDef + '</div>';
                        }}
                        // Full entry toggle (collapsible, formatted)
                        var formattedEntry = r.formatted_entry || '';
                        var fullDef = r.definition || '';
                        if (formattedEntry) {{
                            var toggleId = 'fullEntry_' + i;
                            html += '<div style="margin-top:8px;border-top:1px solid #efe6d8;padding-top:10px;">' +
                                '<button type="button" style="cursor:pointer;background:none;border:1px solid #d4c5b0;border-radius:4px;padding:4px 12px;font-size:0.82em;color:#7a5a3a;" ' +
                                'onclick="var e=document.getElementById(\\'' + toggleId + '\\');e.style.display=e.style.display===\\'none\\'?\\'block\\':\\'none\\';">' +
                                'Toggle full Lewis & Short entry</button>' +
                                '<div id="' + toggleId + '" style="display:none;margin-top:8px;font-size:0.92rem;line-height:1.7;background:#f9f6f1;padding:14px 16px;border-radius:6px;border:1px solid #e8ddd0;">' +
                                formattedEntry + '</div></div>';
                        }}
                        html += '</article>';
                    }}
                    html += '<div style="margin-top:8px;padding-top:10px;border-top:1px solid #eee;font-size:0.82em;color:#8b8b8b;text-align:center;">' +
                        'Double-click another word to replace, or press Esc / click outside to close.</div>';
                    fullPopup.innerHTML = html;
                    fullPopup.style.display = 'block';
                    fullOverlay.style.display = 'block';
                }}, toggle.dataset.lang, true);
            }});
            
            fullOverlay.addEventListener('click', function() {{
                fullPopup.style.display = 'none';
                fullOverlay.style.display = 'none';
            }});

            window.addEventListener('keydown', function(e) {{
                if (e.key === 'Escape') {{
                    fullPopup.style.display = 'none';
                    fullOverlay.style.display = 'none';
                }}
            }});
            
            // ── Scroll progress indicator ──
            
            // ── In-text search ──
            var searchInput = document.getElementById('searchInput');
            var searchPrev = document.getElementById('searchPrev');
            var searchNext = document.getElementById('searchNext');
            var searchClear = document.getElementById('searchClear');
            var searchCount = document.getElementById('searchCount');
            var searchMatches = [];
            var searchIndex = -1;
            
            function doSearch() {{
                var q = searchInput.value.trim().toLowerCase();
                
                // Minimum 2 chars, skip if too short
                if (q.length < 2) {{
                    // Restore original HTML if needed
                    if (window._origTextHtml) {{
                        var td = document.querySelector('._textContent');
                        if (td) td.innerHTML = window._origTextHtml;
                    }}
                    searchCount.textContent = '';
                    return;
                }}
                
                var textDiv = document.querySelector('._textContent');
                if (!textDiv) return;
                
                // Store original HTML on first search
                if (!window._origTextHtml) window._origTextHtml = textDiv.innerHTML;
                
                // Restore original HTML (remove old highlights)
                textDiv.innerHTML = window._origTextHtml;
                
                // Use innerHTML replacement per paragraph (safe — <p> contains only text)
                var re = new RegExp('(' + q.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
                var paragraphs = textDiv.querySelectorAll('p');
                for (var pi = 0; pi < paragraphs.length; pi++) {{
                    paragraphs[pi].innerHTML = paragraphs[pi].innerHTML.replace(re, '<span class="search-hl">$1</span>');
                }}
                
                var total = document.querySelectorAll('.search-hl, .search-hl-active').length;
                searchCount.textContent = total + ' match' + (total !== 1 ? 'es' : '');
                searchIndex = -1;
                if (total > 0) goToMatch(0);
            }}
            
            function goToMatch(idx) {{
                var spans = document.querySelectorAll('.search-hl, .search-hl-active');
                if (spans.length === 0 || idx < 0 || idx >= spans.length) return;
                // Remove active class from all
                document.querySelectorAll('.search-hl-active').forEach(function(el) {{
                    el.className = 'search-hl';
                }});
                searchIndex = idx;
                if (spans[idx]) {{
                    spans[idx].className = 'search-hl-active';
                    spans[idx].scrollIntoView({{ block: 'center', behavior: 'smooth' }});
                }}
                searchCount.textContent = (idx + 1) + '/' + spans.length;
            }}
            
            searchInput.addEventListener('input', doSearch);
            searchInput.addEventListener('keydown', function(e) {{
                if (e.key === 'Enter') {{ e.preventDefault(); if (e.shiftKey) searchPrev.click(); else searchNext.click(); }}
            }});
            searchPrev.addEventListener('click', function() {{
                if (document.querySelectorAll('.search-hl, .search-hl-active').length === 0) doSearch();
                var n = document.querySelectorAll('.search-hl, .search-hl-active').length;
                goToMatch(searchIndex <= 0 ? n - 1 : searchIndex - 1);
            }});
            searchNext.addEventListener('click', function() {{
                if (document.querySelectorAll('.search-hl, .search-hl-active').length === 0) doSearch();
                var n = document.querySelectorAll('.search-hl, .search-hl-active').length;
                goToMatch(searchIndex >= n - 1 ? 0 : searchIndex + 1);
            }});
            searchClear.addEventListener('click', function() {{
                searchInput.value = '';
                doSearch();
                searchInput.focus();
            }});
            

            
            // ── Scroll-to-top button ──
            var topBtn = document.createElement('div');
            topBtn.textContent = '\u2191';
            topBtn.title = 'Scroll to top';
            topBtn.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:500;'
                + 'font-size:1.4em;font-weight:700;width:40px;height:40px;line-height:40px;'
                + 'text-align:center;border-radius:50%;cursor:pointer;user-select:none;'
                + 'background:#4a2c1a;color:#f5f0eb;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.2);';
            topBtn.addEventListener('click', function() {{
                window.scrollTo({{top:0, behavior:'smooth'}});
            }});
            document.body.appendChild(topBtn);
            
            // ── Scroll progress indicator ──
            var progressEl = document.getElementById('scrollProgress');
            if (!progressEl) {{
                progressEl = document.createElement('div');
                progressEl.id = 'scrollProgress';
                progressEl.style.cssText = 'position:fixed;right:28px;bottom:50%;transform:translateY(50%);'
                    + 'z-index:500;font-size:1.6em;font-family:monospace;font-weight:600;color:#4a2c1a;'
                    + 'background:rgba(255,253,250,0.95);border:2px solid #c9a87c;border-radius:8px;'
                    + 'padding:8px 14px;opacity:0;transition:opacity 0.3s;'
                    + 'pointer-events:none;user-select:none;box-shadow:0 2px 10px rgba(0,0,0,0.15);';
                document.body.appendChild(progressEl);
            }}
            var progressFadeTimer = null;
            var updateProgress = function() {{
                var st = window.scrollY || document.documentElement.scrollTop;
                var sh = document.documentElement.scrollHeight - window.innerHeight;
                if (sh > 0) {{
                    progressEl.textContent = (st / sh * 100).toFixed(1) + '%';
                }}
                progressEl.style.opacity = '1';
                if (progressFadeTimer) clearTimeout(progressFadeTimer);
                progressFadeTimer = setTimeout(function() {{ progressEl.style.opacity = '0'; }}, 1200);
            }};
            window.addEventListener('scroll', function() {{
                clearWord();
                updateProgress();
            }});
            updateProgress();
        }})();
        </script>
        """
        self._html(body)

    def handle_search(self, qs):
        query = qs.get("q", "").strip()
        scope = qs.get("scope", "all").strip()
        lang_filter = qs.get("lang", "").strip()
        page = int(qs.get("page", "1"))
        per_page = 25
        offset = (page - 1) * per_page
        
        # Determine placeholders and help text
        scope_labels = {"all": "All fields", "author": "Author", "title": "Title"}
        scope_placeholder = {
            "all": "Search all text, author names, and titles...",
            "author": "Search by author name (e.g., 'Homer', 'Cicero', 'Plato')...",
            "title": "Search by work title (e.g., 'Iliad', 'Aeneid', 'Republic')...",
        }
        lang_labels = {"": "All languages", "grc": "Greek only", "lat": "Latin only"}
        
        empty_form = f"""
        <h2 style="color:#4a2c1a;margin:16px 0;">Search</h2>
        <form class="search-box" action="/search" method="get">
            <input type="text" name="q" placeholder="{scope_placeholder[scope]}" value="">
            <select name="scope">
                <option value="all" {'selected' if scope == 'all' else ''}>All fields</option>
                <option value="author" {'selected' if scope == 'author' else ''}>Author</option>
                <option value="title" {'selected' if scope == 'title' else ''}>Title</option>
            </select>
            <select name="lang">
                <option value="" {'selected' if lang_filter == '' else ''}>All languages</option>
                <option value="grc" {'selected' if lang_filter == 'grc' else ''}>Greek only</option>
                <option value="lat" {'selected' if lang_filter == 'lat' else ''}>Latin only</option>
            </select>
            <button type="submit">Search</button>
        </form>
        <p style="color:#666;">Use full-text search across the entire corpus, or narrow by author/work title and language.</p>
        """
        
        if not query:
            self._html(empty_form)
            return
        
        conn = self.get_db()
        cur = conn.cursor()
        
        # Search using LIKE (substring matching) for author/title, FTS5 for full text
        like_q = f"%{query}%"

        # Build WHERE clause based on scope and language
        where_parts = []
        params = []

        if scope == "author":
            where_parts.append("author LIKE ?")
            params.append(like_q)
        elif scope == "title":
            where_parts.append("title LIKE ?")
            params.append(like_q)
        else:
            where_parts.append("(author LIKE ? OR title LIKE ?)")
            params.extend([like_q, like_q])

        if lang_filter:
            where_parts.append("lang = ?")
            params.append(lang_filter)

        where_clause = " AND ".join(where_parts)

        # Try LIKE search first (finds partial matches like "tusculan" → "Tusculanae")
        try:
            cur.execute(
                f"SELECT id, author, title, lang, word_count, "
                f"CASE WHEN full_text LIKE ? THEN substr(full_text, max(1, instr(full_text, ?)-100), 200) ELSE '' END as snip "
                f"FROM texts WHERE {where_clause} "
                f"ORDER BY word_count DESC LIMIT ? OFFSET ?",
                params + [like_q, query, per_page, offset],
            )
            results = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) FROM texts WHERE {where_clause}",
                params,
            )
            total = cur.fetchone()[0]

            # If LIKE returns nothing, try FTS5 full-text search as fallback
            if not results and scope == "all":
                raise Exception("Try FTS5 fallback")
        except Exception:
            # FTS5 full-text fallback (for searching within document bodies)
            try:
                fts_query = query.replace('"', '""') + '*'
                if lang_filter:
                    cur.execute("""
                        SELECT t.id, t.author, t.title, t.lang, t.word_count,
                               snippet(texts_fts, 2, '<em>', '</em>', '...', 40) as snip
                        FROM texts_fts f JOIN texts t ON t.id = f.rowid
                        WHERE texts_fts MATCH ? AND t.lang = ?
                        ORDER BY rank LIMIT ? OFFSET ?
                    """, (fts_query, lang_filter, per_page, offset))
                    results = cur.fetchall()
                    cur.execute("""
                        SELECT COUNT(*) FROM texts_fts f JOIN texts t ON t.id = f.rowid
                        WHERE texts_fts MATCH ? AND t.lang = ?
                    """, (fts_query, lang_filter))
                else:
                    cur.execute("""
                        SELECT t.id, t.author, t.title, t.lang, t.word_count,
                               snippet(texts_fts, 2, '<em>', '</em>', '...', 40) as snip
                        FROM texts_fts f JOIN texts t ON t.id = f.rowid
                        WHERE texts_fts MATCH ?
                        ORDER BY rank LIMIT ? OFFSET ?
                    """, (fts_query, per_page, offset))
                    results = cur.fetchall()
                    cur.execute("""
                        SELECT COUNT(*) FROM texts_fts WHERE texts_fts MATCH ?
                    """, (fts_query,))
                total = cur.fetchone()[0]
            except Exception:
                # Ultimate fallback: LIKE on full_text too
                like_q = f"%{query}%"
                where_parts = ["(author LIKE ? OR title LIKE ? OR full_text LIKE ?)"]
                params = [like_q, like_q, like_q]
                if lang_filter:
                    where_parts.append("lang = ?")
                    params.append(lang_filter)
                where_clause = " AND ".join(where_parts)
                cur.execute(
                    f"SELECT id, author, title, lang, word_count, "
                    f"CASE WHEN full_text LIKE ? THEN substr(full_text, max(1, instr(full_text, ?)-100), 200) ELSE '' END as snip "
                    f"FROM texts WHERE {where_clause} "
                    f"ORDER BY word_count DESC LIMIT ? OFFSET ?",
                    params + [like_q, query, per_page, offset],
                )
                results = cur.fetchall()
                cur.execute(
                    f"SELECT COUNT(*) FROM texts WHERE {where_clause}",
                    params,
                )
                total = cur.fetchone()[0]
        
        conn.close()
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        lang_icons = {"grc": "🏛️", "lat": "🏛️"}
        
        # Build filter labels for display
        filter_parts = []
        if scope != "all":
            filter_parts.append(f"in {scope_labels[scope]}")
        if lang_filter:
            filter_parts.append(lang_labels[lang_filter].lower())
        filter_desc = f" ({', '.join(filter_parts)})" if filter_parts else ""
        
        # Build URL for pagination
        def build_page_url(p):
            params = {"q": query, "page": str(p)}
            if scope != "all":
                params["scope"] = scope
            if lang_filter:
                params["lang"] = lang_filter
            return "/search?" + "&".join(f"{k}={quote(v)}" for k, v in params.items())
        
        selected = lambda v, k: 'selected' if v == k else ''
        
        body = f"""
        <h2 style="color:#4a2c1a;margin:16px 0;">Search Results</h2>
        <form class="search-box" action="/search" method="get">
            <input type="text" name="q" placeholder="{scope_placeholder[scope]}" value="{query}">
            <select name="scope">
                <option value="all" {selected(scope, 'all')}>All fields</option>
                <option value="author" {selected(scope, 'author')}>Author</option>
                <option value="title" {selected(scope, 'title')}>Title</option>
            </select>
            <select name="lang">
                <option value="" {selected(lang_filter, '')}>All languages</option>
                <option value="grc" {selected(lang_filter, 'grc')}>Greek only</option>
                <option value="lat" {selected(lang_filter, 'lat')}>Latin only</option>
            </select>
            <button type="submit">Search</button>
        </form>
        <p style="margin-bottom:12px;color:#666;">{total:,} result{'s' if total != 1 else ''} for <strong>{query}</strong>{filter_desc}</p>
        """
        
        for r in results:
            tid, author, title, lang, wc, snip = r
            icon = lang_icons.get(lang, "📄")
            body += f"""
            <div class="result-item">
                <h4><a href="/read?id={tid}" style="color:#4a2c1a;text-decoration:none;">{icon} {title}</a></h4>
                <div class="meta">{author} · {lang.upper()} · {wc:,} words</div>
                <div class="snippet">{snip}</div>
            </div>"""
        
        if not results:
            body += '<p style="color:#888;text-align:center;padding:30px;">No results found. Try different search terms or broaden your filters.</p>'
        
        if total_pages > 1:
            body += '<div class="pagination">'
            for p in range(max(1, page - 3), min(total_pages, page + 3) + 1):
                active = ' style="background:#4a2c1a;color:#fff;"' if p == page else ""
                body += f'<a href="{build_page_url(p)}"{active}>{p}</a>'
            body += '</div>'
        
        self._html(body)

    def handle_dictionary(self, qs):
        query = qs.get("q", "").strip()
        mode = qs.get("mode", "headword")  # 'headword' (default) or 'fulltext'
        # Normalize search query to NFC for consistent matching
        import unicodedata
        query = unicodedata.normalize('NFC', query)
        page = int(qs.get("page", "1"))
        per_page = 30
        offset = (page - 1) * per_page
        source_filter = qs.get("source", "")
        
        conn = self.get_db()
        cur = conn.cursor()
        
        if query:
            like_q = f"%{query}%"
            # Headword-only search is the default (tighter matching)
            # Full-text search (includes definitions) is opt-in
            if mode == "fulltext":
                where_headword = "(headword LIKE ? OR headword_greek LIKE ? OR headword_plain LIKE ? OR definition LIKE ?)"
                where_params = (like_q, like_q, like_q, like_q)
            else:
                where_headword = "(headword LIKE ? OR headword_greek LIKE ? OR headword_plain LIKE ?)"
                where_params = (like_q, like_q, like_q)
            
            # Order so prefix matches come first, then substring matches
            order_clause = "ORDER BY CASE WHEN headword LIKE ? THEN 0 WHEN headword_plain LIKE ? THEN 0 ELSE 1 END, headword"
            prefix_q = f"{query}%"
            
            if source_filter:
                cur.execute(
                    "SELECT headword, headword_greek, definition, source FROM dictionary_entries "
                    "WHERE {} AND source = ? "
                    "{} LIMIT ? OFFSET ?".format(where_headword, order_clause),
                    where_params + (source_filter, prefix_q, prefix_q, per_page, offset),
                )
                rows = cur.fetchall()
                cur.execute(
                    "SELECT COUNT(*) FROM dictionary_entries "
                    "WHERE {} AND source = ?".format(where_headword),
                    where_params + (source_filter,),
                )
            else:
                cur.execute(
                    "SELECT headword, headword_greek, definition, source FROM dictionary_entries "
                    "WHERE {} "
                    "{} LIMIT ? OFFSET ?".format(where_headword, order_clause),
                    where_params + (prefix_q, prefix_q, per_page, offset),
                )
                rows = cur.fetchall()
                cur.execute(
                    "SELECT COUNT(*) FROM dictionary_entries "
                    "WHERE {}".format(where_headword),
                    where_params,
                )
        else:
            if source_filter:
                cur.execute(
                    "SELECT headword, headword_greek, definition, source FROM dictionary_entries "
                    "WHERE source = ? ORDER BY headword LIMIT ? OFFSET ?",
                    (source_filter, per_page, offset),
                )
                rows = cur.fetchall()
                cur.execute(
                    "SELECT COUNT(*) FROM dictionary_entries WHERE source = ?",
                    (source_filter,),
                )
            else:
                cur.execute(
                    "SELECT headword, headword_greek, definition, source FROM dictionary_entries "
                    "ORDER BY headword LIMIT ? OFFSET ?",
                    (per_page, offset),
                )
                rows = cur.fetchall()
                cur.execute("SELECT COUNT(*) FROM dictionary_entries")
        
        total = cur.fetchone()[0]
        conn.close()
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        
        source_opts = {"": "All", "LSJ": "LSJ (Greek)", "Lewis & Short": "Lewis & Short (Latin)"}
        source_sel = lambda v: 'selected' if v == source_filter else ''
        mode = qs.get("mode", "headword")
        mode_full_sel = 'selected' if mode == 'fulltext' else ''
        mode_head_sel = 'selected' if mode != 'fulltext' else ''
        
        body = f"""
        <h2 style="color:#4a2c1a;margin:16px 0;">📖 Dictionaries</h2>
        
        <form class="search-box" action="/dictionary" method="get">
            <input type="text" name="q" placeholder="Look up a word..." value="{query}">
            <select name="source" style="padding:10px;border:2px solid #c9a87c;border-radius:4px;">
                {''.join(f'<option value="{k}" {source_sel(k)}>{v}</option>' for k, v in source_opts.items())}
            </select>
            <select name="mode" style="padding:10px;border:2px solid #c9a87c;border-radius:4px;">
                <option value="headword" {mode_head_sel}>Headword only</option>
                <option value="fulltext" {mode_full_sel}>Full text (incl. definitions)</option>
            </select>
            <button type="submit">Look Up</button>
        </form>
        <p style="margin-bottom:12px;color:#666;">{total:,} entries found{f' (headword match)' if mode != 'fulltext' else ' (full-text match)'}</p>
        """
        
        for headword, headword_greek, definition, source in rows:
            # Clean definition for display
            if source == 'LSJ':
                display_def = clean_greek_definition(definition)
                short_def = (display_def[:200] + "…") if len(display_def) > 200 else display_def
                formatted = html.escape(format_greek_entry(definition, truncate=False))
            else:
                short_def = (definition[:200] + "…") if len(definition) > 200 else definition
                formatted = html.escape(format_full_entry(definition, truncate=False))
            # Greek headword as primary display, Beta Code as subtle secondary
            if headword_greek and headword_greek.strip():
                display_title = f'{headword_greek} <span style="font-size:0.7em;color:#aaa;">({headword})</span>'
            else:
                # Fallback: try converting Beta Code to Greek on the fly
                converted = beta_to_greek(headword)
                if converted and converted != headword:
                    display_title = f'{converted} <span style="font-size:0.7em;color:#aaa;">({headword})</span>'
                else:
                    display_title = headword
            # Escape headwords for data attributes
            esc_headword = headword.replace('"', '&quot;').replace("'", "&#39;")
            hw_greek_for_data = headword_greek or beta_to_greek(headword)
            if not hw_greek_for_data or hw_greek_for_data == headword:
                hw_greek_for_data = headword
            esc_hw_greek = hw_greek_for_data.replace('"', '&quot;').replace("'", "&#39;")
            body += f"""
            <div class="dict-entry" style="cursor:pointer;" onclick="openDictEntry(this)" 
                 data-headword="{esc_hw_greek or esc_headword}" data-source="{source}" 
                 data-formatted='{formatted}'>
                <div class="headword">{display_title} <span class="source">{source}</span></div>
                <div class="dict-def">{short_def}</div>
            </div>"""
        
        if not rows and query:
            if mode == "fulltext":
                body += '<p style="color:#888;text-align:center;padding:30px;">No entries found. Try a different search term.</p>'
            else:
                body += '<p style="color:#888;text-align:center;padding:30px;">No entries found matching headword. Try <a href="/dictionary?q={}&mode=fulltext&source={}" style="color:#4a2c1a;">full-text search</a> to search inside definitions.</p>'.format(quote(query), source_filter)
        
        if total_pages > 1:
            src_param = f"&source={source_filter}" if source_filter else ""
            mode_param = f"&mode={mode}" if mode != "headword" else ""
            body += '<div class="pagination">'
            for p in range(max(1, page - 3), min(total_pages, page + 3) + 1):
                active = ' style="background:#4a2c1a;color:#fff;"' if p == page else ""
                body += f'<a href="/dictionary?q={quote(query)}{src_param}{mode_param}&page={p}"{active}>{p}</a>'
            body += '</div>'
        
        # Add modal overlay and popup for full entry display
        body += """
        <div id="dictFullPopup" style="display:none;position:fixed;z-index:2000;
            background:#fffdfa;border:1px solid #c9a87c;border-radius:12px;
            padding:24px 28px;width:min(900px, calc(100vw - 32px));max-height:84vh;overflow-y:auto;
            box-shadow:0 16px 48px rgba(0,0,0,0.22);font-size:0.98em;line-height:1.72;
            pointer-events:auto;top:50%;left:50%;transform:translate(-50%,-50%);"></div>
        <div id="dictFullOverlay" style="display:none;position:fixed;z-index:1999;
            top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);"
            onclick="closeDictEntry();"></div>
        <script>
        function openDictEntry(el) {
            var headword = el.getAttribute('data-headword');
            var source = el.getAttribute('data-source');
            var formatted = el.getAttribute('data-formatted');
            var popup = document.getElementById('dictFullPopup');
            var overlay = document.getElementById('dictFullOverlay');
            popup.innerHTML =
                '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px;padding-bottom:12px;border-bottom:2px solid #c9a87c;">' +
                '<div><div style="font-size:0.75em;letter-spacing:0.08em;text-transform:uppercase;color:#9a7a52;margin-bottom:6px;">Dictionary Entry</div>' +
                '<div style="font-size:1.45em;font-weight:700;color:#4a2c1a;line-height:1.2;">' + headword + '</div></div>' +
                '<div style="font-weight:600;font-size:0.78em;letter-spacing:0.04em;text-transform:uppercase;color:#9a7a52;margin-top:6px;white-space:nowrap;">' + source + '</div>' +
                '<button type="button" style="cursor:pointer;font-size:1.4em;line-height:1;color:#8a8a8a;background:none;border:none;padding:0;font-family:serif;" onclick="closeDictEntry();">&times;</button></div>' +
                (formatted || '<div style="color:#888;">No formatted entry available.</div>') +
                '<div style="margin-top:12px;padding-top:10px;border-top:1px solid #eee;font-size:0.82em;color:#8b8b8b;text-align:center;">Press Esc or click outside to close.</div>';
            popup.style.display = 'block';
            overlay.style.display = 'block';
        }
        function closeDictEntry() {
            document.getElementById('dictFullPopup').style.display = 'none';
            document.getElementById('dictFullOverlay').style.display = 'none';
        }
        window.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') closeDictEntry();
        });
        </script>
        """
        
        self._html(body)

    def handle_about(self):
        body = """
        <div class="text-viewer" style="margin-top:16px;">
            <h2 style="color:#4a2c1a;">About Perseus Minimalist v0.1</h2>
            <div style="text-align:center;margin:16px 0;">
                <img src="/static/perseus_logo.png" style="height:80px;width:80px;border-radius:50%;box-shadow:0 2px 8px rgba(0,0,0,0.15);" alt="Perseus Minimalist">
            </div>
            <p style="font-size:0.8em;color:#999;margin-bottom:16px;font-style:italic;">Dedicated to Eflatun İlyas, designed over the request of Saygın G.</p>
            <p><em>Perseus Minimalist v0.1</em> provides offline access to texts from the 
            <a href="http://www.perseus.tufts.edu/">Perseus Digital Library</a> 
            at Tufts University, with morphological analysis powered by 
            <a href="https://mk270.github.io/whitakers-words/">Whitaker's Words</a>.</p>
            
            <h3 style="color:#4a2c1a;margin-top:20px;">Data Sources</h3>
            <ul style="margin-left:20px;">
                <li><strong>Greek Texts</strong> — <a href="https://github.com/PerseusDL/canonical-greekLit">github.com/PerseusDL/canonical-greekLit</a></li>
                <li><strong>Latin Texts</strong> — <a href="https://github.com/PerseusDL/canonical-latinLit">github.com/PerseusDL/canonical-latinLit</a></li>
                <li><strong>LSJ Dictionary</strong> — <a href="https://github.com/PerseusDL/lexica">github.com/PerseusDL/lexica</a></li>
                <li><strong>Lewis &amp; Short</strong> — <a href="https://github.com/PerseusDL/lexica">github.com/PerseusDL/lexica</a></li>
                <li><strong>Latin Morphology (Whitaker's Words)</strong> — <a href="https://github.com/mk270/whitakers-words">github.com/mk270/whitakers-words</a></li>
                <li><strong>Greek Morphology (CLTK / Stanza)</strong> — <a href="https://github.com/cltk/cltk">github.com/cltk/cltk</a></li>
            </ul>
            
            <h3 style="color:#4a2c1a;margin-top:20px;">License</h3>
            <p>All Perseus texts are provided under a 
            <a href="https://creativecommons.org/licenses/by-sa/4.0/">Creative Commons Attribution-ShareAlike 4.0 International License</a>
            by the Perseus Digital Library.</p>
            <p>Whitaker's Words is in the public domain.</p>
            
            <h3 style="color:#4a2c1a;margin-top:20px;">Usage</h3>
            <ul style="margin-left:20px;">
                <li><code>setup.bat</code> — First-time setup (double-click)</li>
                <li><code>start.bat</code> — Launch the viewer (double-click)</li>
                <li><code>python perseus_offline.py download</code> — Download all data</li>
                <li><code>python perseus_offline.py serve</code> — Start the web viewer</li>
                <li><code>python perseus_offline.py all</code> — Download then serve</li>
            </ul>
        </div>
        """
        self._html(body)

    def serve_static(self, path):
        # Serve static files (logo, etc.) from project root
        import mimetypes
        # Map /static/filename → filename in project root
        filename = path.replace("/static/", "", 1)
        filepath = Path(__file__).parent / filename
        if filepath.exists() and filepath.is_file():
            mime, _ = mimetypes.guess_type(str(filepath))
            try:
                with open(str(filepath), "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception:
                pass
        self.send_error(404)


# ── Main CLI ───────────────────────────────────────────────────────────────

def cmd_download():
    """Download all Perseus data from GitHub."""
    log("=" * 60)
    log("Perseus Minimalist v0.1 — Downloading Data")
    log("=" * 60)
    
    download_dir = DATA_DIR / "repos"
    download_dir.mkdir(parents=True, exist_ok=True)
    
    for key, repo in REPOS.items():
        log(f"\n{'─' * 40}")
        log(f"Downloading {repo['label']}...")
        success = download_zip(repo["url"], download_dir, key)
        if success:
            log(f"✓ {repo['label']} downloaded successfully.")
        else:
            log(f"✗ Failed to download {repo['label']}.")
    
    log(f"\n{'=' * 40}")
    log("Building search index...")
    log(f"{'=' * 40}")
    
    conn = init_db()
    
    index_greek_latin_texts(conn, download_dir, "greek")
    index_greek_latin_texts(conn, download_dir, "latin")
    index_lexica(conn, download_dir)
    rebuild_fts(conn)
    
    conn.close()
    
    log(f"\n✓ Download complete! Data saved to: {DATA_DIR}")
    
    # Show stats
    conn2 = sqlite3.connect(str(DB_PATH))
    cur = conn2.cursor()
    cur.execute("SELECT COUNT(*) FROM texts")
    log(f"  Texts indexed: {cur.fetchone()[0]:,}")
    cur.execute("SELECT COUNT(*) FROM dictionary_entries")
    log(f"  Dictionary entries: {cur.fetchone()[0]:,}")
    cur.execute("SELECT SUM(word_count) FROM texts")
    total = cur.fetchone()[0] or 0
    log(f"  Total words: {total:,}")
    conn2.close()
    
    log(f"\nRun 'python perseus_offline.py serve' to start the web viewer.")


def cmd_rebuild():
    """Rebuild the search index from existing repos (no download)."""
    log("=" * 60)
    log("Perseus Minimalist v0.1 — Rebuilding Index")
    log("=" * 60)
    
    download_dir = DATA_DIR / "repos"
    
    if not (download_dir / "greek" / "data").exists() and not (download_dir / "latin" / "data").exists():
        log("No existing repos found. Run 'download' first.")
        return
    
    log("Using existing repos (no download)...")
    
    conn = init_db()
    
    # Clear old data
    cur = conn.cursor()
    cur.execute("DELETE FROM texts")
    cur.execute("DELETE FROM dictionary_entries")
    conn.commit()
    
    index_greek_latin_texts(conn, download_dir, "greek")
    index_greek_latin_texts(conn, download_dir, "latin")
    index_lexica(conn, download_dir)
    rebuild_fts(conn)
    
    conn.close()
    
    log(f"\n✓ Index rebuilt!")
    
    conn2 = sqlite3.connect(str(DB_PATH))
    cur = conn2.cursor()
    cur.execute("SELECT COUNT(*) FROM texts")
    log(f"  Texts indexed: {cur.fetchone()[0]:,}")
    cur.execute("SELECT COUNT(*) FROM dictionary_entries")
    log(f"  Dictionary entries: {cur.fetchone()[0]:,}")
    conn2.close()
    
    log(f"\nRun 'python perseus_offline.py serve' to start the web viewer.")


def cmd_serve():
    """Start the local web viewer."""
    if not DB_PATH.exists():
        log("No data found. Run 'python perseus_offline.py download' first.")
        return
    
    # Check total data size
    total_size = sum(
        f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file()
    )
    log(f"Data directory: {DATA_DIR}")
    log(f"Total data size: {total_size / 1024 / 1024:.1f} MB")
    
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM texts")
    texts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM dictionary_entries")
    dicts = cur.fetchone()[0]
    conn.close()
    
    log(f"Texts: {texts:,}  |  Dictionary entries: {dicts:,}")
    
    host = "127.0.0.1"
    port = 8080
    server = http.server.HTTPServer((host, port), PerseusHandler)
    
    # Pre-load Greek NLP models in background so first request is instant
    threading.Thread(target=get_greek_nlp, daemon=True).start()
    
    print()
    log("=" * 60)
    log("Perseus Minimalist v0.1 — Ready!")
    log(f"Open http://{host}:{port} in your browser")
    log("Press Ctrl+C to stop the server")
    log("=" * 60)
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\nServer stopped.")


def cmd_all():
    """Download all data then start the server."""
    cmd_download()
    print("\n" * 2)
    cmd_serve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Perseus Minimalist v0.1 — Download and browse the Perseus Digital Library locally"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["download", "rebuild", "serve", "all"],
        help="What to do (default: all)",
    )
    args = parser.parse_args()
    
    if args.command == "download":
        cmd_download()
    elif args.command == "rebuild":
        cmd_rebuild()
    elif args.command == "serve":
        cmd_serve()
    elif args.command == "all":
        cmd_all()
    else:
        parser.print_help()
