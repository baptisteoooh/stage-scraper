"""Garde-fou commun à tous les tests : aucun accès à Internet (pas de vrai scrap, pas d'appel d'IA, pas de mail).

Un test qui oublie de remplacer une source par une fausse échoue tout de suite, au lieu d'interroger Careerjet,
Google, Gemini ou Gmail pour de vrai. Seuls les tests marqués `reseau` (lancés à la main, ex. GEMINI_REEL=1)
y ont droit.
"""
import imaplib
import smtplib

import httpx
import pytest
import requests


class ReseauInterdit(RuntimeError):
    """Un test a voulu sortir sur Internet."""


def _interdit(*args, **kwargs):
    raise ReseauInterdit("Accès à Internet interdit dans les tests : remplace la source ou le client par un faux.")


def pytest_configure(config):
    config.addinivalue_line("markers", "reseau: test qui parle vraiment à une API (lancé à la main seulement)")


@pytest.fixture(autouse=True)
def _pas_d_internet(request, monkeypatch):
    if request.node.get_closest_marker("reseau"):
        return
    monkeypatch.setattr(requests.sessions.Session, "request", _interdit)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _interdit)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _interdit)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _interdit)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _interdit)
    monkeypatch.setattr(smtplib, "SMTP", _interdit)
    # Les clés des IA de secours (ia.py) ne doivent pas venir du vrai .env : chaque test les pose s'il en a besoin.
    for nom in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "GROQ_API_KEY"):
        monkeypatch.delenv(nom, raising=False)
