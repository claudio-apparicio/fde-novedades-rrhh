# fde-novedades-rrhh

Asistente de novedades de personal para el área de RRHH de una pyme industrial metalúrgica.
Proyecto del curso **Forward Deployed Engineer** (Claudio Aparicio).

Los supervisores de planta informan horas extras, ausencias, licencias, vacaciones y adelantos
por WhatsApp o mail, en texto libre. Hoy el 22,5 % llega incompleto y el ida y vuelta para
completarlas es el cuello de botella del proceso (ficha de la PE1). Este repositorio crece en cada
preentrega; cada estado queda marcado con una etiqueta de Git.

| Etiqueta | Qué agrega |
|---|---|
| `pe2` | Motor LLM: contrato Pydantic, reintento único, error estructurado, tokens, costo y latencia |
| `pe3` | RAG con permisos por rol, búsqueda híbrida (vectorial + BM25), respuestas con fuentes |

```
Entrada ─► usuario del directorio (rol) ─► buscar(): ChromaDB filtrado por rol + BM25 del rol ─► RRF
        ─► fragmentos permitidos ─► prompt (src/prompts/*.txt) ─► LLM ─► JSON ─► valida contra Salida
        ─► reglas.py (estado, quién aprueba) ─► Salida + fuentes · requiere_humano si no hay evidencia
                                    │ inválido: registra el campo, reintenta 1 vez, después ErrorMotor
```

## Cómo correrlo desde un clon limpio

Requisitos: Python 3.10 a 3.13 y git.

```bash
git clone https://github.com/claudio-apparicio/fde-novedades-rrhh.git
cd fde-novedades-rrhh

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# Editá .env: PROVEEDOR_LLM=<anthropic|openai|xai> y la clave de ese proveedor
```

### Sin clave

```bash
pytest                                                    # 87 pruebas, sin clave ni descargas
PROVEEDOR_LLM=simulado python -m src.motor --mensaje "Juan hizo horas extra el sábado"
EMBEDDINGS=simulado python -m src.rag.ingesta
EMBEDDINGS=simulado PROVEEDOR_LLM=simulado python -m src.rag.responder --usuario EMP-1091 \
    --mensaje "¿Qué es el concepto 1035 de mi recibo?"
```

En Windows (PowerShell) las variables se ponen antes: `$env:PROVEEDOR_LLM="simulado"; python -m src.motor --mensaje "..."`
(y `Remove-Item Env:PROVEEDOR_LLM` para volver a usar el `.env`).

### Con la clave del `.env`

```bash
python -m src.motor --mensaje "El 1091 hizo 10 hs extras al 100% hoy" \
    --supervisor SUP-003 --sector montaje --canal whatsapp --recibida 2026-09-12T16:00
python -m src.rag.ingesta                                 # la primera vez descarga el modelo de embeddings (~220 MB)
python -m src.rag.responder --usuario SUP-003 --mensaje "¿Cuántos días de licencia por matrimonio?"
```

Los logs (búsqueda, llamadas, tokens, validación, reintentos) salen por la terminal y el resultado, como JSON.
Código de salida: `0` si validó, `1` si devolvió un error estructurado.

### Verificar que el README funciona desde cero

```bash
python scripts/verificar_clon_limpio.py                   # clona en una carpeta temporal y sigue este README
```

Clona el repo, crea el venv, instala, copia `.env.example` como `.env` **sin claves**, corre `pytest`, el
motor simulado, la ingesta y una consulta del RAG, y confirma con `git check-ignore -v .env` que el `.env`
está ignorado. La salida queda en `resultados/verificacion_clon_limpio.txt`.

## Configuración

### `.env.example` (contenido exacto)

```dotenv
# Copiá este archivo como .env y completá los valores. El .env NO se sube al repositorio.

# Proveedor: anthropic | openai | xai | simulado   (simulado funciona sin clave; vacío = anthropic)
PROVEEDOR_LLM=
# Modelo (vacío = claude-haiku-5-5 con anthropic, gpt-5-mini con openai, grok-4.3 con xai)
MODELO_LLM=

# Claves (solo hace falta la del proveedor que uses)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
XAI_API_KEY=

# Opcionales
# Segundos de espera máxima por llamada (vacío = 30)
LLM_TIMEOUT_S=
# Tokens máximos de salida (vacío = 1024 con anthropic, 4000 con openai)
LLM_MAX_TOKENS=
# Solo OpenAI: minimal | low | medium | high | ninguno (vacío = low)
OPENAI_REASONING_EFFORT=
# Solo con PROVEEDOR_LLM=simulado: respuesta_invalida | limite_de_uso | sin_conexion | tiempo_agotado
SIMULAR=

# PE3 · RAG (todo opcional)
# Embeddings: local | simulado   (vacío = local: modelo multilingüe en la PC, se descarga una vez a modelos/)
EMBEDDINGS=
# Modelo de embeddings local (vacío = sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
EMBEDDINGS_MODELO=
# Fragmentado que usa responder(): seccion | fijo300   (vacío = el que ganó en medir_rag, o seccion)
FRAGMENTADO=
# Carpeta del índice de ChromaDB (vacío = indice/)
INDICE_DIR=
```

### `.gitignore` (contenido exacto)

```gitignore
# Secretos: la clave va solo en .env, que nunca se sube
.env

# Python
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/

# PE3: índice de ChromaDB y modelo de embeddings (se regeneran con python -m src.rag.ingesta)
indice/
modelos/

# Entregables generados (el PDF se sube al aula, no al repo)
entrega/
*.pdf

# Sistema
.DS_Store
```

`tests/test_repo.py` verifica que estos dos bloques coincidan con los archivos, que `.env` esté en
`.gitignore`, que `.env.example` no tenga ningún valor cargado y que documente todas las variables que
lee el código.

## PE3 · RAG con permisos y búsqueda híbrida

| Pieza | Contrato | Archivo |
|---|---|---|
| Ingesta | `ingestar(carpeta, config)` → colección de ChromaDB | `src/rag/ingesta.py` (`python -m src.rag.ingesta`) |
| Búsqueda | `buscar(consulta, usuario, k)` → fragmentos con `documento`, `fragmento_id`, `texto`, `puntaje` | `src/rag/busqueda.py` |
| Respuesta | `responder(entrada)` → `Salida` + `fuentes` + `requiere_humano` | `src/rag/responder.py` |
| Permisos | roles, directorio de usuarios y filtro `where` | `src/rag/permisos.py`, `datos/usuarios.json` |
| Documentos | lectura, limpieza, secciones y fragmentado | `src/rag/documentos.py`, `documentos/` |

**Documentos y permisos** (`documentos/catalogo.json`; un archivo que no está en el catálogo no se ingesta):

| Documento | supervisor | analista | jefe | empleado |
|---|---|---|---|---|
| POL-01 Política de licencias y vacaciones | sí | sí | sí | sí |
| PRO-02 Procedimiento para informar novedades | sí | sí | sí | no |
| CRI-03 Criterio de aprobación (RRHH) | no | sí, sin §5 | sí | no |
| ESC-04 Escala salarial 2026 (ficticia) | no | sí, sin §4 | sí | no |
| CCT-05 Resumen de convenio y LCT (`.txt` con ruido de PDF) | sí | sí | sí | sí |
| GUI-06 Guía del recibo y del estado de novedades | sí | sí | sí | sí |
| PRO-07 Protocolo de licencias con causa sensible | no | sí | sí | no |

- **Ingesta:** limpia pies y encabezados de página, palabras cortadas con guion y tablas; divide en
  secciones y fragmenta con dos configuraciones: `seccion` (una sección, hasta 900 caracteres) y `fijo300`
  (ventanas de 300 con 60 de solapamiento). **Ningún fragmento cruza una sección**, así un permiso por
  sección no se filtra. Cada fragmento lleva `documento`, `seccion`, `roles` y un booleano por rol.
- **Permisos antes de buscar:** el rol sale de `datos/usuarios.json`, no del mensaje. La búsqueda vectorial
  le pasa a ChromaDB `where={"rol_<rol>": True}` y el índice BM25 de cada rol se arma con lo que la base
  devuelve para ese rol. Lo restringido no se puntúa ni llega al prompt.
- **Híbrida:** vectorial (embeddings multilingües locales con fastembed) + BM25 que conserva códigos
  (`HE100`, `F-12`, `19.032`), fusionados con Reciprocal Rank Fusion. Si la consulta trae un código o un
  número, el ranking de BM25 pesa el doble.
- **Respuesta con fuentes:** el modelo solo puede citar fragmentos que recibió (si cita otro, la validación
  falla y se reintenta). Una consulta sin citas devuelve `requiere_humano = true` y estado `derivada_rrhh`.

```bash
python scripts/evidencia_pe3.py          # todo: ingesta, tests de permisos, medición, 10 preguntas, errores y PDF
python scripts/medir_rag.py              # top-k con las 2 configuraciones, fugas y contraste (no usa el LLM)
python scripts/demo_rag.py               # las 10 preguntas de punta a punta con el LLM
pytest tests/test_rag_permisos.py -v     # tests de permisos por rol
```

Preguntas de prueba: `datos/preguntas_rag.json` (6 normales, 2 sin respuesta, 2 restringidas, cada una con
el documento que tiene la respuesta). Consultas exactas para comparar vectorial vs híbrida:
`datos/consultas_contraste.json`. La evidencia queda en `resultados/pe3/`.

## PE2 · Motor LLM base

`src/motor.py` recibe la consulta, se la pasa a un modelo de lenguaje real y devuelve una respuesta
**validada con Pydantic**, junto con los **tokens** (campo `usage` de la respuesta de la API, sumando los de
razonamiento), el **costo en USD** y la **latencia en ms**. Cada métrica dice de dónde salen sus tokens
(`fuente_tokens`: `usage` o `estimado` con el proveedor simulado).

```bash
python scripts/medir.py                  # 5 consultas reales → resultados/medicion.csv, .json y terminal_medicion.txt
python scripts/medir.py --resumen        # rehace la tabla y los KPI desde la última medición, sin llamar al modelo
python scripts/demo_errores.py           # salida inválida, clave inválida y sin conexión → resultados/terminal_errores.txt
```

Las 5 consultas de `datos/consultas_pe2.json` son un **smoke test**: prueban el circuito completo (una
completa, dos incompletas, una confusa y una fuera de tema). La medición separa:

- **KPI con meta (PE1):** detección de faltantes al ingreso (≥ 95 %) y falsas alarmas (≤ 10 %). Con n = 5 no
  se puede afirmar la meta: se evalúa con el set fijo de 60 mensajes en la PE6.
- **Indicadores exploratorios (sin meta, línea de base):** categoría correcta, validación al primer intento,
  latencia, costo por consulta y costo proyectado por mes.

## Estructura

```
src/
  motor.py          Motor: arma el prompt, llama al modelo, valida, reintenta, mide (y CLI)
  contrato.py       Entrada, Salida (con citas) y los Enum con sus reglas de validación
  reglas.py         Reglas de negocio deterministas (estado y quién aprueba)
  proveedores.py    Anthropic, OpenAI, xAI y simulado detrás de una misma interfaz
  precios.py        Precios publicados por millón de tokens y cálculo del costo
  prompts/          sistema.txt, usuario.txt y correccion.txt (plantillas separadas del código)
  rag/              documentos, embeddings, ingesta, busqueda, permisos y responder (PE3)
documentos/         7 documentos del caso + catalogo.json con los permisos
datos/              consultas de la PE2, preguntas del RAG, consultas de contraste y directorio de usuarios
scripts/            medición, demos, evidencia, PDFs y verificación desde un clon limpio
tests/              pruebas con pytest (no necesitan clave ni descargas)
resultados/         evidencia de la última medición (pe3/ para el RAG)
```

Prompt, validación y reglas siguen separados: el prompt se cambia en `src/prompts/`, el contrato en
`src/contrato.py` y los umbrales en `src/reglas.py`, sin tocar el proveedor.

## Contrato de datos

| `Entrada` | Regla |
|---|---|
| `supervisor_id` | id de quien escribe: `SUP-001`, `ANA-001`, `JEF-001` o `EMP-<legajo>` (el rol se busca en el directorio) |
| `sector` | Enum de 5 sectores; obligatorio para supervisores |
| `canal` | Enum: whatsapp, mail, chat_web |
| `recibida_en` | fecha y hora |
| `mensaje` | largo de 10 a 2000 caracteres |

| `Salida` (la devuelve el modelo) | Regla |
|---|---|
| `categoria` | Enum: novedad, consulta, fuera_de_tema |
| `tipo` | Enum de 9 tipos (opcional) |
| `legajo` | patrón `^\d{4}$` (opcional) |
| `fecha_desde`, `fecha_hasta` | fecha; hasta ≥ desde; como máximo 60 días hacia atrás |
| `cantidad`, `unidad` | > 0; Enum HS / dias / $; rango HS 0,5–12, días 1–30, $ 1.000–500.000; unidad acorde al tipo |
| `tiene_adjunto` | bool |
| `campos_faltantes` | Enum; tiene que coincidir exactamente con los campos vacíos (+ `adjunto` si es enfermedad o ausencia justificada sin certificado) |
| `respuesta_supervisor` | largo de 20 a 600 caracteres |
| `confianza` | rango de 0 a 1 |
| `citas` | hasta 6 ids `^[A-Z]{3}-\d{2}#\d{3}$`; solo fragmentos enviados al modelo; vacío si es fuera de tema |

Después de validar, `reglas.py` decide el estado: `requiere_dato`, `pendiente_analista`,
`pendiente_jefe` (HS > 8 o adelanto > $100.000), `revision_manual` (confianza < 0,7),
`respondida` (consulta con citas), `derivada_rrhh` (consulta sin evidencia) o `fuera_de_alcance`.
Los umbrales son supuestos de la PE1 a confirmar con el jefe de RRHH.

## Manejo de errores

- **Salida inválida:** se registra cada campo que falló con su valor, se le reenvían los errores al
  modelo **una vez** y, si vuelve a fallar, se devuelve un `ErrorMotor` completo: `tipo_error=validacion`,
  los campos fallidos con su valor, la **respuesta cruda completa** del modelo, `requiere_humano=true` y las
  métricas. La novedad no se carga y pasa a revisión manual.
- **Errores de la API:** límite de uso (429), sin conexión, tiempo agotado y errores 5xx se reintentan
  una vez a los 2 segundos. Clave inválida y pedidos rechazados se devuelven sin reintentar. Los
  reintentos automáticos de los SDK están apagados para que cada llamada quede medida y registrada.
- **Permisos:** un usuario que no está en el directorio recibe `tipo_error=permisos` y no se busca nada.
- **Configuración:** si falta la clave, no hay precio cargado para el modelo o el índice se armó con otros
  embeddings, el sistema lo avisa antes de llamar a la API.

## Proveedores y costos

| `PROVEEDOR_LLM` | Modelo por defecto | US$ por millón de tokens (entrada / salida) |
|---|---|---|
| `anthropic` (por defecto) | `claude-haiku-5-5` | 0,10 / 0,50 |
| `openai` | `gpt-5-mini` | 0,25 / 2,00 |
| `xai` | `grok-4.3` | 1,25 / 2,50 |
| `simulado` | sin clave | 0 (tokens estimados) |

Fuentes: [precios de Anthropic](https://platform.claude.com/docs/en/about-claude/pricing),
[gpt-5-mini](https://developers.openai.com/api/docs/models/gpt-5-mini),
[modelos de xAI](https://docs.x.ai/docs/models). Consultados en noviembre de 2026.
Los embeddings del RAG corren en la PC (fastembed, ONNX): no tienen costo por consulta.

## Seguridad

La clave va solo en `.env`, que está en `.gitignore` (ver arriba). `.env.example` tiene los nombres de las
variables sin valores. Los documentos y los datos son ficticios o anonimizados; la escala salarial es
inventada. Los documentos del RAG y sus embeddings no salen de la PC: el índice (`indice/`) y el modelo
(`modelos/`) tampoco se suben al repositorio.
