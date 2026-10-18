import os
import tempfile

# Test ka shor (fake query ids, simulated outages) asli logs/datamind.log se bahar rakho.
os.environ["DATAMIND_LOG_DIR"] = tempfile.mkdtemp(prefix="datamind-test-logs-")
