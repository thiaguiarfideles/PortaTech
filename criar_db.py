import sqlite3

conn = sqlite3.connect('condominio.db')
cursor = conn.cursor()

# Moradores
cursor.execute("""
CREATE TABLE IF NOT EXISTS morador (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    casa TEXT UNIQUE NOT NULL,
    tipo TEXT NOT NULL,
    tem_carro BOOLEAN DEFAULT 0,
    qtde_moradores INTEGER NOT NULL,
    foto_morador TEXT,
    foto_placa TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP
);
""")

# Vagas de garagem
cursor.execute("""
CREATE TABLE IF NOT EXISTS vaga_garagem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    morador_id INTEGER,
    placa TEXT,
    ocupada BOOLEAN DEFAULT 0,
    FOREIGN KEY(morador_id) REFERENCES morador(id)
);
""")

# Visitantes
cursor.execute("""
CREATE TABLE IF NOT EXISTS visitante (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    casa_destino TEXT NOT NULL,
    hora_entrada TEXT DEFAULT CURRENT_TIMESTAMP,
    hora_limite TEXT NOT NULL,
    placa TEXT,
    foto_visitante TEXT
);
""")

# Movimentação (entradas e saídas)
cursor.execute("""
CREATE TABLE IF NOT EXISTS movimentacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    identificador TEXT NOT NULL,
    status TEXT NOT NULL,
    entrada TEXT NOT NULL,
    saida TEXT
);
""")

cursor.execute("""

CREATE TABLE veiculo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_morador INTEGER NOT NULL,
    qtde_veiculos INTEGER NOT NULL DEFAULT 1,
    placa TEXT NOT NULL,
    tipo_veiculo TEXT,
    data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_morador) REFERENCES morador(id)
);
""")



conn.commit()
conn.close()

print("Tabelas criadas com sucesso.")
