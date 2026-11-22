# ERR-09 · Errores de configuración al arrancar

**Responsable:** Equipo 3 · **Historia:** Shortcut #125 · **Rama:** `juanpablojimnezmartn/sc-125/err-09-errores-de-configuracion-al-arrancar` → `equipo3`

## Problema

Si faltaba `SECRET_KEY` o no pasaba la validación de SEG-01, uvicorn mostraba
el traceback completo de Pydantic. Para alguien que acaba de clonar el repo no
quedaba claro qué variable corregir ni cómo generarla.

## Solución

`get_settings()` captura el `ValidationError` de `Settings()` y termina el
proceso con `SystemExit` y **una sola línea** (código de salida 1):

```text
Error de configuración: falta SECRET_KEY en el entorno o en .env; genera una con: python -c "import secrets; print(secrets.token_urlsafe(48))"
```

- Nombra cada variable que falta o es inválida, separadas por `;`.
- Para una variable inválida incluye el motivo del validador (por ejemplo, el
  de SEG-01: "es un valor de ejemplo o débil").
- Nunca incluye el valor rechazado, para no filtrar un secreto real en los logs.

`Settings(...)` directo (tests, `create_app(settings)`) sigue lanzando
`ValidationError` como antes; solo cambia el arranque por entorno.

## Pruebas

`tests/test_config.py`: variable faltante, clave de ejemplo sin filtrarla,
varias variables a la vez y el arranque real (`app.main:app` en un
subproceso) sin `Traceback` en stderr.
