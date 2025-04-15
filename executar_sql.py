import sqlite3

# Caminho para o arquivo SQL
caminho_sql = "criar_tabela_veiculo.sql"

# Conexão com o banco de dados
conn = sqlite3.connect("condominio.db")
cursor = conn.cursor()

# Leitura e execução do script SQL
with open(caminho_sql, "r", encoding="utf-8") as f:
    script = f.read()
    cursor.executescript(script)

conn.commit()
conn.close()

print("Tabela 'veiculo' recriada com sucesso.")
