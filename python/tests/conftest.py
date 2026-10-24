"""Test session setup: the SAEngine user folder (code packs, the trust store) is a fresh temporary
folder, so code packs installed on this machine never change what the tests compute."""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("SAENGINE_USER_DATA", tempfile.mkdtemp(prefix="saengine-tests-user-"))
