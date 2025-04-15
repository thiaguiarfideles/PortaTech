Primeiro, certifique-se de que seu app.py tem a configuração do Flask-Migrate:

python
Copy
from flask_migrate import Migrate

# ... após criar a instância do app e do db ...
migrate = Migrate(app, db)
2. Processo de Atualização do Banco de Dados
Você precisará rodar os seguintes comandos:

bash
Copy
# 1. Crie uma nova migração (isso analisará suas mudanças nos modelos)
flask db migrate -m "Adiciona sistema de vagas por tipo de morador"

# 2. Aplique as migrações ao banco de dados
flask db upgrade
3. Se você ainda não tem as tabelas criadas
Para um banco de dados novo ou se você precisar recriar completamente as tabelas:

bash
Copy
# 1. Apague o banco de dados existente (se necessário)
rm instance/condominio.db

# 2. Crie todas as tabelas
flask db upgrade
4. Inicialize as vagas com o comando personalizado
Após criar as tabelas, rode o comando para inicializar as vagas:

bash
Copy
flask init-vagas
5. Verifique se tudo foi criado corretamente
Você pode verificar no shell do Flask:

bash
Copy
flask shell
python
Copy
# No shell do Flask
from app import db, VagaGaragem, Morador
print(VagaGaragem.query.count())  # Deve retornar 73
print(Morador.query.filter_by(tipo='proprietario').count())
print(Morador.query.filter_by(tipo='inquilino').count())
6. Possíveis Problemas e Soluções
Se encontrar erros:

Tabelas não existem:

bash
Copy
flask db stamp head  # Marca o banco como atualizado
flask db migrate
flask db upgrade
Problemas com colunas existentes:

Se precisar alterar colunas existentes, você pode precisar:

bash
Copy
flask db migrate -m "alterar_coluna_x"
flask db upgrade
Erros de migração:

Se uma migração falhar, você pode:

bash
Copy
flask db downgrade  # Reverte a última migração
# Corrija seus modelos e tente novamente
flask db migrate
flask db upgrade
7. Atualização dos Dados Existentes
Se você já tem dados no banco, pode precisar de um script de migração de dados:

python
Copy
@app.cli.command('migrar-dados-vagas')
def migrar_dados_vagas():
    """Migra dados existentes para o novo sistema de vagas"""
    from sqlalchemy import text
    
    # Atualiza o tipo dos moradores existentes (exemplo)
    db.session.execute(text("UPDATE morador SET tipo='proprietario' WHERE tipo IS NULL"))
    db.session.commit()
    
    print("Dados migrados com sucesso!")
Lembre-se de fazer backup do seu banco de dados antes de realizar migrações importantes!