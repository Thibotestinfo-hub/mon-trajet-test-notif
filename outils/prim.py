#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Accès à PRIM : perturbations, temps réel, horaires théoriques, météo."""

import html
import json
import os
import re
import sys
import time as _time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta

M = "https://prim.iledefrance-mobilites.fr/marketplace"
NAV = M + "/v2/navitia"
ICI = os.path.dirname(os.path.abspath(__file__))


def cle():
    c = os.environ.get("PRIM_KEY", "").strip()
    if c:
        return c
    f = os.path.join(ICI, "cle_prim.txt")
    return open(f, encoding="utf-8").read().strip() if os.path.exists(f) else ""


def get(url, avec_cle=True, timeout=25, essais=4, attente=3):
    """GET JSON, avec quelques tentatives : la tâche tourne sans surveillance.

    L'attente croît vite : Open-Meteo limite le débit par adresse, et un
    deuxième essai immédiat se fait rejeter de la même façon.
    """
    e = {"apiKey": cle()} if avec_cle else {}
    req = urllib.request.Request(url, headers=e)
    for n in range(essais):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if n == essais - 1:
                raise
            _time.sleep(attente * (2 ** n))


# ─── utilitaires de texte ────────────────────────────────────────────────────

def sans_html(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def pliage(s):
    """Minuscules, sans accents ni ponctuation — pour comparer des noms de gare."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def horo(s):
    """'20261016T050600' → datetime."""
    return datetime.strptime(s, "%Y%m%dT%H%M%S")


# ─── 1. perturbations ────────────────────────────────────────────────────────

_GARES = None


def gares_de(ligne):
    global _GARES
    if _GARES is None:
        f = os.path.join(ICI, "arrets_lignes.json")
        _GARES = json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {}
    return _GARES.get(ligne, [])


def _touche(p, arrets_vus, ligne, mes_arrets):
    """La perturbation touche-t-elle une gare empruntée ?

    Quatre cas, du plus fiable au plus bricolé : tronçons déclarés ; arrêts
    déclarés ; noms de gares lus dans le texte (fréquent : beaucoup de travaux
    ne déclarent ni l'un ni l'autre) ; rien du tout → ligne entière, on garde.
    """
    mes = [pliage(a) for a in mes_arrets]
    ok = lambda nom: any(m in pliage(nom) for m in mes)

    sections = p.get("impactedSections") or []
    if sections:
        return any(ok(s[b]["name"]) for s in sections for b in ("from", "to"))
    if arrets_vus:
        return any(ok(n) for n in arrets_vus)
    texte = pliage(f"{p.get('title','')} {sans_html(p.get('message'))}")
    citees = [g for g in gares_de(ligne) if pliage(g) in texte]
    return any(ok(g) for g in citees) if citees else True


def perturbations(lignes, arrets, gravites, t0, t1):
    """Un seul appel pour tout le réseau.

    Rend {ligne: {"direct": [...], "amont": [...]}}.
      direct — touche une gare empruntée. Déclenche un repli.
      amont  — bloquante ailleurs sur la ligne. Peut retarder le train par
               propagation, sans que la gare soit nommée. On informe, sans
               proposer de repli.
    """
    try:
        d = get(f"{M}/disruptions_bulk/disruptions/v2", timeout=45)
    except Exception as e:
        print(f"[avertissement] PRIM injoignable : {e}", file=sys.stderr)
        return {}

    par_id = {x["id"]: x for x in d.get("disruptions", [])}
    index, vus = {}, {}
    for l in d.get("lines", []):
        for o in l.get("impactedObjects", []) or []:
            dids = o.get("disruptionIds") or []
            if o.get("type") == "line":
                index.setdefault(o["id"], set()).update(dids)
            elif o.get("type") in ("stop_point", "stop_area"):
                for did in dids:
                    vus.setdefault(did, set()).add(o.get("name") or "")

    out = {}
    for nom, lid in lignes.items():
        direct, amont = [], []
        for did in index.get(lid, ()):
            p = par_id.get(did)
            if not p or p.get("severity") not in gravites:
                continue
            if not any(horo(a["begin"]) <= t1 and horo(a["end"]) >= t0
                       for a in p.get("applicationPeriods", []) or []):
                continue
            txt = sans_html(p.get("message") or p.get("title"))
            if _touche(p, vus.get(did, set()), nom, arrets[nom]):
                direct.append(txt)
            elif p.get("severity") == "BLOQUANTE":
                amont.append(txt)
        if direct or amont:
            out[nom] = {"direct": direct, "amont": amont}
    return out


# ─── 2. temps réel : le second capteur ───────────────────────────────────────

def passages_reels(stop_area, ligne_id, exclure=(), routes=None, limite=6):
    """Prochains passages réels à un arrêt, dans le bon sens. [(datetime, destination)]"""
    ref = "STIF:StopArea:SP:" + stop_area.split(":")[-1] + ":"
    try:
        d = get(f"{M}/stop-monitoring?MonitoringRef={urllib.parse.quote(ref)}")
        v = d["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"][0] \
             .get("MonitoredStopVisit", []) or []
    except Exception as e:
        print(f"[avertissement] temps réel indisponible : {e}", file=sys.stderr)
        return []
    code = ligne_id.split(":")[-1]
    out = []
    for x in v:
        j = x.get("MonitoredVehicleJourney", {})
        if code not in (j.get("LineRef", {}) or {}).get("value", ""):
            continue
        c = j.get("MonitoredCall", {}) or {}
        t = c.get("ExpectedDepartureTime") or c.get("AimedDepartureTime")
        if not t:
            continue
        dest = ((j.get("DestinationName") or [{}])[0] or {}).get("value", "")
        if any(pliage(e) in pliage(dest) for e in exclure):
            continue
        out.append((datetime.fromisoformat(t.replace("Z", "+00:00")), dest))
    out.sort()
    return out[:limite]


def ecart_anormal(passages, attendu_mn):
    """Le premier trou dépasse-t-il nettement l'intervalle habituel ?

    C'est la mesure qui rattrape l'angle mort du filtre géographique : un
    incident en début de ligne ne nomme pas ma gare, mais il s'y voit.
    """
    if len(passages) < 2:
        return None
    trous = [round((passages[i + 1][0] - passages[i][0]).total_seconds() / 60)
             for i in range(len(passages) - 1)]
    pire = max(trous)
    return pire if pire >= attendu_mn * 2 else None


# ─── 3. horaires théoriques (pour le bouton « je pars ») ─────────────────────

def horaires_theoriques(stop_area, ligne_id, jour, debut, fin,
                        routes=None, exclure=()):
    """Départs théoriques à un arrêt, dans le bon sens, sur un créneau.

    Couvre volontairement toute la journée de service : un bouton « je pars »
    qui ne répond que sur une plage de deux heures annonce « plus de départ
    prévu » le reste du temps, ce qui est faux et déroutant.
    """
    total = (fin.hour * 60 + fin.minute) - (debut.hour * 60 + debut.minute)
    if total <= 0:
        total += 24 * 60

    # L'API plafonne le nombre de départs rendus par appel : une seule requête
    # sur vingt heures s'arrête vers le début d'après-midi. On découpe.
    TRANCHE = 240          # 4 h
    vus = {}
    depart0 = datetime.combine(jour, debut)
    for off in range(0, total, TRANCHE):
        t = depart0 + timedelta(minutes=off)
        duree = min(TRANCHE, total - off) * 60
        q = (f"from_datetime={t:%Y%m%dT%H%M%S}&duration={duree}"
             f"&count=200&data_freshness=base_schedule")
        urls = ([f"{NAV}/routes/{r}/stop_areas/{stop_area}/departures?{q}"
                 for r in routes] if routes else
                [f"{NAV}/stop_areas/{stop_area}/lines/{ligne_id}/departures?{q}"])
        for u in urls:
            try:
                d = get(u, timeout=40)
            except Exception as e:
                print(f"[avertissement] horaires : {e}", file=sys.stderr)
                continue
            for x in d.get("departures", []):
                dt_ = x["stop_date_time"]["departure_date_time"]
                dest = x["display_informations"].get("direction", "")
                if any(pliage(e) in pliage(dest) for e in exclure):
                    continue
                vus[dt_] = re.sub(r"\s*\([^)]*\)\s*$", "", dest)
    return [{"h": k[9:11] + ":" + k[11:13], "dest": v}
            for k, v in sorted(vus.items())]


# ─── 4. météo ────────────────────────────────────────────────────────────────

OM = "https://api.open-meteo.com/v1/forecast"


def _picto(mm, prob):
    """Du plus sec au plus mouillé. C'est le risque de pluie qui décide, pas
    la couverture nuageuse : marcher sous un ciel gris ne dérange personne."""
    if mm >= 1.0:
        return "averse"
    if mm >= 0.2:
        return "pluie"
    if (prob or 0) >= 50:
        return "risque"
    if (prob or 0) >= 25:
        return "nuage"
    return "soleil"


def meteo(points, jour=None):
    """Météo fine sur plusieurs points du parcours, en deux appels.

    points : [(nom, lat, lon, heure_debut, heure_fin)]
    Rend {nom: {mm, prob, temp, vent, picto}}.

    La quantité vient d'AROME haute définition (maille 1,5 km, pas de 15 mn),
    qui est le plus fin disponible sans compte. AROME ne publie pas de
    probabilité : celle-ci vient du modèle combiné, au pas horaire.
    """
    if not points:
        return {}
    j = jour or date.today()
    lats = ",".join(f"{p[1]}" for p in points)
    lons = ",".join(f"{p[2]}" for p in points)
    base = f"{OM}?latitude={lats}&longitude={lons}&timezone=Europe%2FParis&forecast_days=2"

    def liste(d):
        return d if isinstance(d, list) else [d]

    try:
        fin = liste(get(base + "&minutely_15=precipitation,temperature_2m,"
                               "wind_speed_10m&models=meteofrance_arome_france_hd",
                        avec_cle=False, timeout=35, essais=5, attente=6))
    except Exception as e:
        print(f"[avertissement] météo fine injoignable : {e}", file=sys.stderr)
        return {}
    try:
        _time.sleep(2)
        gros = liste(get(base + "&hourly=precipitation_probability",
                         avec_cle=False, timeout=35, essais=5, attente=6))
    except Exception as e:
        print(f"[avertissement] probabilités indisponibles : {e}", file=sys.stderr)
        gros = [None] * len(fin)

    out = {}
    for (nom, _, _, h0, h1), f, g_ in zip(points, fin, gros):
        m = f["minutely_15"]
        t0 = datetime.combine(j, h0)
        t1 = datetime.combine(j, h1)
        mm, temps, vents = 0.0, [], []
        for i, iso in enumerate(m["time"]):
            t = datetime.fromisoformat(iso)
            if not (t0 <= t <= t1):
                continue
            mm += m["precipitation"][i] or 0.0
            if m["temperature_2m"][i] is not None:
                temps.append(m["temperature_2m"][i])
            if m["wind_speed_10m"][i] is not None:
                vents.append(m["wind_speed_10m"][i])
        prob = None
        if g_:
            h = g_["hourly"]
            vals = [h["precipitation_probability"][i]
                    for i, iso in enumerate(h["time"])
                    if t0.hour <= datetime.fromisoformat(iso).hour <= t1.hour
                    and h["precipitation_probability"][i] is not None]
            prob = max(vals) if vals else None
        out[nom] = {
            "mm": round(mm, 2),
            "prob": prob,
            "temp": round(sum(temps) / len(temps)) if temps else None,
            "vent": round(max(vents)) if vents else None,
            "picto": _picto(mm, prob),
        }
    return out
