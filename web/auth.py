"""Hachage et verification de mot de passe (scrypt, bibliotheque standard).

Format stocke : scrypt:N:r:p:sel_hex:hash_hex
Ce format n'a ni '$' ni espace : il survit tel quel dans un .env, un
`docker run -e` ou un fichier compose (un '$' y serait interprete).
"""
import hashlib
import hmac
import os

# Parametres OWASP pour scrypt : N=2^16, r=8, p=2 (~64 Mio de memoire)
N, R, P = 2 ** 16, 8, 2
MAXMEM = 256 * 1024 * 1024
DKLEN = 32


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=N, r=R, p=P, maxmem=MAXMEM, dklen=DKLEN
    )
    return "scrypt:%d:%d:%d:%s:%s" % (N, R, P, salt.hex(), digest.hex())


def verify_password(password, stored):
    """True si le mot de passe correspond au hash stocke (comparaison a temps constant)."""
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split(":")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        got = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
            maxmem=MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)
