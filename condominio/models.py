from datetime import datetime, timezone
from enum import Enum
import os
import re
from typing import Optional
from werkzeug.utils import secure_filename
from flask import current_app, url_for
from sqlalchemy import event, Enum as SQLEnum, ForeignKey, CheckConstraint
from sqlalchemy.orm import validates, relationship
from sqlalchemy import Column, DateTime
from sqlalchemy.sql import func
from flask import current_app


from .extensions import db

from sqlalchemy.orm import validates

# ============================
# FUNÇÕES AUXILIARES
# ============================

def gerar_lista_casas():
    """Gera lista de casas disponíveis para cadastro"""
    casas = []
    for i in range(1, 46):  # 45 blocos
        casas.append(str(100 + i))  # térreo: 101 a 145
        casas.append(str(200 + i))  # superior: 201 a 245
    return sorted(casas, key=int)

# ============================
# ENUMS E CLASSES BASE
# ============================

class TipoMorador(Enum):
    PROPRIETARIO = 'proprietario'
    INQUILINO = 'inquilino'

class TipoVeiculo(Enum):
    CARRO = 'Carro'
    MOTO = 'Moto'
    CAMINHONETE = 'Caminhonete'
    VAN = 'Van'
    OUTRO = 'Outro'

    @classmethod
    def get_values(cls):
        return [e.value for e in cls]    
    


class TipoVaga(Enum):
    PROPRIETARIO = 'proprietario'
    INQUILINO = 'inquilino'
    VISITANTE = 'visitante'

class TipoMovimentacao(Enum):
    FACIAL = 'facial'
    PLACA = 'placa'
    MANUAL = 'manual'

class StatusMovimentacao(Enum):
    RECONHECIDO = 'reconhecido'
    NEGADO = 'negado'

# ============================
# MODELOS PRINCIPAIS
# ============================

class Morador(db.Model):
    __tablename__ = 'moradores'
    
    # Configurações
    FOTO_DIR = os.path.join('static', 'rostos_moradores')
    PLACA_DIR = os.path.join('static', 'placas_moradores')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    
    # Colunas
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, index=True)
    casa = db.Column(db.String(20), nullable=False, index=True)
    tipo = db.Column(SQLEnum(TipoMorador), nullable=False)
    tem_carro = db.Column(db.Boolean, default=False)
    qtde_moradores = db.Column(db.Integer, nullable=False, default=1)
    foto_morador = db.Column(db.String(255))
    foto_placa = db.Column(db.String(255))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, 
                            onupdate=datetime.utcnow)
    
    # Relacionamentos
    veiculos = db.relationship('Veiculo', back_populates='morador', cascade='all, delete-orphan')
    acessos = db.relationship('Movimentacao', back_populates='morador', order_by='desc(Movimentacao.entrada)')
    vagas = db.relationship('VagaGaragem', back_populates='morador')

    
    @validates('casa')
    def validate_casa(self, key, casa):
        if casa not in gerar_lista_casas():
            raise ValueError("Casa inválida")
        return casa

    @validates('tipo')
    def validate_tipo(self, key, tipo):
        if isinstance(tipo, str):
            tipo = TipoMorador(tipo)
        if not isinstance(tipo, TipoMorador):
            raise ValueError(f"Tipo inválido. Deve ser um dos: {list(TipoMorador)}")
        return tipo


    @validates('qtde_moradores')
    def validate_qtde_moradores(self, key, qtde):
        if not isinstance(qtde, int) or qtde < 1:
            raise ValueError("Quantidade de moradores deve ser um inteiro positivo")
        return qtde

    def _process_upload(self, file, upload_dir: str) -> Optional[str]:
        if file and self._allowed_file(file.filename):
            filename = secure_filename(f"morador_{self.id}_{file.filename}")
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.abspath(os.path.join(upload_dir, filename))  # Absolute path
            file.save(filepath)
            return filepath
        return None

    def _allowed_file(self, filename):
        """Verifica se a extensão do arquivo é permitida"""
        return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS

    @property
    def foto_morador_url(self):
        """Retorna URL para foto do morador"""
        if self.foto_morador:
            return url_for('static', filename=os.path.relpath(self.foto_morador, 'static'))
        return None

    @property
    def foto_placa_url(self):
        """Retorna URL para foto da placa"""
        if self.foto_placa:
            return url_for('static', filename=os.path.relpath(self.foto_placa, 'static'))
        return None

    def to_dict(self):
        """Converte modelo para dicionário (API)"""
        return {
            'id': self.id,
            'nome': self.nome,
            'casa': self.casa,
            'tipo': self.tipo.value,
            'tem_carro': self.tem_carro,
            'qtde_moradores': self.qtde_moradores,
            'foto_morador_url': self.foto_morador_url,
            'foto_placa_url': self.foto_placa_url,
            'criado_em': self.criado_em.isoformat(),
            'atualizado_em': self.atualizado_em.isoformat() if self.atualizado_em else None,
            'veiculos_count': len(self.veiculos),
            'acessos_count': len(self.acessos)
        }

    def __repr__(self):
        return f'<Morador {self.id} - {self.nome} ({self.casa})>'







class Veiculo(db.Model):
    __tablename__ = 'veiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(20), nullable=False, unique=True)
    tipo_veiculo = db.Column(db.Enum(TipoVeiculo), default=TipoVeiculo.CARRO)
    qtde_veiculos = db.Column(db.Integer, default=1)
    data_cadastro = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamentos
    morador_id = db.Column(db.Integer, db.ForeignKey('moradores.id'), nullable=False)
    morador = db.relationship('Morador', back_populates='veiculos')
    acessos = db.relationship('Movimentacao', back_populates='veiculo')
    vaga = db.relationship('VagaGaragem', back_populates='veiculo', uselist=False)
    

    @validates('placa')
    def validate_placa(self, key, placa):
        placa = re.sub(r'[^a-zA-Z0-9]', '', placa).upper()
        if len(placa) not in (7, 8):  # Padrões brasileiros
            raise ValueError("Formato de placa inválido")
        return placa

    @validates('tipo_veiculo')
    def validate_tipo_veiculo(self, key, tipo):
        tipos_validos = ['Carro', 'Moto', 'Caminhonete', 'Van', 'Outro']
        if tipo not in tipos_validos:
            raise ValueError(f"Tipo de veículo inválido. Deve ser um dos: {tipos_validos}")
        return tipo

    def __repr__(self):
        return f'<Veiculo {self.placa} - {self.tipo_veiculo.value}>'

class VagaGaragem(db.Model):
    __tablename__ = 'vagas_garagem'
    
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(10), nullable=False, unique=True)
    ocupada = db.Column(db.Boolean, default=False)
    data_ocupacao = db.Column(db.DateTime)
    tipo = db.Column(SQLEnum(TipoVaga), nullable=False)
    
    
    # Relacionamentos
    morador_id = db.Column(db.Integer, ForeignKey('moradores.id'))
    veiculo_id = db.Column(db.Integer, ForeignKey('veiculos.id'))
    visitante_id = db.Column(db.Integer, ForeignKey('visitantes.id'))
    
    morador = db.relationship('Morador', back_populates='vagas')
    veiculo = db.relationship('Veiculo', back_populates='vaga')
    visitante = db.relationship('Visitante', back_populates='vaga')

    __table_args__ = (
        CheckConstraint(
            '(morador_id IS NOT NULL AND visitante_id IS NULL) OR '
            '(morador_id IS NULL AND visitante_id IS NOT NULL)',
            name='check_vaga_owner'
        ),
    )

    @validates('tipo')
    def validate_tipo(self, key, tipo):
        if isinstance(tipo, str):
            tipo = TipoVaga(tipo)
        if not isinstance(tipo, TipoVaga):
            raise ValueError(f"Tipo de vaga inválido. Deve ser um dos: {list(TipoVaga)}")
        return tipo

    def __repr__(self):
        return f'<VagaGaragem {self.numero} - Tipo: {self.tipo.value}>'

class Visitante(db.Model):
    __tablename__ = 'visitantes'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    casa_destino = db.Column(db.String(20), nullable=False)
    hora_entrada = db.Column(db.DateTime, default=datetime.utcnow)
    hora_limite = db.Column(db.DateTime, nullable=False)
    placa = db.Column(db.String(20))
    foto_visitante = db.Column(db.String(200))
    
    # Relacionamentos
    acessos = db.relationship('Movimentacao', back_populates='visitante')
    vaga = db.relationship('VagaGaragem', back_populates='visitante', uselist=False)


    @validates('casa_destino')
    def validate_casa_destino(self, key, casa):
        if casa not in gerar_lista_casas() and casa != 'VISITANTE':
            raise ValueError("Casa de destino inválida")
        return casa

    def __repr__(self):
        return f'<Visitante {self.nome} - Casa: {self.casa_destino}>'

class Movimentacao(db.Model):
    __tablename__ = 'movimentacoes'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(SQLEnum(TipoMovimentacao), nullable=False)
    identificador = db.Column(db.String(100), nullable=False)
    status = db.Column(SQLEnum(StatusMovimentacao), nullable=False)
    #entrada = db.Column(db.DateTime, default=datetime.utcnow)
    entrada = db.Column(db.DateTime(timezone=True), server_default=func.now())
    #saida = db.Column(db.DateTime)
    saida = db.Column(db.DateTime(timezone=True))
    
    # Relacionamentos
    morador_id = db.Column(db.Integer, ForeignKey('moradores.id'))
    veiculo_id = db.Column(db.Integer, ForeignKey('veiculos.id'))
    visitante_id = db.Column(db.Integer, ForeignKey('visitantes.id'))
    
    morador = db.relationship('Morador', back_populates='acessos')
    veiculo = db.relationship('Veiculo', back_populates='acessos')
    visitante = db.relationship('Visitante', back_populates='acessos')

    __table_args__ = (
        CheckConstraint(
            '(morador_id IS NOT NULL AND visitante_id IS NULL) OR '
            '(morador_id IS NULL AND visitante_id IS NOT NULL)',
            name='check_movimentacao_owner'
        ),
        db.Index('idx_movimentacao_entrada', 'entrada'),
        db.Index('idx_movimentacao_saida', 'saida')
    )

    @validates('tipo')
    def validate_tipo(self, key, tipo):
        if isinstance(tipo, str):
            tipo = TipoMovimentacao(tipo)
        if not isinstance(tipo, TipoMovimentacao):
            raise ValueError(f"Tipo de movimentação inválido. Deve ser um dos: {list(TipoMovimentacao)}")
        return tipo

    @validates('status')
    def validate_status(self, key, status):
        if isinstance(status, str):
            status = StatusMovimentacao(status)
        if not isinstance(status, StatusMovimentacao):
            raise ValueError(f"Status inválido. Deve ser um dos: {list(StatusMovimentacao)}")
        return status
    
    @classmethod
    def registrar_saida(cls, identificador):
        movimentacao = cls.query.filter_by(
            identificador=identificador,
            saida=None
            ).order_by(cls.entrada.desc()).first()
        if movimentacao:
            movimentacao.saida = datetime.now(timezone.utc)
            db.session.commit()
            return True
        return False

    def __repr__(self):
        return f'<Movimentacao {self.id} - {self.tipo.value} - {self.status.value}>'

class ConfiguracaoVagas(db.Model):
    __tablename__ = 'configuracoes_vagas'
    
    id = db.Column(db.Integer, primary_key=True)
    total_vagas = db.Column(db.Integer, nullable=False)
    vagas_proprietario = db.Column(db.Integer, default=2)
    vagas_inquilino = db.Column(db.Integer, default=1)
    vagas_visitantes = db.Column(db.Integer, default=3)
    ultima_atualizacao = db.Column(db.DateTime, default=datetime.utcnow)

    @validates('total_vagas', 'vagas_proprietario', 'vagas_inquilino', 'vagas_visitantes')
    def validate_vagas(self, key, value):
        if not isinstance(value, int) or value < 0:
            raise ValueError("Valor deve ser um inteiro positivo")
        return value

    def __repr__(self):
        return f'<ConfiguracaoVagas Total: {self.total_vagas}>'

# ============================
# EVENT LISTENERS
# ============================

def inicializar_vagas():
    from .extensions import db
    from .models import ConfiguracaoVagas, VagaGaragem, Morador
    
    try:
        # Verifica se já existem vagas
        if VagaGaragem.query.first():
            return False
            
        config = ConfiguracaoVagas.query.first()
        if not config:
            config = ConfiguracaoVagas(
                total_vagas=73,
                vagas_proprietario=2,
                vagas_inquilino=1,
                vagas_visitantes=3
            )
            db.session.add(config)
        
        # Cria vagas para moradores
        moradores = Morador.query.all()
        for morador in moradores:
            num_vagas = config.vagas_proprietario if morador.tipo == 'proprietario' else config.vagas_inquilino
            for i in range(num_vagas):
                vaga = VagaGaragem(
                    numero=f"{morador.casa}{chr(65+i)}",
                    tipo=morador.tipo,
                    morador_id=morador.id
                )
                db.session.add(vaga)
        
        # Cria vagas para visitantes
        for i in range(config.vagas_visitantes):
            db.session.add(VagaGaragem(
                numero=f"VIS{i+1:02d}",
                tipo='visitante'
            ))
        
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao criar vagas: {e}")
        return False
    
@event.listens_for(Morador, 'after_delete')
def delete_morador_files(mapper, connection, target):
    """Remove arquivos associados quando um morador é deletado"""
    for attr in ['foto_morador', 'foto_placa']:
        filepath = getattr(target, attr)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError as e:
                current_app.logger.error(f"Erro ao deletar arquivo {filepath}: {e}")

@event.listens_for(Veiculo, 'after_delete')
def liberar_vaga_veiculo(mapper, connection, target):
    """Libera vaga quando um veículo é deletado"""
    if target.vaga:
        target.vaga.ocupada = False
        target.vaga.veiculo_id = None
        db.session.commit()