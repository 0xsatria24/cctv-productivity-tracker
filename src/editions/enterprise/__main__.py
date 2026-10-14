import sys
from cctv_tracker.cli import main

if __name__ == '__main__':
    # Retain the existing CLI's global-option ordering.
    main(sys.argv[1:] if 'dashboard' in sys.argv else ['dashboard', *sys.argv[1:]])
