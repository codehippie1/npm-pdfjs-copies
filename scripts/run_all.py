"""Run the whole pipeline end to end. Every step is resumable; re-running skips finished work.

    set MSR_WORK=<a scratch folder outside this dataset>   (HTTP cache, tarball fallback)
    python -I scripts/run_all.py

Steps: s00 reference -> s01 frame -> s02 screen -> s03 releases -> s04 downloads -> s05 tables -> s06 numbers
"""
import os, runpy, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
STEPS = ["s00_reference", "s01_frame", "s02_screen", "s03_releases", "s04_downloads", "s05_tables", "s06_numbers",
         "s07_checks"]

if __name__ == "__main__":
    only = sys.argv[1:] or STEPS
    for s in STEPS:
        if s in only:
            print("==>", s, flush=True)
            runpy.run_path(os.path.join(HERE, s + ".py"), run_name="__main__")
