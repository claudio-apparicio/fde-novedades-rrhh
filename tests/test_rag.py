"""Ingesta, fragmentado, búsqueda híbrida y respuesta con fuentes. Correr con: pytest"""
import json
import re
import shutil
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.contrato import PATRON_FRAGMENTO, EstadoNovedad, Salida
from src.motor import Motor
from src.proveedores import ProveedorSimulado
from src.rag.busqueda import fusionar_rrf, tokenizar
from src.rag.documentos import (CONFIGS_FRAGMENTADO, DIR_DOCUMENTOS, cargar_documentos, dividir_secciones,
                                fragmentar, limpiar)
from src.rag.permisos import obtener_usuario
from src.rag.responder import responder
from src.contrato import Entrada

RECIBIDA = datetime(2026, 11, 16, 10)


# --- Limpieza y secciones ------------------------------------------------------------
def test_limpieza_quita_pies_encabezados_y_guiones():
    crudo = (DIR_DOCUMENTOS / "CCT-05_resumen_convenio_lct.txt").read_text("utf-8")
    limpio = limpiar(crudo)
    assert "Página" not in limpio and "No reemplaza el texto oficial" not in limpio
    assert "siguiente" in limpio and "si-\nguiente" not in limpio


def test_secciones_de_txt_numeradas():
    _, secciones = dividir_secciones(limpiar("1. JORNADA DE TRABAJO\n\nOcho horas.\n\n2. HORAS EXTRAS\n\nRecargo."), ".txt")
    assert [t for t, _ in secciones] == ["1. Jornada de trabajo", "2. Horas extras"]


def test_catalogo_deniega_archivos_no_listados(tmp_path, caplog):
    shutil.copytree(DIR_DOCUMENTOS, tmp_path / "docs")
    (tmp_path / "docs" / "secreto.md").write_text("# Secreto\n\n## 1. Sueldos\n\nTodo.", encoding="utf-8")
    docs = cargar_documentos(tmp_path / "docs")
    assert "secreto.md" not in {d.archivo for d in docs}
    assert "no está en el catálogo" in caplog.text


def test_una_seccion_no_puede_ampliar_roles(tmp_path):
    shutil.copytree(DIR_DOCUMENTOS, tmp_path / "docs")
    ruta = tmp_path / "docs" / "catalogo.json"
    cat = json.loads(ruta.read_text("utf-8"))
    cat["documentos"][2]["secciones"]["5. Excepciones autorizadas por gerencia"] = ["empleado"]
    ruta.write_text(json.dumps(cat), encoding="utf-8")
    with pytest.raises(ValueError, match="ampliar"):
        cargar_documentos(tmp_path / "docs")


# --- Fragmentado ------------------------------------------------------------------------
@pytest.mark.parametrize("config", list(CONFIGS_FRAGMENTADO))
def test_fragmentos_no_cruzan_secciones_ni_pasan_el_maximo(config):
    maximo = CONFIGS_FRAGMENTADO[config]["max_caracteres"]
    for doc in cargar_documentos():
        secciones = {s.titulo: re.sub(r"\s+", " ", s.texto) for s in doc.secciones}
        for f in fragmentar(doc, config):
            assert re.fullmatch(PATRON_FRAGMENTO, f.id)
            assert len(f.texto) <= maximo
            assert re.sub(r"\s+", " ", f.texto) in secciones[f.seccion]   # sale de una sola sección
            meta = f.metadatos()
            assert {"documento", "seccion", "roles"} <= set(meta)
            assert all(meta[f"rol_{r}"] for r in f.roles)


# --- Búsqueda ---------------------------------------------------------------------------
def test_tokenizar_conserva_codigos():
    assert {"he100", "f-12", "19.032", "exc-2026-03"} <= set(tokenizar("HE100, F-12, Ley 19.032, EXC-2026-03"))
    assert tokenizar("Conceptos de licencias") == ["concepto", "licencia"]


def test_rrf_premia_lo_que_aparece_en_los_dos_rankings():
    p = fusionar_rrf(["a", "b", "c"], ["c", "d"])
    assert max(p, key=p.get) == "c"


def test_con_codigo_bm25_pesa_doble():
    from src.rag.busqueda import peso_bm25
    assert peso_bm25("¿Qué es el concepto 1035?") == 2.0 and peso_bm25("planilla F-07") == 2.0
    assert peso_bm25("¿cuántos días por casamiento?") == 1.0
    p = fusionar_rrf(["a", "b"], ["b", "a"], pesos=(1.0, 2.0))
    assert max(p, key=p.get) == "b"


def test_buscar_devuelve_el_contrato(buscador):
    r = buscador.buscar("¿Qué código uso para horas extras al 100 %?", obtener_usuario("SUP-003"), k=3)
    assert 0 < len(r) <= 3
    assert all(f.documento and f.fragmento_id and f.texto and f.puntaje > 0 for f in r)
    assert [f.puntaje for f in r] == sorted((f.puntaje for f in r), reverse=True)


def test_hibrida_encuentra_codigo_exacto(buscador):
    r = buscador.buscar("HE100", obtener_usuario("SUP-003"), k=3, modo="hibrida")
    assert any("HE100" in f.texto for f in r)


# --- Respuesta con fuentes ----------------------------------------------------------------
def _entrada(mensaje, usuario="EMP-1091"):
    u = obtener_usuario(usuario)
    return Entrada(supervisor_id=u.id, sector=u.sector, canal="chat_web", recibida_en=RECIBIDA, mensaje=mensaje)


def _consulta(citas, texto="El concepto 1035 es el premio por asistencia (presentismo)."):
    return json.dumps({**ProveedorSimulado.SIN_DATOS, "categoria": "consulta", "confianza": 0.9,
                       "respuesta_supervisor": texto, "citas": citas})


def test_respuesta_con_fuentes(buscador):
    entrada = _entrada("¿Qué es el concepto 1035 de mi recibo?")
    ids = [f.fragmento_id for f in buscador.buscar(entrada.mensaje, obtener_usuario("EMP-1091"), k=5)]
    r = responder(entrada, buscador=buscador, motor=Motor(ProveedorSimulado([_consulta([ids[0]])])))
    assert r.ok and not r.requiere_humano and r.estado == EstadoNovedad.RESPONDIDA
    assert [f.fragmento_id for f in r.fuentes] == [ids[0]] and r.fuentes[0].documento == ids[0].split("#")[0]


def test_cita_inventada_se_rechaza_y_se_reintenta(buscador):
    entrada = _entrada("¿Qué es el concepto 1035 de mi recibo?")
    ids = [f.fragmento_id for f in buscador.buscar(entrada.mensaje, obtener_usuario("EMP-1091"), k=5)]
    p = ProveedorSimulado([_consulta(["ESC-04#001"]), _consulta([ids[0]])])
    r = responder(entrada, buscador=buscador, motor=Motor(p))
    assert r.ok and p.llamadas == 2 and r.metricas.intentos == 2
    assert "ESC-04#001" in p.prompts[1]   # el reintento le explica al modelo qué cita no era válida


def test_sin_evidencia_requiere_humano(buscador):
    entrada = _entrada("¿La empresa me reintegra el gasto de guardería?")
    r = responder(entrada, buscador=buscador,
                  motor=Motor(ProveedorSimulado([_consulta([], "No tengo esa información; pasa a RRHH.")])))
    assert r.ok and r.requiere_humano and r.motivo_humano == "sin_evidencia_en_documentos"
    assert r.estado == EstadoNovedad.DERIVADA_RRHH and r.fuentes == []


def test_fuera_de_tema_no_lleva_citas():
    with pytest.raises(ValidationError, match="citas"):
        Salida.model_validate({**ProveedorSimulado.SIN_DATOS, "categoria": "fuera_de_tema", "confianza": 0.9,
                               "respuesta_supervisor": "Solo puedo ayudarte con novedades de personal.",
                               "citas": ["POL-01#001"]}, context={"ids_validos": {"POL-01#001"}})


def test_error_del_motor_siempre_requiere_humano(buscador):
    from src.contrato import TipoError
    r = responder(_entrada("¿Qué es el concepto 1035?"), buscador=buscador,
                  motor=Motor(ProveedorSimulado(error=TipoError.AUTENTICACION)))
    assert not r.ok and r.requiere_humano
