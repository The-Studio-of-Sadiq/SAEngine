"""The ``saengine`` command line: a SAEngine project without the app (see ``docs/cli.md``).

The entry point is :func:`saengine.cli.main.main`; ``python -m saengine.cli`` runs it too.
"""

from saengine.cli.main import EXIT_CHECKS, EXIT_ERROR, EXIT_OK, EXIT_USAGE, main

__all__ = ["EXIT_CHECKS", "EXIT_ERROR", "EXIT_OK", "EXIT_USAGE", "main"]
