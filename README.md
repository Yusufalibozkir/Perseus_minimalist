# <img src="perseus_logo.png" width="32" height="32" style="border-radius:50%;vertical-align:middle;margin-right:8px;" alt=""> Perseus Minimalist v0.1

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
2. Install dependencies (**CLTK/Stanza** for Greek morphology, **PyTorch**)
3. Download texts and dictionaries from Perseus (~10 min, 930 MB)
4. Build the search index and load **Whitaker's Words** for Latin morphology (~2 min)

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
