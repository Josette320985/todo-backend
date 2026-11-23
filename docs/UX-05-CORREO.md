# UX-05: comprobación del correo antes del registro

`POST /api/v1/auth/validate-email` recibe `{ "email": "..." }` y devuelve
HTTP 200 con `valid`, `normalized` y `message`. Un formato inválido tiene
`valid: false`; no se trata como fallo de la petición de registro.

La comprobación reutiliza el tipo `NormalizedEmail` de `UserCreate`, mediante
un TypeAdapter compartido. Incluye las mismas reglas de email-validator,
Unicode/IDN y normalización. No consulta usuarios, no verifica DNS, no crea
cuentas ni devuelve información sobre la existencia de una cuenta.

La entrada está limitada a 2048 caracteres. Hay un bucket independiente de
60 comprobaciones por minuto e IP, usando el rate limiter existente. No consume
los intentos de registro/login. El endpoint de registro conserva toda su
validación; esta consulta no sustituye ningún control del servidor.

Desplegar este backend antes del frontend que usa la comprobación. Si el
endpoint falta o falla, el nuevo frontend conserva los datos y no envía el
registro sin validar.

Verificación: 25 pruebas nuevas de formato, Unicode, dominios reservados,
límites, independencia del rate limit y ausencia de enumeración de cuentas.
Suite completa: 308 pruebas aprobadas; mypy sin errores.
