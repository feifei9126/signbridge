#!/usr/bin/env python3
"""Run the repository's hyphenated Python test modules with the chosen interpreter."""
import importlib.util
from pathlib import Path
import sys
import unittest


def main():
    tests = Path(__file__).resolve().parents[2] / 'tests'
    suite = unittest.TestSuite()
    for index, path in enumerate(sorted(tests.glob('*.test.py'))):
        name = f'signbridge_suite_{index}'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
