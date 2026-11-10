"""Suite completa, sin warnings ocultos ni omisiones silenciosas."""

import argparse
import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    warnings.simplefilter('error')
    suites = {'simulator': unittest.TestLoader().discover(str(ROOT / 'src/simulator'))}
    labels = {'test_backend': 'backend', 'test_frontend_integration': 'frontend',
              'test_firmware_parity': 'firmware_parity'}
    for path in sorted((ROOT / 'tests').glob('test_*.py')):
        suites[labels.get(path.stem, path.stem)] = unittest.TestLoader().loadTestsFromName('tests.' + path.stem)
    total = 0
    success = True
    print('QA VitiScan | warnings=error | optimize=' + str(sys.flags.optimize), flush=True)
    for name, suite in suites.items():
        print('\n[' + name + ']', flush=True)
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
        passed = max(0, result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped))
        print(f'{name}: {passed}/{result.testsRun}; omitidas={len(result.skipped)}', flush=True)
        total += passed
        success &= result.wasSuccessful() and not result.skipped
    print(f'\nTOTAL: {total} aprobadas | ' + ('OK, sin warnings ni omisiones' if success else 'FALLO'), flush=True)
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
