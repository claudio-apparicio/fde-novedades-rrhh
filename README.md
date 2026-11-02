# fde-novedades-rrhh

Asistente de novedades de personal para el área de RRHH de una pyme industrial metalúrgica.
Proyecto del curso **Forward Deployed Engineer** (Claudio Aparicio).

Los supervisores de planta informan horas extras, ausencias, licencias, vacaciones y adelantos
por WhatsApp o mail, en texto libre. Hoy el 22,5 % llega incompleto y el ida y vuelta para
completarlas es el cuello de botella del proceso (ficha de la PE1). Este repositorio crece en cada
preentrega; cada estado queda marcado con una etiqueta de Git (`pe2`, `pe3`, ...).

## PE2 · Motor LLM base

`src/motor.py` recibe la consulta de un supervisor, se la pasa a un modelo de lenguaje real y devuelve
una respuesta **validada con Pydantic**, junto con los **tokens** (campo `usage` de la API), el **costo
en USD** y la **latencia en ms**.

```
Entrada ──► prompt (src/prompts/*.txt) ──► LLM ──► JSON ──► valida contra Salida ──► reglas.py ──► ResultadoMotor
                                                              │ inválido
                                                              ├─► registra qué campo falló y reintenta 1 vez
                                                              └─► si vuelve a fallar: ErrorMotor estructurado
```

## Cómo correrlo desde un clon limpio

Requisitos: Python 3.10 o superior y git.

```bash
git clone https://github.com/claudio-apparicio/fde-novedades-rrhh.git
cd fde-novedades-rrhh

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# Editá .env: PROVEEDOR_LLM=anthropic y ANTHROPIC_API_KEY=<tu clave>
```

### Probarlo sin clave

```bash
PROVEEDOR_LLM=simulado python -m src.motor --mensaje "Juan hizo horas extra el sábado"
pytest                              # 30 pruebas del contrato y del motor, sin clave
```

En Windows (PowerShell): `$env:PROVEEDOR_LLM="simulado"; python -m src.motor --mensaje "..."`.

### Una consulta con el modelo real

```bash
python -m src.motor --mensaje "El 1091 hizo 10 hs extras al 100% hoy" \
    --supervisor SUP-003 --sector montaje --canal whatsapp --recibida 2026-09-12T16:00
```

Los logs (llamadas, tokens, validación, reintentos) salen por la terminal y el resultado, como JSON.
Código de salida: `0` si validó, `1` si devolvió un error estructurado.

### Medición de la PE2 y evidencia

```bash
python scripts/medir.py             # 5 consultas reales → resultados/medicion.csv, .json y terminal_medicion.txt
python scripts/demo_errores.py      # salida inválida, clave inválida y sin conexión → resultados/terminal_errores.txt
python scripts/generar_pdf.py
```

Las 5 consultas están en `datos/consultas_pe2.json`: una completa, dos incompletas, una confusa y una
fuera de tema, cada una con su resultado esperado.

## Estructura

```
src/
  motor.py          Motor: arma el prompt, llama al modelo, valida, reintenta, mide (y CLI)
  contrato.py       Entrada, Salida y los Enum con sus reglas de validación
  reglas.py         Reglas de negocio deterministas (estado y quién aprueba)
  proveedores.py    Anthropic, OpenAI, xAI y simulado detrás de una misma interfaz
  precios.py        Precios publicados por millón de tokens y cálculo del costo
  prompts/          sistema.txt, usuario.txt y correccion.txt (plantillas separadas del código)
scripts/            medir.py, demo_errores.py, generar_pdf.py
datos/              consultas de la medición
tests/              pruebas con pytest (no necesitan clave)
resultados/         evidencia de la última medición
```

## Contrato de datos

| `Entrada` | Regla |
|---|---|
| `supervisor_id` | patrón `^SUP-\d{3}$` |
| `sector` | Enum: torneria, soldadura, montaje, deposito, mantenimiento |
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

Después de validar, `reglas.py` decide el estado: `requiere_dato`, `pendiente_analista`,
`pendiente_jefe` (HS > 8 o adelanto > $100.000), `revision_manual` (confianza < 0,7),
`derivada_rrhh` (consultas, que se responden con documentos en la PE3) o `fuera_de_alcance`.
Los umbrales son supuestos de la PE1 a confirmar con el jefe de RRHH.

## Manejo de errores

- **Salida inválida:** se registra cada campo que falló con su valor, se le reenvían los errores al
  modelo **una vez** y, si vuelve a fallar, se devuelve un `ErrorMotor` con `tipo_error=validacion`,
  los campos fallidos, la respuesta cruda y las métricas. La novedad no se carga y pasa a revisión manual.
- **Errores de la API:** límite de uso (429), sin conexión, tiempo agotado y errores 5xx se reintentan
  una vez a los 2 segundos. Clave inválida y pedidos rechazados se devuelven sin reintentar. Los
  reintentos automáticos de los SDK están apagados para que cada llamada quede medida y registrada.
- **Configuración:** si falta la clave o no hay precio cargado para el modelo, el motor lo avisa antes
  de llamar a la API.

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

## Seguridad

La clave va solo en `.env`, que está en `.gitignore`. `.env.example` tiene los nombres de las
variables sin valores. Los datos de las consultas son ficticios o anonimizados.
