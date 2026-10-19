#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Envoi d'un Web Push, sans aucune dépendance hors `cryptography`.

Le push est envoyé SANS charge utile : il ne contient aucun texte, il réveille
seulement le service worker de la webapp, qui va lire message.json et afficher
la notification. C'est ce qui permet de se passer du chiffrement aes128gcm
(donc de pywebpush), et ça a un effet de bord utile : le message affiché est
toujours le dernier publié, même si le push a traîné en route.

    python3 envoyer.py             # notifie tous les abonnements
    python3 envoyer.py --verbeux
"""

import base64
import json
import os
import sys
import time as _time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils

ICI = os.path.dirname(os.path.abspath(__file__))
CLES = os.path.join(ICI, "cles_vapid.json")
ABOS = os.path.join(ICI, "abonnements.json")
CONTACT = os.environ.get("VAPID_CONTACT", "mailto:moi@example.org")


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt_vapid(origine, pem, duree_h=12):
    """JWT ES256 signé, au format attendu par les services de push."""
    sk = serialization.load_pem_private_key(pem.encode(), password=None)
    entete = b64(json.dumps({"typ": "JWT", "alg": "ES256"},
                            separators=(",", ":")).encode())
    corps = b64(json.dumps({"aud": origine,
                            "exp": int(_time.time()) + duree_h * 3600,
                            "sub": CONTACT},
                           separators=(",", ":")).encode())
    signe = f"{entete}.{corps}".encode()
    der = sk.sign(signe, ec.ECDSA(hashes.SHA256()))
    r, s = asym_utils.decode_dss_signature(der)      # DER → r||s brut (64 o.)
    brut = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{entete}.{corps}.{b64(brut)}"


def notifier(endpoint, cles, verbeux=False):
    o = urllib.parse.urlparse(endpoint)
    origine = f"{o.scheme}://{o.netloc}"
    entetes = {
        "Authorization": f"vapid t={jwt_vapid(origine, cles['privee_pem'])},"
                         f"k={cles['publique_b64url']}",
        # 45 mn de conservation chez Apple : si le téléphone est éteint ou hors
        # réseau à 8h00, la notification arrive à l'allumage. Ça ne coûte rien
        # en fraîcheur, puisque le push est vide et que la webapp va chercher
        # le bulletin au moment où elle se réveille.
        "TTL": "2700",
        "Urgency": "high",
        "Content-Length": "0",
    }
    req = urllib.request.Request(endpoint, data=b"", headers=entetes, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if verbeux:
                print(f"  {r.status} {o.netloc}")
            return r.status
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", "replace")[:200]
        print(f"  ÉCHEC {e.code} {o.netloc} : {corps}", file=sys.stderr)
        if e.code in (404, 410):
            print("  → abonnement périmé (webapp désinstallée ?). "
                  "À retirer d'abonnements.json.", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"  ÉCHEC {o.netloc} : {e}", file=sys.stderr)
        return 0


def main():
    if not os.path.exists(CLES):
        sys.exit("cles_vapid.json absent : lancez `python3 vapid.py`.")
    if not os.path.exists(ABOS):
        sys.exit("abonnements.json absent : ouvrez la webapp sur l'iPhone, "
                 "activez les notifications, copiez l'abonnement affiché.")
    cles = json.load(open(CLES))
    abos = json.load(open(ABOS))
    if isinstance(abos, dict):
        abos = [abos]
    verbeux = "--verbeux" in sys.argv
    ok = 0
    for a in abos:
        ep = a.get("endpoint") if isinstance(a, dict) else a
        if not ep:
            continue
        if notifier(ep, cles, verbeux) in (200, 201, 202):
            ok += 1
    print(f"{ok}/{len(abos)} notification(s) envoyée(s).")


if __name__ == "__main__":
    main()
