"""Read-only: cek status device Fonnte langsung via API (bukan dashboard) - buat verifikasi
device beneran connect/nyambung, bukan cuma dashboard yang keliatan connect tapi device
sebenarnya limited/expired."""

import json
import sys

import requests

sys.path.insert(0, ".")
from config import FONNTE_TOKEN

resp = requests.post(
    "https://api.fonnte.com/device",
    headers={"Authorization": FONNTE_TOKEN},
    timeout=20,
)
print("STATUS CODE:", resp.status_code)
print(json.dumps(resp.json(), indent=2))
