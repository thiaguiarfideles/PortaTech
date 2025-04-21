@echo off
call venv\Scripts\activate
set FLASK_APP=condominio.app
set FLASK_ENV=development
flask run --host=0.0.0.0 --port=5000
pause