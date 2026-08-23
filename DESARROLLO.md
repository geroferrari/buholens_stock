# Ambiente de desarrollo

Dev corre sobre un **Postgres local en Docker**, mismo motor que producción, para
evitar bugs por diferencias entre SQLite y Postgres.

## Puesta en marcha (una vez)

```bash
docker compose up -d db          # levanta Postgres local en localhost:5432
python manage.py migrate
python manage.py createsuperuser
```

El `.env` ya apunta a esa base:
`DATABASE_URL=postgresql://optica:optica@localhost:5432/stockero`
Esa base (`'default'`) es solo de **control**: guarda el registro de ópticas
(`Tenant`). Cada óptica tiene su propia base separada (ver "Multi-tenant"
abajo).

## Multi-tenant: dar de alta una óptica en local

Cada óptica (tenant) vive en su propia base Postgres, resuelta por el
subdominio con el que se entra (`<slug>.localhost:8000`). Para tener una con
la que probar:

```bash
python manage.py crear_optica --slug demo --nombre "Óptica Demo"
python manage.py generar_datos_prueba --tenant demo   # datos de prueba, opcional
python manage.py configurar_usuarios --tenant demo --admin admin
python manage.py runserver
```

Y entrar a `http://demo.localhost:8000/` (los navegadores modernos resuelven
`*.localhost` a 127.0.0.1 solos, no hace falta tocar `/etc/hosts`; si algo no
lo resuelve —por ejemplo `curl` en algunos sistemas—, agregá una línea
`127.0.0.1 demo.localhost` a `/etc/hosts` como fallback).

Entrar a `http://localhost:8000/` (sin subdominio) sigue sirviendo sobre la
base de control `'default'` — útil para los 231+ tests, que no pasan por
ningún subdominio.

## Día a día

```bash
docker compose up -d db          # si no está corriendo
python manage.py runserver
```

## Comandos útiles

```bash
python manage.py test            # suite completa
docker compose down              # apaga la base (los datos quedan en el volumen)
docker compose down -v           # apaga y BORRA los datos locales
```

## Notas

- La imagen es `postgres:16`. Si tu base de producción usa otra versión mayor,
  ajustá el tag en `docker-compose.yml` para que coincida.
- Para volver a SQLite: dejá `DATABASE_URL=` vacío en `.env`.
- **Nunca usar producción como sandbox.** Si necesitás datos reales para
  reproducir algo, restaurá un backup (ver `OPERACION.md`) en la base local.
