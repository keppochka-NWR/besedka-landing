# -*- coding: utf-8 -*-
"""Builds artifact.html — the landing prepared for hosting as a Claude Artifact.

Differences from preview.html, all forced by the Artifact sandbox:
  * no doctype / html / head / body wrappers (the platform adds them)
  * Google Fonts links replaced by inlined @font-face data URIs, because the
    Artifact CSP blocks external hosts and the page would silently lose its type
  * page background pinned on the root so the viewer's light theme cannot
    show through as white gaps around a deliberately dark design

Run: py -3 build_artifact.py
"""
import os
import re

DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(DIR, "preview.html")
OUT = os.path.join(DIR, "artifact.html")
FONTS = r"C:\besedka_ai\fonts\fonts_inline.css"

with open(SRC, "r", encoding="utf-8") as fh:
    html = fh.read()

with open(FONTS, "r", encoding="utf-8") as fh:
    faces = fh.read().strip()

# внешние шрифты -> встроенные
html = re.sub(r'<link rel="preconnect"[^>]*>\s*', "", html)
html = re.sub(
    r'<link href="https://fonts\.googleapis\.com[^"]*" rel="stylesheet">',
    "<style>\n" + faces + "\n</style>",
    html,
)
assert "fonts.googleapis.com" not in html, "остался внешний запрос к шрифтам"
assert "fonts.gstatic.com" not in html, "остался внешний запрос к шрифтам"

# снимаем обёртку документа
html = re.sub(r"^\s*<!DOCTYPE html>\s*", "", html, flags=re.I)
html = re.sub(r"<html[^>]*>\s*", "", html, count=1, flags=re.I)
html = re.sub(r"\s*</html>\s*$", "", html, flags=re.I)
html = re.sub(r"<head>\s*", "", html, count=1, flags=re.I)
html = re.sub(r"\s*</head>\s*", "\n", html, count=1, flags=re.I)
html = re.sub(r"<body>\s*", "", html, count=1, flags=re.I)
html = re.sub(r"\s*</body>\s*", "\n", html, count=1, flags=re.I)
for tag in ("<html", "</html>", "<head>", "</head>", "<body>", "</body>", "<!DOCTYPE"):
    assert tag.lower() not in html.lower(), "осталась обёртка документа: %s" % tag

# страница намеренно тёмная: не даём светлой теме просвечивать по краям
html = html.replace(
    "  *{margin:0;padding:0;box-sizing:border-box}",
    "  :root{background:#141311;color-scheme:dark}\n"
    "  *{margin:0;padding:0;box-sizing:border-box}",
    1,
)

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(html)

size = os.path.getsize(OUT) / 1024 / 1024
print("artifact.html: %.2f MB" % size)
print("title:", (re.search(r"<title>(.*?)</title>", html) or ["", "нет"])[1])
print("inlined @font-face:", html.count("@font-face"))
print("external hosts:", "нет" if "https://fonts." not in html else "ЕСТЬ")
assert size < 16, "превышен лимит 16 МБ"
