#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
La description des deux trajets. C'est le seul fichier à modifier pour régler
le dispositif : tout le reste est de la mécanique.

Principe maintenu : les REPLIS ne sont pas calculés, ils sont écrits. Ils
viennent de la connaissance du terrain, pas d'un graphe. Le calculateur IDFM
sert à donner les HORAIRES d'un trajet choisi, jamais à CHOISIR le trajet —
interrogé sans contrainte, il propose M13, M12 et le bus 42.
"""

from datetime import time

# ─────────────────────────────────────────────────────────────────────────────
# Lignes et gares
# ─────────────────────────────────────────────────────────────────────────────

LIGNES = {
    "RER A": "line:IDFM:C01742",
    "RER B": "line:IDFM:C01743",
    "RER C": "line:IDFM:C01727",
    "M1":    "line:IDFM:C01371",
    "M12":   "line:IDFM:C01382",
    "T2":    "line:IDFM:C01390",
}

GRAVITES_RETENUES = {"BLOQUANTE", "PERTURBEE"}

# Les gares réellement empruntées, ligne par ligne. Filtre décisif : le RER C
# déclare en permanence une trentaine de perturbations, presque toutes des
# travaux de nuit en Essonne. Sans ce filtre, la ligne est « perturbée » tous
# les jours de l'année et l'alerte ne vaut plus rien.
ARRETS = {
    "RER A": ["Vincennes", "Nation", "Gare de Lyon"],
    "RER B": ["Chatelet", "Saint-Michel"],
    "RER C": ["Austerlitz", "Saint-Michel", "Musee d'Orsay", "Invalides",
              "Pont de l'Alma", "Champ de Mars", "Javel", "Garigliano", "Issy"],
    "M1":    ["Berault", "Saint-Mande", "Porte de Vincennes", "Nation",
              "Reuilly", "Gare de Lyon"],
    "M12":   ["Mairie d'Issy", "Corentin Celton", "Concorde"],
    "T2":    ["Issy", "Brimborion", "Musee de Sevres"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Marches à pied, en minutes (relevés Maps)
# ─────────────────────────────────────────────────────────────────────────────

MARCHE = {
    "domicile→Vincennes RER": 5,
    "domicile→Bérault M1":    8,
    "Issy→bureau":            6,     # 400 m
    "bureau→Issy":            6,
    "passerelle":            10,     # Gare de Lyon ↔ Austerlitz
}

# ─────────────────────────────────────────────────────────────────────────────
# Les deux trajets
# ─────────────────────────────────────────────────────────────────────────────

MATIN = {
    "cle": "matin",
    "libelle": "Domicile → Bureau",
    # Plage de DÉPART du domicile. C'est elle qui change la nature du message :
    # la question n'est plus « quel est l'impact ? » mais « quand partir ? ».
    "plage": (time(8, 15), time(8, 40)),
    "arrivee_confort": time(9, 15),
    "arrivee_tard":    time(9, 30),
    "duree_mn": 52,                  # porte à porte, calibré sur les horaires IDFM
    # L'arrêt où l'on monte : sert au bouton « je pars » et au second capteur.
    "embarquement": {
        "libelle": "Vincennes RER",
        "ligne": "RER A",
        "stop_area": "stop_area:IDFM:71651",
        "marche_mn": 5,
        # Vers Paris = tout sauf les deux branches de l'est.
        "exclure_destinations": ["Boissy", "Marne-la-Vallée", "Torcy",
                                 "Chessy", "Val d'Europe", "Noisy"],
    },
    "segments": [
        {"nom": "Marche jusqu'à Vincennes RER", "ligne": None, "duree": 5,
         "coord": (48.8475, 2.4344)},
        {"nom": "Vincennes → Gare de Lyon",     "ligne": "RER A", "duree": 10},
        {"nom": "Passerelle Charles-de-Gaulle", "ligne": None, "duree": 10,
         "pluie": True, "coord": (48.8465, 2.3660)},
        {"nom": "Austerlitz → Issy-Val-de-Seine", "ligne": "RER C", "duree": 19},
        {"nom": "Marche jusqu'au bureau",        "ligne": None, "duree": 6,
         "coord": (48.8268, 2.2731)},
    ],
    "replis": {
        "RER A": [{"texte": "M1 à Bérault (8 mn à pied) jusqu'à Gare de Lyon",
                   "depend_de": ["M1"], "retard_mn": 8}],
        "RER C": [{"texte": "T2 jusqu'à Issy-Val-de-Seine",
                   "depend_de": ["T2"], "retard_mn": 10},
                  {"texte": "M12 jusqu'à Mairie d'Issy ou Corentin Celton, puis 8 mn à pied",
                   "depend_de": ["M12"], "retard_mn": 12}],
    },
    "repli_pluie": {
        "texte": "RER A poussée jusqu'à Châtelet, RER B jusqu'à Saint-Michel-"
                 "Notre-Dame, puis RER C. La passerelle est évitée.",
        "depend_de": ["RER A", "RER B"],
        "retard_mn": -6,             # plus rapide, en fait : voir le README
        "reserve": "Le B est bondé quand il pleut.",
        "arbitrage": "10 mn sous la pluie, ou un B chargé.",
    },
}

SOIR = {
    "cle": "soir",
    "libelle": "Bureau → Domicile",
    # Plage plus large : le départ dépend de la fin de journée, pas d'un horaire.
    "plage": (time(18, 15), time(19, 45)),
    "arrivee_confort": None,         # aucune contrainte d'arrivée le soir
    "arrivee_tard": None,
    "duree_mn": 51,
    "embarquement": {
        "libelle": "Issy-Val-de-Seine",
        "ligne": "RER C",
        "stop_area": "stop_area:IDFM:71016",
        "marche_mn": 6,
        # Le sens se résout par les routes, pas par les destinations :
        # voir sens.json, construit par horaires.py.
        "routes_fichier": "sens.json",
        "routes_cle": "Issy->Austerlitz",
    },
    "segments": [
        {"nom": "Marche jusqu'à Issy-Val-de-Seine", "ligne": None, "duree": 6,
         "coord": (48.8268, 2.2731)},
        {"nom": "Issy-Val-de-Seine → Austerlitz",   "ligne": "RER C", "duree": 19},
        {"nom": "Passerelle Charles-de-Gaulle",     "ligne": None, "duree": 10,
         "pluie": True, "coord": (48.8465, 2.3660)},
        {"nom": "Gare de Lyon → Vincennes",         "ligne": "RER A", "duree": 11},
        {"nom": "Marche jusqu'au domicile",         "ligne": None, "duree": 5,
         "coord": (48.8475, 2.4344)},
    ],
    "replis": {
        # Repli réel. La marche de 15 mn jusqu'à Mairie d'Issy est le point
        # dur : c'est elle qui coûte, pas le métro. Sous la pluie, elle change
        # complètement la valeur de ce repli.
        "RER C": [{"texte": "15 mn à pied jusqu'à Mairie d'Issy, M12 jusqu'à "
                            "Saint-Lazare, puis RER A jusqu'à Vincennes",
                   "depend_de": ["M12", "RER A"], "retard_mn": 10,
                   "marche_mn": 15}],
        "RER A": [{"texte": "M1 depuis Gare de Lyon jusqu'à Bérault, "
                            "puis 8 mn à pied",
                   "depend_de": ["M1"], "retard_mn": 8, "a_confirmer": True}],
    },
    "repli_pluie": None,             # la passerelle le soir : à voir avec vous
}

TRAJETS = {"matin": MATIN, "soir": SOIR}

# Le bouton « je pars » couvre toute la journée de service, pas seulement la
# plage du trajet : sinon il répond « plus de départ prévu » le reste du temps.
HORAIRES_PLAGE = (time(5, 0), time(1, 0))

PLUIE_SEUIL_MM = 0.3
COULEURS = {"RER A": "#E2231A", "RER B": "#5291CE", "RER C": "#FFCE00",
            "M1": "#FFCD00", "M12": "#007852", "T2": "#CF009E"}
