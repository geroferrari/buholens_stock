web: python manage.py migrate --noinput && python manage.py migrate_tenants && python manage.py collectstatic --noinput && gunicorn stockero.wsgi --log-file -
