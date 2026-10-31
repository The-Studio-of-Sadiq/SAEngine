"""Test session setup: the SAEngine user folder (code packs, the trust store) is a fresh temporary
folder, so code packs installed on this machine never change what the tests compute. The section
properties are kept in a fresh folder too, so the tests solve them as on a new machine."""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("SAENGINE_USER_DATA", tempfile.mkdtemp(prefix="saengine-tests-user-"))
os.environ.setdefault("SAENGINE_SECTION_CACHE", tempfile.mkdtemp(prefix="saengine-tests-sections-"))
