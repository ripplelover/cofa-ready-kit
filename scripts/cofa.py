"""Run the kit from any working directory, without installing a package."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module('cofa_kit', run_name='__main__')
