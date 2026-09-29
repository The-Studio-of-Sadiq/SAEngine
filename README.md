# SAEngine — Structure Analysis Engine

> A modern, open-source structural analysis and design platform powered by OpenSeesPy.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Overview

SAEngine is a cross-platform desktop application for structural analysis and design of building systems. It provides an intuitive 3D modeling environment backed by the proven OpenSees finite element framework.

## Features

- 🏗️ 3D object-based structural modeling (beams, columns, walls, slabs)
- 📐 Grid and story system for building definition
- 💻 **Integrated Code Studio**: Full multi-tab code editor with syntax highlighting (Python, OpenSeesPy, JSON, Diffs), line numbers, auto-indentation, and search/replace
- 🖥️ **Interactive Terminal & Python REPL**: Integrated shell terminal (PowerShell/cmd/bash) and live Python console executing against the active project
- 📁 **Workspace File Explorer**: Tree view of repository files with create, rename, delete, and open actions
- 🌿 **Git Version Control**: Full GUI for branches, staged/unstaged changes, diffs, commits, and remote push/pull
- ⚡ Linear and nonlinear structural analysis via OpenSeesPy
- 🌊 Seismic analysis (response spectrum, time history, pushover)
- 🏛️ Code-based design checking (plugin architecture)
- 📊 Result visualization (deformed shapes, force diagrams, contour plots)
- 💾 JSON/CSV import for design code properties and section databases
- 🖥️ Cross-platform: Windows, macOS, Linux

## Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/saengine.git
cd saengine

# Create virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Launch
saengine
# or
python -m saengine
```

## Tech Stack

| Component | Technology |
|:---|:---|
| GUI | PySide6 (Qt 6) |
| 3D Visualization | PyVista + VTK |
| FE Solver | OpenSeesPy |
| Numerical | NumPy, SciPy, Pandas |
| Database | SQLite |

## License

MIT License — free for everyone, forever.
