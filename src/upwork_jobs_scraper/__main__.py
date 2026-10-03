"""Allow ``python -m upwork_jobs_scraper``."""

import sys

from .cli import main

sys.exit(main())
