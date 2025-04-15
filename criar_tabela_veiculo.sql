DROP TABLE IF EXISTS veiculo;

CREATE TABLE veiculo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_morador INTEGER NOT NULL,
    qtde_veiculos INTEGER NOT NULL DEFAULT 1,
    placa TEXT NOT NULL,
    tipo_veiculo TEXT,
    data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_morador) REFERENCES morador(id)
);
