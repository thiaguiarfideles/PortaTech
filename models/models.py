# models.py
from datetime import datetime, timezone
from sqlalchemy import event
from sqlalchemy.orm import validates
from app import db  # Make sure this imports correctly
import os
from werkzeug.utils import secure_filename
from typing import Optional

def gerar_lista_casas():
    casas = []
    for i in range(1, 46):  # 45 blocos
        casas.append(str(100 + i))  # térreo: 101 a 145
        casas.append(str(200 + i))  # superior: 201 a 245
    return sorted(casas, key=int)

# ============================
# MODELOS DE BANCO
# ============================

def gerar_lista_casas():
    casas = []
    for i in range(1, 46):  # 45 blocos
        casas.append(str(100 + i))  # térreo: 101 a 145
        casas.append(str(200 + i))  # superior: 201 a 245
    return sorted(casas, key=int)

from datetime import datetime, timezone
from sqlalchemy import event
from sqlalchemy.orm import validates
from app import db  # Assuming your db instance is in app.py
import os
from werkzeug.utils import secure_filename
from typing import List, Optional

class Morador(db.Model):
    __tablename__ = 'morador'
    
    # Constants
    TIPOS_VALIDOS = ['proprietario', 'inquilino']
    FOTO_DIR = 'static/rostos_moradores'
    PLACA_DIR = 'static/placas_moradores'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    
    # Columns
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, index=True)  # Added index for faster searches
    casa = db.Column(db.String(20), nullable=False, index=True)   # Added index
    tipo = db.Column(db.String(20), nullable=False)
    tem_carro = db.Column(db.Boolean, default=False)
    qtde_moradores = db.Column(db.Integer, nullable=False, default=1)  # Added default
    foto_morador = db.Column(db.String(255))  # Increased length for paths
    foto_placa = db.Column(db.String(255))    # Increased length
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    atualizado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), 
                            onupdate=lambda: datetime.now(timezone.utc))  # Track updates
    
    # Relationships
    veiculos = db.relationship('Veiculo', back_populates='morador', 
                            lazy='dynamic', cascade='all, delete-orphan')
    acessos = db.relationship('Movimentacao', back_populates='morador', 
                            lazy='dynamic', order_by='desc(Movimentacao.entrada)')
    
    def __init__(self, **kwargs):
        """
        Initialize with automatic timestamp handling and file path processing
        """
        # Process file paths if provided
        if 'foto_morador_file' in kwargs:
            kwargs['foto_morador'] = self._process_upload(kwargs.pop('foto_morador_file'), self.FOTO_DIR)
            
        if 'foto_placa_file' in kwargs:
            kwargs['foto_placa'] = self._process_upload(kwargs.pop('foto_placa_file'), self.PLACA_DIR)
            
        super().__init__(**kwargs)
        
        # Ensure created_at is always a valid datetime
        if isinstance(self.criado_em, str):
            try:
                self.criado_em = datetime.fromisoformat(self.criado_em)
            except (ValueError, TypeError):
                self.criado_em = datetime.now(timezone.utc)
    
    @validates('tipo')
    def validate_tipo(self, key, tipo):
        """Validate resident type"""
        if tipo not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo must be one of: {', '.join(self.TIPOS_VALIDOS)}")
        return tipo
    
    @validates('qtde_moradores')
    def validate_qtde_moradores(self, key, qtde):
        """Validate number of residents"""
        if not isinstance(qtde, int) or qtde < 1:
            raise ValueError("Quantidade de moradores deve ser um inteiro positivo")
        return qtde
    
    def _process_upload(self, file, upload_dir: str) -> Optional[str]:
        """Process uploaded file and return saved path"""
        if file and self._allowed_file(file.filename):
            filename = secure_filename(f"morador_{self.id}_{file.filename}")
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            return filepath
        return None
    
    def _allowed_file(self, filename):
        """Check if file extension is allowed"""
        return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS
    
    @property
    def foto_morador_url(self):
        """Get URL for resident photo"""
        if self.foto_morador:
            return url_for('static', filename=os.path.relpath(self.foto_morador, 'static'))
        return None
    
    @property
    def foto_placa_url(self):
        """Get URL for license plate photo"""
        if self.foto_placa:
            return url_for('static', filename=os.path.relpath(self.foto_placa, 'static'))
        return None
    
    def to_dict(self):
        """Convert model to dictionary for API responses"""
        return {
            'id': self.id,
            'nome': self.nome,
            'casa': self.casa,
            'tipo': self.tipo,
            'tem_carro': self.tem_carro,
            'qtde_moradores': self.qtde_moradores,
            'foto_morador_url': self.foto_morador_url,
            'foto_placa_url': self.foto_placa_url,
            'criado_em': self.criado_em.isoformat(),
            'atualizado_em': self.atualizado_em.isoformat() if self.atualizado_em else None,
            'veiculos_count': self.veiculos.count(),
            'acessos_count': self.acessos.count()
        }
    
    def __repr__(self):
        return f'<Morador {self.id} - {self.nome} ({self.casa})>'

# Event listeners for cleanup
@event.listens_for(Morador, 'after_delete')
def delete_associated_files(mapper, connection, target):
    """Delete associated files when resident is deleted"""
    for attr in ['foto_morador', 'foto_placa']:
        filepath = getattr(target, attr)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError as e:
                current_app.logger.error(f"Error deleting file {filepath}: {e}")
    


class VagaGaragem(db.Model):
    __tablename__ = 'vaga_garagem'
    
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(10), nullable=False, unique=True)
    casa = db.Column(db.String(20), nullable=False)
    placa = db.Column(db.String(20), nullable=True)
    ocupada = db.Column(db.Boolean, default=False)
    data_ocupacao = db.Column(db.DateTime, nullable=True)
    tipo = db.Column(db.String(20))  # 'proprietario', 'inquilino', 'visitante'
    
    # Relações
    morador_id = db.Column(db.Integer, db.ForeignKey('morador.id'))
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'))
    visitante_id = db.Column(db.Integer, db.ForeignKey('visitantes.id'))
    
    morador = db.relationship('Morador', backref='vagas')
    veiculo = db.relationship('Veiculo', back_populates='vaga')
    visitante = db.relationship('Visitante', backref='vaga')


    def __repr__(self):
        return f'<VagaGaragem {self.numero} - Casa {self.casa}>'

class Visitante(db.Model):
    __tablename__ = 'visitantes'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    casa_destino = db.Column(db.String(20), nullable=False)
    hora_entrada = db.Column(db.DateTime, default=datetime.utcnow)
    hora_limite = db.Column(db.DateTime, nullable=False)
    placa = db.Column(db.String(20), nullable=True)
    foto_visitante = db.Column(db.String(200), nullable=True)
    
    # Add relationship with Movimentacao
    acessos = db.relationship('Movimentacao', back_populates='visitante')

    def __repr__(self):
        return f'<Visitante {self.nome}>'

class Movimentacao(db.Model):
    __tablename__ = 'movimentacao'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # 'facial' ou 'placa'
    identificador = db.Column(db.String(100), nullable=False)  # ID morador ou placa
    status = db.Column(db.String(20), nullable=False)  # 'reconhecido' ou 'negado'
    entrada = db.Column(db.DateTime, default=datetime.utcnow)
    saida = db.Column(db.DateTime)
    
    # Relações
    morador_id = db.Column(db.Integer, db.ForeignKey('morador.id'))
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'))
    visitante_id = db.Column(db.Integer, db.ForeignKey('visitantes.id', name='fk_movimentacao_visitante'))  # Added constraint name
    
    morador = db.relationship('Morador', back_populates='acessos')
    veiculo = db.relationship('Veiculo', back_populates='acessos')
    visitante = db.relationship('Visitante', back_populates='acessos')  # Change backref to back_populates
    
class Veiculo(db.Model):
    __tablename__ = 'veiculo'
    
    id = db.Column(db.Integer, primary_key=True)
    id_morador = db.Column(db.Integer, db.ForeignKey('morador.id'), nullable=False)
    placa = db.Column(db.String(20), nullable=False, unique=True)
    tipo_veiculo = db.Column(db.String(50))
    qtde_veiculos = db.Column(db.Integer, nullable=False, default=1)
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relações
    morador = db.relationship('Morador', back_populates='veiculos')
    acessos = db.relationship('Movimentacao', back_populates='veiculo')
    vaga = db.relationship('VagaGaragem', back_populates='veiculo', uselist=False)
    
class ConfiguracaoVagas(db.Model):
    __tablename__ = 'configuracao_vagas'
    
    id = db.Column(db.Integer, primary_key=True)
    total_vagas = db.Column(db.Integer, nullable=False)
    vagas_proprietario = db.Column(db.Integer, nullable=False, default=2)
    vagas_inquilino = db.Column(db.Integer, nullable=False, default=1)
    vagas_visitantes = db.Column(db.Integer, nullable=False, default=3)
    ultima_atualizacao = db.Column(db.DateTime, default=datetime.now(timezone.utc))
