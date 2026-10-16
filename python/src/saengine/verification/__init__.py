"""SAEngine's verification pack: benchmark problems with independent references.

Each case runs a small model through SAEngine's real pipeline (or calls its design functions)
and compares the result with a closed-form solution, a hand calculation written out in the case
or a published benchmark, within a stated tolerance. :mod:`saengine.verification.run` runs them
all and writes ``verification.json`` and the Verification Manual PDF.
"""
