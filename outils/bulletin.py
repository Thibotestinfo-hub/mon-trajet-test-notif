#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Le point d'entrée. Deux rendez-vous par jour.

    python3 bulletin.py --moment matin    # vers 8h00
    python3 bulletin.py --moment soir     # vers 18h00
    python3 bulletin.py --moment matin --simuler 1 --sans-git --sans-push

Il écrit web/message-<moment>.json (le bulletin) et web/horaires-<moment>.json
(les départs théoriques, pour le bouton « je pars »), publie sur GitHub Pages,
puis notifie — seulement s'il y a quelque chose à dire.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, date, time, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

import prim                                   # noqa: E402
import trajets as T                           # noqa: E402

# Où écrire, et où committer. Par défaut le sous-dossier web/ du projet ;
# dans la tâche planifiée, la racine du dépôt cloné.
WEB   = os.environ.get("SORTIE") or os.path.join(ICI, "web")
DEPOT = os.environ.get("DEPOT")  or ICI


# ─────────────────────────────────────────────────────────────────────────────
# Calcul
# ─────────────────────────────────────────────────────────────────────────────

def creneau(tr, jour=None):
    """Le créneau que le trajet peut occuper : du premier départ possible à
    l'arrivée du dernier. C'est sur lui qu'on teste les perturbations."""
    j = jour or date.today()
    t0 = datetime.combine(j, tr["plage"][0])
    t1 = datetime.combine(j, tr["plage"][1]) + timedelta(minutes=tr["duree_mn"] + 30)
    return t0, t1


def fenetres_marche(tr, jour=None):
    """Pour chaque portion à pied : où, et entre quelles heures j'y serai.

    La fenêtre couvre toute la plage de départ possible, pas un instant : si
    je peux partir entre 8h15 et 8h40, je traverse la passerelle entre 8h30 et
    8h55. C'est sur cet intervalle qu'il faut regarder la pluie.
    """
    j = jour or date.today()
    out, offset = [], 0
    for s in tr["segments"]:
        if s.get("coord"):
            t0 = (datetime.combine(j, tr["plage"][0])
                  + timedelta(minutes=offset)).time()
            t1 = (datetime.combine(j, tr["plage"][1])
                  + timedelta(minutes=offset + s["duree"])).time()
            out.append((s["nom"], s["coord"][0], s["coord"][1], t0, t1))
        offset += s["duree"]
    return out


def choisir_repli(tr, ligne, touchees):
    for opt in tr["replis"].get(ligne, []):
        if not any(d in touchees for d in opt["depend_de"]):
            return opt
    return None


def dernier_depart(tr, cible, retard_mn):
    """L'heure à laquelle il faut être parti pour arriver à `cible`."""
    if cible is None:
        return None
    d = datetime.combine(date.today(), cible) - timedelta(
        minutes=tr["duree_mn"] + max(0, retard_mn))
    return d.time()


def construire(tr, perturbs, meteos, passages, trou):
    p_lignes = set(perturbs)
    # La règle pluie porte sur la passerelle : c'est la seule marche longue
    # et découverte du parcours.
    seg_pluie = next((s for s in tr["segments"] if s.get("pluie")), None)
    mp = meteos.get(seg_pluie["nom"], {}) if seg_pluie else {}
    mm = mp.get("mm")
    il_pleut = mm is not None and mm >= T.PLUIE_SEUIL_MM

    lignes_touchees, L, detail = [], [], []
    retard, arbitrage, a_confirmer = 0, None, False

    # ── segments, pour l'affichage
    segments = []
    for s in tr["segments"]:
        etat = "ok"
        if s["ligne"] and s["ligne"] in p_lignes and perturbs[s["ligne"]]["direct"]:
            etat = "ko"
        elif s["ligne"] and s["ligne"] in p_lignes:
            etat = "amont"
        elif s.get("pluie") and il_pleut:
            etat = "pluie"
        seg = {"nom": s["nom"], "ligne": s["ligne"], "etat": etat,
               "duree": s["duree"],
               "couleur": T.COULEURS.get(s["ligne"], "#8a8f98")}
        if s["nom"] in meteos:
            seg["meteo"] = meteos[s["nom"]]
        segments.append(seg)

    # ── perturbations directes
    for s in tr["segments"]:
        lg = s["ligne"]
        if not lg or lg not in p_lignes or not perturbs[lg]["direct"]:
            continue
        lignes_touchees.append(lg)
        repli = choisir_repli(tr, lg, p_lignes)
        if repli:
            L.append(f"{lg} perturbé sur votre tronçon.")
            L.append(f"→ {repli['texte']}")
            retard = max(retard, repli["retard_mn"])
            a_confirmer |= repli.get("a_confirmer", False)
            # Un repli qui impose une longue marche n'a pas la même valeur
            # sous la pluie : on le dit plutôt que de le proposer sèchement.
            if il_pleut and repli.get("marche_mn", 0) >= 10:
                L.append(f"   {repli['marche_mn']} mn à pied sous la pluie : "
                         f"prenez un parapluie, ou patientez au bureau.")
        else:
            L.append(f"{lg} perturbé, et les alternatives le sont aussi.")
        detail += perturbs[lg]["direct"][:1]

    # ── perturbations en amont : on informe, on ne propose rien
    for lg, d in perturbs.items():
        if d["amont"] and lg not in lignes_touchees:
            L.append(f"{lg} : incident ailleurs sur la ligne. Votre gare n'est "
                     f"pas citée, mais votre train peut être retardé.")
            detail += d["amont"][:1]

    # ── second capteur : l'écart réel à l'arrêt d'embarquement
    if trou:
        L.append(f"À {tr['embarquement']['libelle']}, un trou de {trou} mn est "
                 f"annoncé entre deux passages.")

    # ── pluie
    rp = tr.get("repli_pluie")
    if il_pleut and rp:
        if L:
            L.append("")
        L.append(f"Pluie annoncée sur la passerelle : {mm:.1f} mm"
                 .replace(".", ",") + f", {mp.get('prob') or 0} % de risque.")
        if all(d not in p_lignes for d in rp["depend_de"]):
            L.append(f"→ {rp['texte']} {rp['reserve']}")
            arbitrage = rp["arbitrage"]
            retard = max(retard, rp["retard_mn"])
        else:
            L.append("→ le détour par le B n'est pas praticable aujourd'hui. "
                     "Prenez un parapluie.")
    elif il_pleut:
        L.append(f"Pluie annoncée sur la passerelle : {mm:.1f} mm".replace(".", ",") + ".")

    # ── l'heure de départ : c'est ça, la vraie réponse du matin
    departs = None
    if tr["arrivee_tard"]:
        confort = dernier_depart(tr, tr["arrivee_confort"], retard)
        tard    = dernier_depart(tr, tr["arrivee_tard"], retard)
        tot = tr["plage"][0]
        # Une heure de départ antérieure au début de la plage n'est pas une
        # consigne, c'est un objectif hors d'atteinte : on le dit.
        departs = {
            "confort": confort.strftime("%Hh%M") if confort and confort >= tot else None,
            "tard":    tard.strftime("%Hh%M") if tard and tard >= tot else None,
            "cible_confort": tr["arrivee_confort"].strftime("%Hh%M"),
            "cible_tard":    tr["arrivee_tard"].strftime("%Hh%M"),
            "confort_perdu": bool(confort and confort < tot),
            "intenable": bool(tard and tard < tot),
        }
        if departs["intenable"]:
            arr = (datetime.combine(date.today(), tot)
                   + timedelta(minutes=tr["duree_mn"] + retard)).strftime("%Hh%M")
            L.append(f"Même en partant à {tot.strftime('%Hh%M')}, arrivée vers {arr}.")

    if lignes_touchees:
        statut = "perturbe"
        titre = " et ".join(dict.fromkeys(lignes_touchees)) + " perturbé"
    elif any(d["amont"] for d in perturbs.values()):
        statut, titre = "amont", "Incident en amont"
    elif trou:
        statut, titre = "amont", "Passages espacés"
    elif il_pleut:
        statut, titre = "pluie", "Pluie sur la passerelle"
    else:
        statut, titre = "normal", "Trafic normal"

    return {
        "moment": tr["cle"],
        "libelle": tr["libelle"],
        "genere": datetime.now().astimezone().isoformat(timespec="seconds"),
        "plage": [tr["plage"][0].strftime("%Hh%M"), tr["plage"][1].strftime("%Hh%M")],
        "statut": statut,
        "titre": titre,
        "lignes": list(dict.fromkeys(lignes_touchees)),
        "message": "\n".join(L),
        "arbitrage": arbitrage,
        "a_confirmer": a_confirmer,
        "retard_mn": retard,
        "departs": departs,
        "pluie_mm": round(mm, 1) if mm is not None else None,
        "meteo_source": "Météo-France AROME 1,5 km, pas de 15 mn",
        "segments": segments,
        "detail": [d[:220] for d in detail],
        "prochains": [{"h": t.astimezone().strftime("%H:%M"), "dest": d}
                      for t, d in (passages or [])][:4],
        "notifier": statut != "normal",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Publication
# ─────────────────────────────────────────────────────────────────────────────

def publier(fichiers):
    def git(*a):
        return subprocess.run(["git", "-C", DEPOT, *a], capture_output=True, text=True)
    if git("rev-parse", "--git-dir").returncode != 0:
        print("[info] pas un dépôt git, publication sautée.")
        return False
    for f in fichiers:
        git("add", os.path.relpath(f, DEPOT))
    r = git("commit", "-m", "bulletin")
    if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
        print("[info] bulletin inchangé.")
        return True
    r = git("push")
    if r.returncode != 0:
        print(f"[avertissement] push échoué : {r.stderr.strip()[:200]}", file=sys.stderr)
        return False
    print("[info] publié.")
    return True


def pousser():
    import envoyer
    ck, ca = os.path.join(ICI, "cles_vapid.json"), os.path.join(ICI, "abonnements.json")
    if not (os.path.exists(ck) and os.path.exists(ca)):
        print("[info] pas d'abonnement, push sauté.")
        return
    c, A = json.load(open(ck)), json.load(open(ca))
    A = [A] if isinstance(A, dict) else A
    ok = sum(envoyer.notifier(a["endpoint"], c) in (200, 201, 202) for a in A)
    print(f"[info] {ok}/{len(A)} notification(s) envoyée(s).")


JEU_TEST = [
    ("Rien", {}, 0.0),
    ("RER C sur mon tronçon", {"RER C": {"direct": ["Trafic interrompu entre "
     "Austerlitz et Javel."], "amont": []}}, 0.0),
    ("RER C + son repli", {"RER C": {"direct": ["Interruption."], "amont": []},
                           "T2": {"direct": ["Interruption."], "amont": []}}, 0.0),
    ("Pluie seule", {}, 1.4),
    ("RER A + pluie", {"RER A": {"direct": ["Incident voyageur à Nation."],
                                 "amont": []}}, 2.0),
    ("Incident en amont seulement", {"RER C": {"direct": [], "amont":
     ["Trafic interrompu entre Juvisy et Brétigny."]}}, 0.0),
]


def main():
    a = sys.argv
    moment = a[a.index("--moment") + 1] if "--moment" in a else "matin"
    tr = T.TRAJETS[moment]
    t0, t1 = creneau(tr)
    emb = tr["embarquement"]

    def routes_de(e):
        if not e.get("routes_fichier"):
            return None
        f = os.path.join(ICI, e["routes_fichier"])
        return ([r["id"] for r in json.load(open(f))[e["routes_cle"]]]
                if os.path.exists(f) else None)

    if "--simuler" in a:
        titre, perturbs, mm = JEU_TEST[int(a[a.index("--simuler") + 1])]
        print(f"[simulation] {titre}")
        passages, trou = [], None
        seg = next((s for s in tr["segments"] if s.get("pluie")), None)
        meteos = {seg["nom"]: {"mm": mm, "prob": 80 if mm else 5, "temp": 12,
                               "vent": 14,
                               "picto": prim._picto(mm, 80 if mm else 5)}} if seg else {}
    else:
        perturbs = prim.perturbations(T.LIGNES, T.ARRETS, T.GRAVITES_RETENUES, t0, t1)
        meteos = prim.meteo(fenetres_marche(tr))
        passages = prim.passages_reels(emb["stop_area"], T.LIGNES[emb["ligne"]],
                                       emb.get("exclure_destinations", ()),
                                       routes_de(emb))
        trou = prim.ecart_anormal(passages, 10)

    b = construire(tr, perturbs, meteos, passages, trou)
    os.makedirs(WEB, exist_ok=True)
    f_msg = os.path.join(WEB, f"message-{moment}.json")
    json.dump(b, open(f_msg, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fichiers = [f_msg]
    # message.json reste le bulletin courant, pour la page d'accueil
    f_cur = os.path.join(WEB, "message.json")
    json.dump(b, open(f_cur, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fichiers.append(f_cur)

    # Horaires théoriques pour le bouton « je pars ». Les DEUX arrêts, sur
    # toute la journée de service : le bouton doit répondre à n'importe quelle
    # heure, pas seulement pendant la plage du trajet.
    if "--simuler" not in a:
        d0, d1 = T.HORAIRES_PLAGE
        arrets = {}
        for k, t in T.TRAJETS.items():
            e = t["embarquement"]
            h = prim.horaires_theoriques(e["stop_area"], T.LIGNES[e["ligne"]],
                                         date.today(), d0, d1, routes_de(e),
                                         e.get("exclure_destinations", ()))
            arrets[k] = {"libelle": e["libelle"], "ligne": e["ligne"],
                         "couleur": T.COULEURS.get(e["ligne"], "#8a8f98"),
                         "marche_mn": e["marche_mn"], "departs": h}
            print(f"[info] {len(h)} départ(s) à {e['libelle']}.")
        f_h = os.path.join(WEB, "horaires.json")
        json.dump({"genere": b["genere"], "jour": date.today().isoformat(),
                   "arrets": arrets},
                  open(f_h, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        fichiers.append(f_h)

    print(f"[info] {b['statut']} — {b['titre']}")
    if b["departs"]:
        print(f"[info] partir avant {b['departs']['confort']} pour "
              f"{b['departs']['cible_confort']}, "
              f"{b['departs']['tard']} pour {b['departs']['cible_tard']}")

    if "--sans-git" not in a:
        publier(fichiers)
    if b["notifier"] and "--sans-push" not in a:
        pousser()
    elif not b["notifier"]:
        print("[info] rien à signaler : pas de notification.")


if __name__ == "__main__":
    main()
