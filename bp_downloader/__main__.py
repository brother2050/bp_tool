"""允许 python -m bp_downloader 运行 CLI。"""

import sys
from .cli import main

sys.exit(main())
