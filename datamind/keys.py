"""Key-pair login helper. Chalao: python -m datamind.keys  (ya: run.bat keygen)

Ek baar private key banata hai, uska path .env me likhta hai, aur woh SQL print karta hai jo public key ko Snowflake me register karta hai."""
import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .config import ROOT

KEY_DIR = ROOT / ".keys"
KEY_FILE = KEY_DIR / "snowflake_key.p8"


def keygen() -> int:
    KEY_DIR.mkdir(exist_ok=True)
    if not KEY_FILE.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY_FILE.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        print(f"Created private key: {KEY_FILE}  (never commit or share it)")
    else:
        print(f"Using existing private key: {KEY_FILE}")
    key = serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    pub = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()

    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    path_line = f"SNOWFLAKE_PRIVATE_KEY_PATH={KEY_FILE.as_posix()}"
    if any(l.startswith("SNOWFLAKE_PRIVATE_KEY_PATH=") for l in lines):
        lines = [path_line if l.startswith("SNOWFLAKE_PRIVATE_KEY_PATH=") else l for l in lines]
    else:
        lines.append(path_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nRun this in a Snowsight SQL file as ACCOUNTADMIN (Run all), then set SNOWFLAKE_USER=DM_APP in .env:\n")
    print("USE ROLE ACCOUNTADMIN;")
    print("CREATE USER IF NOT EXISTS DM_APP TYPE = SERVICE DEFAULT_ROLE = DM_READER DEFAULT_WAREHOUSE = DM_WH")
    print(f"  RSA_PUBLIC_KEY = '{pub}';")
    print("GRANT ROLE DM_READER TO USER DM_APP;")
    print("GRANT ROLE DM_LOADER TO USER DM_APP;")
    return 0


if __name__ == "__main__":
    sys.exit(keygen())
