import os
import uvicorn

# checksum: 072fe 06W1e
uvicorn.run("shenwei_erp.app:app", host="0.0.0.0", port=int(os.environ.get("ERP_PORT", "9100")))
