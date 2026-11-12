"""Automation of alpha 9 L12: visual programs (:mod:`.graph`, gap API-6) and design studies
(:mod:`.studies`, gap API-7). Both keep their files in the project's ``12 Automation`` folder
(:data:`FOLDER`) and run through the backend: the graphs' nodes call the same functions the SDK,
the command line and Run All use; the studies run Run All's steps on copies of the project.
"""

#: The project folder of the graphs and the studies.
FOLDER = "12 Automation"
