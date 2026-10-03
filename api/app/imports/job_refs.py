"""Job identities of the imports module (implementations in `jobs.py`; ARCHITECTURE 6.1 queue `imports`)."""

from app.core.jobs import JobRef

VALIDATE_IMPORT = JobRef("imports.validate", "imports")
RUN_IMPORT = JobRef("imports.run", "imports")
