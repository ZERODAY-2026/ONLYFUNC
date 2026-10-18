import os
import tempfile

# Keep test noise (fake query ids, simulated outages) out of the real logs/datamind.log.
os.environ["DATAMIND_LOG_DIR"] = tempfile.mkdtemp(prefix="datamind-test-logs-")
