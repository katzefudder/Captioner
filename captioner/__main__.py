import logging
import sys


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    from .ui.main_window import run
    sys.exit(run(sys.argv))


if __name__ == '__main__':
    main()
