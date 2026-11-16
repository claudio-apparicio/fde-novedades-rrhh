"""Reproducibilidad y configuración del repositorio (devolución de la PE2). Correr con: pytest"""
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_gitignore_excluye_env():
    lineas = [l.strip() for l in (RAIZ / ".gitignore").read_text("utf-8").splitlines()]
    assert ".env" in lineas
    assert "indice/" in lineas and "modelos/" in lineas


def test_env_example_sin_valores():
    for l in (RAIZ / ".env.example").read_text("utf-8").splitlines():
        if l.strip() and not l.startswith("#"):
            nombre, _, valor = l.partition("=")
            assert valor == "", f"{nombre} tiene un valor en .env.example"


def test_env_example_documenta_todas_las_variables():
    usadas = set()
    for archivo in list((RAIZ / "src").rglob("*.py")) + list((RAIZ / "scripts").glob("*.py")):
        usadas |= set(re.findall(r'getenv\("([A-Z_]+)"', archivo.read_text("utf-8")))
    documentadas = set(re.findall(r"^([A-Z_]+)=", (RAIZ / ".env.example").read_text("utf-8"), re.M))
    assert usadas <= documentadas, usadas - documentadas


def test_readme_muestra_env_example_y_gitignore_exactos():
    readme = (RAIZ / "README.md").read_text("utf-8")
    for archivo in (".env.example", ".gitignore"):
        assert (RAIZ / archivo).read_text("utf-8").strip() in readme, f"el README no tiene {archivo} actualizado"


def test_catalogo_cubre_todos_los_documentos():
    cat = json.loads((RAIZ / "documentos/catalogo.json").read_text("utf-8"))
    archivos = {p.name for p in (RAIZ / "documentos").iterdir() if p.suffix in (".md", ".txt")}
    assert archivos == {d["archivo"] for d in cat["documentos"]}


def test_preguntas_de_prueba_6_2_2():
    preguntas = json.loads((RAIZ / "datos/preguntas_rag.json").read_text("utf-8"))["preguntas"]
    tipos = [p["tipo"] for p in preguntas]
    assert (tipos.count("normal"), tipos.count("sin_respuesta"), tipos.count("restringida")) == (6, 2, 2)
    codigos = {d["codigo"] for d in json.loads((RAIZ / "documentos/catalogo.json").read_text("utf-8"))["documentos"]}
    for p in preguntas:
        assert set(p["documentos_esperados"]) <= codigos
        if p["tipo"] == "sin_respuesta":
            assert p["documentos_esperados"] == []
