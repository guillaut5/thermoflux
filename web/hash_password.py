"""Calcule le hash a mettre dans WEB_PASSWORD_HASH.

Usage : docker run --rm -it thermoflux-web python hash_password.py
(le mot de passe est saisi au clavier, jamais passe en argument)
"""
import getpass
import sys

from auth import hash_password


def main():
    if sys.stdin.isatty():
        password = getpass.getpass("Mot de passe : ")
        if password != getpass.getpass("Confirmer    : "):
            sys.exit("Les deux saisies different.")
    else:
        # PowerShell ajoute un BOM UTF-8 devant ce qu'il envoie par tube : on l'ecarte
        password = sys.stdin.readline().lstrip("﻿").rstrip("\r\n")
    if len(password) < 8:
        sys.exit("Mot de passe trop court (8 caracteres minimum).")
    print(hash_password(password))


if __name__ == "__main__":
    main()
