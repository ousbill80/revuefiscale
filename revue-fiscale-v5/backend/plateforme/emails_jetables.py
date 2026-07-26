"""Rejet des emails jetables / temporaires à l'inscription."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_EMAIL_RE = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$", re.I)

# Domaines courants — complétés par data/disposable_email_domains.txt si présent.
_DOMAINES_BASE: frozenset[str] = frozenset(
    {
        "0-mail.com",
        "10minutemail.com",
        "10minutemail.net",
        "guerrillamail.com",
        "guerrillamail.net",
        "mailinator.com",
        "mailinator.net",
        "tempmail.com",
        "temp-mail.org",
        "temp-mail.io",
        "throwaway.email",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
        "trashmail.com",
        "trashmail.me",
        "getnada.com",
        "sharklasers.com",
        "grr.la",
        "guerrillamailblock.com",
        "pokemail.net",
        "spam4.me",
        "discard.email",
        "dispostable.com",
        "fakeinbox.com",
        "maildrop.cc",
        "mintemail.com",
        "mohmal.com",
        "mytemp.email",
        "tempail.com",
        "tmpmail.org",
        "tmpmail.net",
        "emailondeck.com",
        "getairmail.com",
        "inboxkitten.com",
        "mailnesia.com",
        "mailcatch.com",
        "mailnull.com",
        "spamgourmet.com",
        "jetable.org",
        "courrieltemporaire.com",
        "tempsky.com",
        "burnermail.io",
        "33mail.com",
        "anonymousemail.me",
        "tempinbox.com",
        "throwam.com",
        "trash-mail.com",
        "wegwerfmail.de",
        "wegwerfmail.net",
        "mailforspam.com",
        "spamfree24.org",
        "tempr.email",
        "emailfake.com",
        "crazymailing.com",
        "dropmail.me",
        "mailtemp.net",
        "tempmailo.com",
        "1secmail.com",
        "1secmail.org",
        "1secmail.net",
        "bccto.me",
        "chacuo.net",
        "discardmail.com",
        "dodgeit.com",
        "dontreg.com",
        "dumpmail.de",
        "e4ward.com",
        "emailias.com",
        "fakemail.fr",
        "filzmail.com",
        "getonemail.com",
        "gishpuppy.com",
        "great-host.in",
        "haltospam.com",
        "hide.biz.st",
        "incognitomail.org",
        "jetable.fr.nf",
        "kasmail.com",
        "klassmaster.com",
        "koszmail.pl",
        "kurzepost.de",
        "lifebyfood.com",
        "link2mail.net",
        "lroid.com",
        "mailbidon.com",
        "mailblocks.com",
        "mailexpire.com",
        "mailin8r.com",
        "mailimate.com",
        "mailmetrash.com",
        "mailmoat.com",
        "mailshell.com",
        "mailsiphon.com",
        "mailslapping.com",
        "mailzilla.com",
        "mbx.cc",
        "meltmail.com",
        "messagebeamer.de",
        "mierdamail.com",
        "msa.minsmail.com",
        "mt2009.com",
        "mx0.wwwnew.eu",
        "mycleaninbox.net",
        "nobulk.com",
        "noclickemail.com",
        "nogmailspam.info",
        "nomail.xl.cx",
        "nospam.ze.tc",
        "nospamfor.us",
        "nowmymail.com",
        "objectmail.com",
        "obobbo.com",
        "oneoffemail.com",
        "onewaymail.com",
        "ordinaryamerican.net",
        "owlpic.com",
        "pookmail.com",
        "proxymail.eu",
        "putthisinyourspamdatabase.com",
        "quickinbox.com",
        "rcpt.at",
        "reallymymail.com",
        "recode.me",
        "recursor.net",
        "regbypass.com",
        "safe-mail.net",
        "safetymail.info",
        "shiftmail.com",
        "shortmail.net",
        "sibmail.com",
        "skeefmail.com",
        "slaskpost.se",
        "smellfear.com",
        "snakemail.com",
        "sneakemail.com",
        "sofimail.com",
        "sogetthis.com",
        "soodonims.com",
        "spam.la",
        "spamavert.com",
        "spambob.com",
        "spambob.net",
        "spambog.com",
        "spambox.us",
        "spamcannon.com",
        "spamcero.com",
        "spamcon.org",
        "spamcorptastic.com",
        "spamday.com",
        "spamex.com",
        "spamfree.eu",
        "spamgoes.com",
        "spamherelots.com",
        "spamhole.com",
        "spamify.com",
        "spaml.com",
        "spammotel.com",
        "spamobox.com",
        "spamoff.de",
        "spamslicer.com",
        "spamspot.com",
        "spamthis.co.uk",
        "spamthisplease.com",
        "speed.1s.fr",
        "supergreatmail.com",
        "supermailer.jp",
        "suremail.info",
        "teewars.org",
        "teleworm.com",
        "tempalias.com",
        "temporarioemail.com.br",
        "tempthe.net",
        "thankyou2010.com",
        "thisisnotmyrealemail.com",
        "throwawayemailaddress.com",
        "tilien.com",
        "tmail.ws",
        "tmailinator.com",
        "tradermail.info",
        "trash2009.com",
        "trashdevil.com",
        "trashemail.de",
        "trashymail.com",
        "tyldd.com",
        "uggsrock.com",
        "wegwerfadresse.de",
        "wetrainbayarea.com",
        "wh4f.org",
        "whyspam.me",
        "willselfdestruct.com",
        "winemaven.info",
        "wronghead.com",
        "wuzup.net",
        "xoxy.net",
        "yogamaven.com",
        "yuurok.com",
        "zehnminuten.de",
        "zippymail.info",
        "zoemail.org",
    }
)


@lru_cache(maxsize=1)
def _domaines_jetables() -> frozenset[str]:
    domaines = set(_DOMAINES_BASE)
    chemin = Path(__file__).resolve().parent / "data" / "disposable_email_domains.txt"
    if chemin.is_file():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            d = ligne.strip().lower()
            if d and not d.startswith("#"):
                domaines.add(d)
    return frozenset(domaines)


def normaliser_email(email: str) -> str:
    return email.strip().lower()


def domaine_email(email: str) -> str | None:
    if "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].lower().strip()


def email_syntaxe_valide(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def est_email_jetable(email: str) -> bool:
    d = domaine_email(normaliser_email(email))
    if not d:
        return True
    if d in _domaines_jetables():
        return True
    # sous-domaine d'un domaine jetable connu
    parts = d.split(".")
    for i in range(len(parts) - 1):
        candidat = ".".join(parts[i:])
        if candidat in _domaines_jetables():
            return True
    return False


def valider_email_inscription(email: str) -> str:
    """Retourne l'email normalisé ou lève ValueError."""
    e = normaliser_email(email)
    if not email_syntaxe_valide(e):
        raise ValueError("email invalide")
    if est_email_jetable(e):
        raise ValueError(
            "Les adresses email temporaires ou jetables ne sont pas acceptées. "
            "Utilisez une adresse professionnelle durable."
        )
    return e
