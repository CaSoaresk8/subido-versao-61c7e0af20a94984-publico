import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_senha(senha: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(senha.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${salt.hex()}${dk.hex()}"


def conferir_senha(senha: str, armazenado: str) -> bool:
    try:
        algo, salt_hex, hash_hex = armazenado.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    dk = hashlib.scrypt(
        senha.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return hmac.compare_digest(dk.hex(), hash_hex)
