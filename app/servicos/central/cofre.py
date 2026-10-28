import os

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field, SecretStr

from app.config import DATA_DIR


class Credencial(BaseModel):
    token: SecretStr = Field(repr=False)


def _chave() -> bytes:
    externa = os.environ.get("CENTRAL_MASTER_KEY")
    if externa:
        return externa.encode()
    destino = DATA_DIR / ".central-master.key"
    try:
        fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as arquivo:
            arquivo.write(Fernet.generate_key())
    destino.chmod(0o600)
    return destino.read_bytes()


def cifrar(credencial: Credencial) -> str:
    valor = credencial.token.get_secret_value().strip()
    if not 10 <= len(valor) <= 10000 or any(c in valor for c in ("\n", "\r", "\x00")):
        raise ValueError("Credencial inválida.")
    return Fernet(_chave()).encrypt(valor.encode()).decode()


def abrir(token_cifrado: str) -> SecretStr:
    try:
        return SecretStr(Fernet(_chave()).decrypt(token_cifrado.encode()).decode())
    except InvalidToken:
        raise ValueError("Não foi possível abrir a conexão. Conecte novamente.") from None
