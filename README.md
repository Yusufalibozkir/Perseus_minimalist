# 📚 Perseus Minimalist v0.1

<p align="center">
  <img src="perseus_logo.png" width="120" height="120" style="border-radius:50%;" alt="Perseus Minimalist">
</p>

**Browse the Perseus Digital Library — completely offline, minimal & fast.**

Download Greek and Latin classical texts (2 million+ lines), the LSJ Greek Lexicon,
and Lewis & Short Latin Dictionary, then read everything on your own machine with
morphological analysis on hover — all without an internet connection.

---

## Quick Start

### 1. Install Python
Download **Python 3.11+** from [python.org](https://www.python.org/downloads/).
During installation, **check "Add Python to PATH"**.

### 2. Run Setup (one time)
Double-click **`setup.bat`**. It will:
1. Create a Python virtual environment
2. Install dependencies (~5 min, 770 MB)
3. Download texts and dictionaries from Perseus (~10 min, 930 MB)
4. Build the search index (~2 min)

### 3. Start the Viewer
Double-click **`start.bat`** — your browser opens to the home page.

---

## Features

| Feature | Greek | Latin |
|---------|-------|-------|
| Full-text search | ✅ | ✅ |
| Browse by author/work | ✅ | ✅ |
| In-text search with highlights | ✅ | ✅ |
| Hover → morphology + definition | ✅ (CLTK/Stanza) | ✅ (Whitaker's Words) |
| Double-click → full dictionary entry | ✅ (LSJ) | ✅ (Lewis & Short) |
| Dictionary lookup (headword + full-text) | ✅ | ✅ |
| Inflected form lookup | ✅ | ✅ |
| Principal parts display | — | ✅ |
| Formatted dictionary entries with citations | — | ✅ |
| Scroll progress indicator | ✅ | ✅ |
| Scroll-to-top | ✅ | ✅ |

---

## Data Sources

| Source | Size | Description |
|--------|------|-------------|
| [Perseus Greek Texts](https://github.com/PerseusDL/canonical-greekLit) | 1,611 works | Homer, Plato, Aristotle, etc. |
| [Perseus Latin Texts](https://github.com/PerseusDL/canonical-latinLit) | 626 works | Cicero, Vergil, Ovid, etc. |
| [LSJ Greek Lexicon](https://github.com/PerseusDL/lexica) | 115k entries | Greek–English |
| [Lewis & Short](https://github.com/PerseusDL/lexica) | 103k entries | Latin–English |
| [Whitaker's Words](https://github.com/mk270/whitakers-words) | 39k lemmas | Latin morphology |
| [CLTK / Stanza](https://github.com/cltk/cltk) | — | Greek morphology |

---

## Project Structure

```
📁 Perseus-Minimalist/
├── perseus_offline.py      # Main application (single file)
├── setup.bat               # One-time installer
├── start.bat               # Daily launcher
├── README.md               # This file
├── LICENSE
├── .gitignore
└── perseus_data/
    ├── morphology/          # Whitaker's Words (in repo, ~6 MB)
    ├── repos/               # Raw Perseus XML (downloaded, 930 MB)
    └── perseus_index.db     # SQLite search index (generated, 1.7 GB)
```

## CLI Usage

```bash
python perseus_offline.py download    # Download all data
python perseus_offline.py serve       # Start the web viewer
python perseus_offline.py all         # Download then serve
```

---

## Dedication

*Dedicated to Eflatun İlyas, designed over the request of Saygın G.*

## License

All Perseus texts are provided under a [Creative Commons Attribution-ShareAlike 4.0 International License](https://creativecommons.org/licenses/by-sa/4.0/) by the [Perseus Digital Library](https://www.perseus.tufts.edu/) at Tufts University.

Whitaker's Words is in the public domain.


---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Step-by-Step Installation](#step-by-step-installation)
- [Usage](#usage)
- [Web Interface Guide](#web-interface-guide)
- [Data Details](#data-details)
- [Project Structure](#project-structure)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## Features

- **Offline-first** — Download once, use forever without internet.
- **40+ million words** — The full Perseus Greek (~8M words) and Latin (~5.5M
  words) corpora, plus English translations.
- **Two world-class dictionaries** — The complete Liddell–Scott–Jones (LSJ)
  Greek–English Lexicon and Lewis & Short Latin–English Dictionary
  (~220,000 entries combined).
- **Full-text search** — Search every word across the entire corpus using
  SQLite FTS5 technology.
- **Beta Code & Unicode Greek** — Search LSJ entries using either traditional
  Beta Code (`a)reth/`) or modern Unicode Greek (`ἀρετή`).
- **Beautiful reader** — Clean, typographic reading view optimised for
  classical texts.
- **Cross-platform** — Pure Python, works on Windows, macOS, and Linux.

---

## Requirements

- **Python 3.9 or later**
- **~2 GB free disk space** (the downloaded data is ~1.4 GB)
- A modern web browser (Chrome, Firefox, Edge, Safari)
- An internet connection (only needed for the initial download)

No external Python packages are needed — the script uses only the standard
library.

---

## Quick Start

```bash
# 1. Download everything
python perseus_offline.py download

# 2. Start the viewer
python perseus_offline.py serve
```

Then open **http://localhost:8080** in your browser.

---

## Step-by-Step Installation

### 1. Get the script

Place `perseus_offline.py` in a folder of your choice:

```bash
mkdir Perseus
cd Perseus
# Copy perseus_offline.py into this folder
```

### 2. (Optional but recommended) Create a virtual environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Download the data

```bash
python perseus_offline.py download
```

This will download three repositories from GitHub:

| Repository | Contents | Size |
|---|---|---|
| `canonical-greekLit` | Greek literary texts (TEI XML) | ~600 MB |
| `canonical-latinLit` | Latin literary texts (TEI XML) | ~400 MB |
| `lexica` | LSJ & Lewis & Short dictionaries | ~400 MB |

**What to expect:**
- The download takes **5–15 minutes** depending on your connection speed.
- After downloading, the script **parses and indexes** all texts (~2,200+ works
  and ~220,000 dictionary entries).
- The final index is stored in `perseus_data/perseus_index.db`.
- Total data on disk: **~1.4 GB**.

### 4. Start the viewer

```bash
python perseus_offline.py serve
```

You will see:

```
[18:04:39] Data directory: C:\...\Perseus\perseus_data
[18:04:39] Total data size: 1435.7 MB
[18:04:39] Texts: 2,237  |  Dictionary entries: 219,727

[18:04:39] ============================================================
[18:04:39] Perseus Offline — Ready!
[18:04:39] Open http://127.0.0.1:8080 in your browser
[18:04:39] Press Ctrl+C to stop the server
[18:04:39] ============================================================
```

### 5. Open in your browser

Navigate to **http://127.0.0.1:8080** (or **http://localhost:8080**).

---

## Usage

### Command reference

| Command | Description |
|---|---|
| `python perseus_offline.py download` | Download all texts and dictionaries from GitHub and build the search index |
| `python perseus_offline.py serve` | Start the local web viewer (requires data to be downloaded first) |
| `python perseus_offline.py all` | Download data **and** start the server in one command |
| `python perseus_offline.py --help` | Show usage help |

### Keyboard shortcuts (terminal)

| Key | Action |
|---|---|
| `Ctrl+C` | Stop the server |

### Re-downloading

The script always downloads fresh copies. If you want to update the data,
simply run `download` again — it will replace the existing data.

---

## Web Interface Guide

### 🏠 Home page

The dashboard shows an overview of your local library:

- **Total texts** indexed
- **Greek / Latin** work counts
- **Dictionary entries** available
- **Total word count**
- Quick links to browse by collection or search

### 🏛️ Browsing texts

1. Click **Greek Texts** or **Latin Texts** in the navigation bar.
2. Browse the list of authors and works (50 per page).
3. Use the **Filter** box to narrow by author or title.
4. Click a title to open the **reading view**.

### 📖 Reading a text

The reading view displays the full text with proper typography:

- Greek texts are shown in a serif font (`Linux Libertine`, `Gentium Plus`).
- Latin texts are shown in a standard serif face.
- The file path and language are shown below the title.

### 🔍 Full-text search

1. Type a word or phrase into the search box on the home page, or go to
   **Search**.
2. Results show a snippet with your query highlighted.
3. Click any result to open the full text.
4. Use pagination to browse through large result sets.

**Search tips:**
- Search for *any* word: `amicitia`, `πόλεμος`, `Gallia`
- Search for phrases that appear near each other
- Author names and titles are also searchable

### 📖 Dictionaries

Two dictionaries are included:

| Dictionary | Language | Entries |
|---|---|---|
| **LSJ** (Liddell–Scott–Jones) | Greek → English | ~116,000 |
| **Lewis & Short** | Latin → English | ~103,000 |

**To look up a word:**

1. Click **Dictionaries** in the navigation bar.
2. Type your word in the search box.
3. (Optional) Select a specific dictionary from the dropdown.
4. Click **Look Up**.

**Searching LSJ with Greek text:**

The LSJ entries are stored in **Beta Code** (an ASCII-based representation of
Greek), but the system also stores a Unicode Greek conversion. You can search
either way:

| You type | What it finds | Example result |
|---|---|---|
| `a)reth/` (Beta Code) | Matches the stored headword | `a)reth/  ἀρετή` |
| `ἀρετή` (Unicode) | Matches the converted Greek form | `a)reth/  ἀρετή` |
| `amor` (Latin) | Matches Lewis & Short | Definitions of *amor* |

**Tip:** If you don't know the Beta Code, just type the Greek word in Unicode
— it will find the matching entries.

### ℹ️ About page

Shows information about the data sources, license information, and usage
instructions.

---

## Data Details

### Texts

The Greek and Latin texts are sourced from the Perseus Digital Library's
canonical repositories on GitHub:

- **Greek**: [github.com/PerseusDL/canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit)
- **Latin**: [github.com/PerseusDL/canonical-latinLit](https://github.com/PerseusDL/canonical-latinLit)

The texts are in **TEI XML** format (Text Encoding Initiative), a widely-used
standard for digital humanities. The script extracts the plain text content
from the XML, preserving paragraph and line structure.

### Dictionaries

- **LSJ** (Liddell–Scott–Jones *Greek–English Lexicon*, 9th ed. 1940):
  [github.com/PerseusDL/lexica](https://github.com/PerseusDL/lexica)
- **Lewis & Short** (*A Latin Dictionary*, 1879):
  [github.com/PerseusDL/lexica](https://github.com/PerseusDL/lexica)

Both dictionaries use the **TEI P4** dictionary format with Beta Code
encoding for Greek headwords. The script converts Beta Code to Unicode Greek
using a built-in converter.

### File format support

Currently the viewer understands:
- **TEI P5** texts (with `xmlns="http://www.tei-c.org/ns/1.0"`) — used by
  Greek and Latin texts.
- **TEI P4** dictionaries (with `<entryFree>` elements, no namespace) — used
  by LSJ and Lewis & Short.

### Search index

The SQLite database (`perseus_data/perseus_index.db`) uses **FTS5** (Full-Text
Search version 5) for fast, ranked searching across millions of words.

---

## Project Structure

```
Perseus/
├── perseus_offline.py        # Main script (download, index, serve)
├── README.md                 # This file
└── perseus_data/             # Created by the download command
    ├── perseus_index.db      # SQLite search index (~300 MB)
    ├── repos/                # Downloaded raw data
    │   ├── greek/            # Greek TEI XML files
    │   ├── latin/            # Latin TEI XML files
    │   └── lexica/           # Dictionary XML files
    └── www/                  # (reserved for future static assets)
```

---

## Troubleshooting

### "No data found" when running `serve`

Run `python perseus_offline.py download` first. The download must complete
successfully before the server can start.

### Download fails or times out

The GitHub repositories are large. If the download fails:

1. Check your internet connection.
2. Try again — the script will re-download.
3. If it consistently fails, try using a different network or a VPN.

### Search is slow

With 40 million words, some broad searches (e.g. a single common letter) may
take a moment. Try using more specific search terms.

### Greek characters don't display correctly

Make sure your browser supports Unicode and you have a font that includes
Greek characters. Most modern browsers include such fonts by default.
The reader specifically requests `Linux Libertine`, `Gentium Plus`, and
`Palatino Linotype` for Greek text.

### Port 8080 is already in use

Only one instance of the server can run at a time. If port 8080 is taken:

1. Stop any other instances (use `Ctrl+C` in the terminal).
2. Make sure no other program is using port 8080.

---

## License

The software in this repository is provided for personal, educational, and
scholarly use.

**Data license:** All texts and dictionary data are provided under a
[Creative Commons Attribution-ShareAlike 4.0 International License](https://creativecommons.org/licenses/by-sa/4.0/)
by the Perseus Digital Library, Tufts University.

When using or redistributing the data, please credit:

> Text provided under a CC BY-SA license by Perseus Digital Library,
> http://www.perseus.tufts.edu/, with funding from The National Endowment
> for the Humanities.
> Data accessed from https://github.com/PerseusDL/

---

## Acknowledgments

- The **Perseus Digital Library** at Tufts University
  ([perseus.tufts.edu](http://www.perseus.tufts.edu/)) for creating and
  maintaining these invaluable resources.
- The **Perseus at UChicago** project
  ([perseus.uchicago.edu](https://perseus.uchicago.edu/)) for the PhiloLogic
  search interface that inspired this offline tool.
- All the editors, contributors, and funding agencies who have supported the
  Perseus Project over decades of digital humanities work.
