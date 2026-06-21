"""Translate machine state + OEE into the 'AI Live Comments' line shown center-stage."""
import config


def comment(state, oee, ok, scrap, downtime_s, connected):
    if not connected:
        return "Connexion au cloud perdue..."
    if state is None:
        return "En attente de signal machine..."

    s = (state or "").upper()

    if "MACHINE_STOPPED" in s or "STOPPED" in s:
        if downtime_s and downtime_s > 300:
            return "Arret prolonge - intervention requise"
        if downtime_s and downtime_s > 60:
            return "Arret en cours - analyse Muda"
        return "Micro-arret detecte"

    if "RESTART" in s or "VALIDATION" in s:
        return "Reprise en cours - validation..."

    if "QC" in s:
        return "Controle qualite en cours"

    if "IDLE" in s:
        return "Machine en attente"

    # Normal production
    if oee >= config.OEE_EXCELLENT:
        return "Rythme de production excellent"
    if oee >= config.OEE_NORMAL:
        return "Rythme de production stable"
    if scrap and ok and (scrap / max(1, ok + scrap)) > 0.1:
        return "Qualite degradee - verifier le poste"
    return "Rythme a ameliorer"
