# CLAUDE.md · contexto para trabajar en este repo

Proyecto del curso **Forward Deployed Engineer** (Coderhouse) de Claudio Aparicio. Asistente de novedades de
personal para el área de RRHH de una pyme industrial metalúrgica: los supervisores informan horas extras,
ausencias, licencias, vacaciones y adelantos en texto libre; el asistente los estructura, valida, pide lo que
falta y propone el registro que aprueba una persona de RRHH.

El estado completo del proyecto (ficha de la PE1, decisiones, supuestos, mediciones) vive en el Proyecto de
claude.ai "Forward Deployed Engineer": empezar por `claude/00_LEEME_estado_del_proyecto.md`.

## Convenciones
- Idioma: castellano rioplatense en código, comentarios, mensajes, README y documentos.
- Un repo que crece por pre-entrega; al cerrar cada una: `git tag peN` (PE2 = commit aa3aecd).
  Las etiquetas las sube Claudio (`git push origin peN`): desde el entorno de Claude el push de tags da 403.
- Nunca subir `.env` ni claves. `.env.example` solo con nombres de variables.
- Solo datos ficticios o anonimizados. Nada de CUIL, domicilios ni nombres reales de empleados.
- El modelo interpreta, el código decide: el estado y quién aprueba van en `src/reglas.py`, no en el prompt.
- Los prompts van en `src/prompts/*.txt` (plantillas `string.Template`), nunca dentro de funciones.
- Toda salida del modelo se valida con Pydantic (`src/contrato.py`); reintento único con los errores por campo.
- Toda llamada mide tokens (`usage`, incluidos los de razonamiento), costo en USD y latencia en ms.
- Precios en `src/precios.py` con su fuente; si se agrega un modelo, cargar su precio publicado.

## Comandos
```bash
pip install -r requirements.txt
pytest                                   # sin clave
PROVEEDOR_LLM=simulado python -m src.motor --mensaje "..."
python scripts/medir.py                  # necesita clave en .env
python scripts/demo_errores.py
python scripts/generar_pdf.py            # PDF de la PE2 en entrega/
```

## Entorno de Claudio
Windows, Python con venv en `.venv`. La clave disponible es de xAI (`PROVEEDOR_LLM=xai`, grok-4.3).
Desde el entorno de Claude no hay salida a las APIs de modelos: las mediciones reales las corre Claudio.
