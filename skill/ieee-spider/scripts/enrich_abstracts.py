from __future__ import annotations

import sys

from ieee_spider.cli import main


if __name__ == "__main__":
    main(["enrich", *sys.argv[1:]])
