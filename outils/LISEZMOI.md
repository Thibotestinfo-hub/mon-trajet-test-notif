# Outils de la veille

Exécutés par une tâche planifiée, deux fois par jour.

    SORTIE=<racine du dépôt> DEPOT=<racine du dépôt> \
      python3 outils/bulletin.py --moment matin

Trois fichiers de secrets sont attendus à côté de `bulletin.py` et ne sont
**jamais** versionnés — la tâche les écrit au début de chaque exécution :

| | |
|---|---|
| `cle_prim.txt` | le jeton PRIM |
| `cles_vapid.json` | la paire de clés de signature du push |
| `abonnements.json` | l'abonnement push de l'iPhone |

`trajets.py` est le seul fichier à modifier pour régler le dispositif.
