"""Opt-in office solving (alpha 9 L12, gap CO-4): an office machine runs analyses for the others.

- :mod:`saengine.office.server`: a small HTTP service (JSON-RPC over HTTP with a bearer token) that
  takes a project archive, runs Run All's steps on it headlessly and hands back what the run wrote;
- :mod:`saengine.office.client`: what the app (``office/*`` RPC methods) and the command line use
  to send a project to the server the engineer configured and bring the results back.

Off by default: nothing is sent anywhere until the engineer turns it on and enters the office
server's address and token. Project data only goes to that server; there is no third-party cloud.
"""
