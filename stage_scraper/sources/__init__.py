"""Modules de collecte : un fichier par source (france_travail.py, adzuna.py, ...).

Chaque module expose une fonction `collecter(config) -> list[dict]` qui renvoie
les offres normalisées. Une source qui plante ne doit jamais bloquer les autres :
c'est run.py qui attrape les erreurs et les écrit dans le journal (table runs).
"""
