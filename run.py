#!/usr/bin/env python3
import os
import sys
from subprocess import Popen
from pathlib import Path

def main():
    # Configurações
    venv_path = Path('venv')
    activate_script = str(venv_path / 'Scripts' / 'activate') if os.name == 'nt' else str(venv_path / 'bin' / 'activate')
    
    # Comandos
    commands = [
        f'call {activate_script}' if os.name == 'nt' else f'source {activate_script}',
        'set FLASK_APP=condominio.app',
        'set FLASK_ENV=development',
        'flask run --host=0.0.0.0 --port=5000'
    ]

    # Executa
    Popen(' && '.join(commands), shell=True)

if __name__ == '__main__':
    main()