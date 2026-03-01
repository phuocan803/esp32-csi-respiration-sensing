# Certificates

Do not commit certificate or private key files to git.

Expected local files (ignored by `.gitignore`):
- certs/device.cert.pem
- certs/device.private.key
- certs/root-CA.pem

These files are required at runtime by `scripts/run.py` when AWS IoT is enabled.
