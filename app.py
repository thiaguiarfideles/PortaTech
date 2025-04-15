import logging
from venv import logger
from flask import Flask, jsonify, render_template, request, redirect, url_for, send_file, flash
from flask_cors import cross_origin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from flask import Blueprint
import re

from datetime import datetime, timedelta
from email.message import EmailMessage
import os, json, smtplib, pandas as pd
from io import BytesIO
import base64
import face_recognition
import easyocr
from flask import jsonify
import cv2
import os
import numpy as np
import sys
from flask_migrate import Migrate
from reconhecimento import (
    ReconhecimentoFacial, 
    ReconhecimentoPlacas, 
    GerenciadorAcesso,
    capturar_imagem,
    reconhecer_rosto,
    reconhecer_placa  # certifique-se de importar isso
)

# Configurações iniciais
app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Configura diretórios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIR_ROSTOS = os.path.join(BASE_DIR, "static", "rostos_moradores")
DIR_PLACAS = os.path.join(BASE_DIR, "static", "placas_moradores")
TEMP_DIR = os.path.join(BASE_DIR, "static", "temp")

# Banco de dados
with open('config.json') as f:
    config = json.load(f)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'condominio.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


db = SQLAlchemy(app)
migrate = Migrate(app, db)



# Blueprints
#auth_bp = Blueprint('auth', __name__)
#admin_bp = Blueprint('admin', __name__)

# Register them with the app BEFORE defining routes
#app.register_blueprint(auth_bp, url_prefix='/auth')
#app.register_blueprint(admin_bp, url_prefix='/admin')

# Função para inicializar os sistemas de reconhecimento
def init_recognition_systems(app):
    try:
        logger.info("Inicializando sistemas de reconhecimento...")
        
        # Initialize facial recognition
        logger.info("Inicializando reconhecimento facial...")
        rf = ReconhecimentoFacial()
        
        # Initialize plate recognition
        logger.info("Inicializando reconhecimento de placas...")
        rp = ReconhecimentoPlacas()
        
        # Initialize access manager
        logger.info("Inicializando gerenciador de acesso...")
        ga = GerenciadorAcesso(rf, rp)
        
        # Store in app config
        app.config['RECONHECIMENTO_FACIAL'] = rf
        app.config['RECONHECIMENTO_PLACAS'] = rp
        app.config['GERENCIADOR_ACESSO'] = ga
        
        logger.info("Sistemas de reconhecimento inicializados com sucesso")
        return rf, rp, ga
        
    except Exception as e:
        logger.error(f"Falha na inicialização dos sistemas: {str(e)}", exc_info=True)
        raise RuntimeError(f"Falha na inicialização: {str(e)}")
    
# ============================
# MODELOS DE BANCO
# ============================

def gerar_lista_casas():
    casas = []
    for i in range(1, 46):  # 45 blocos
        casas.append(str(100 + i))  # térreo: 101 a 145
        casas.append(str(200 + i))  # superior: 201 a 245
    return sorted(casas, key=int)

class Morador(db.Model):
    __tablename__ = 'morador'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    casa = db.Column(db.String(20), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'proprietario' ou 'inquilino'
    tem_carro = db.Column(db.Boolean, default=False)
    qtde_moradores = db.Column(db.Integer, nullable=False)
    foto_morador = db.Column(db.String(200))
    foto_placa = db.Column(db.String(200))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    veiculos = db.relationship('Veiculo', back_populates='morador', lazy='dynamic')
    acessos = db.relationship('Movimentacao', back_populates='morador', lazy='dynamic')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Garante que criado_em seja sempre um datetime válido
        if isinstance(self.criado_em, str):
            try:
                self.criado_em = datetime.fromisoformat(self.criado_em)
            except (ValueError, TypeError):
                self.criado_em = datetime.utcnow()
    


class VagaGaragem(db.Model):
    __tablename__ = 'vaga_garagem'
    
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(10), nullable=False, unique=True)
    casa = db.Column(db.String(20), nullable=False)
    placa = db.Column(db.String(20), nullable=True)
    ocupada = db.Column(db.Boolean, default=False)
    data_ocupacao = db.Column(db.DateTime, nullable=True)
    
    # Chave estrangeira e relação (corrigida)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'))
    veiculo = db.relationship('Veiculo', back_populates='vagas')

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

    def __repr__(self):
        return f'<Visitante {self.nome}>'

class Movimentacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # morador ou veiculo
    identificador = db.Column(db.String(100), nullable=False)  # nome ou placa
    status = db.Column(db.String(20), nullable=False)  # reconhecido ou nao_reconhecido
    entrada = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    saida = db.Column(db.DateTime)
    morador_id = db.Column(db.Integer, db.ForeignKey('morador.id'))
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'))
    morador = db.relationship('Morador', back_populates='acessos')
    veiculo = db.relationship('Veiculo', back_populates='acessos')
    
class Veiculo(db.Model):
    __tablename__ = 'veiculo'
    
    id = db.Column(db.Integer, primary_key=True)
    id_morador = db.Column(db.Integer, db.ForeignKey('morador.id'), nullable=False)
    placa = db.Column(db.String(20), nullable=False)
    tipo_veiculo = db.Column(db.String(50))
    qtde_veiculos = db.Column(db.Integer, nullable=False, default=1)
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relação com Morador
    morador = db.relationship('Morador', back_populates='veiculos')
    
    # Relação com VagaGaragem (corrigida)
    vagas = db.relationship('VagaGaragem', back_populates='veiculo')
    


# ============================
# ROTAS DO SISTEMA
# ============================
@app.cli.command('fix-dates')
def fix_dates():
    """Corrige datas inválidas no banco de dados"""
    with app.app_context():
        for morador in Morador.query.all():
            if isinstance(morador.criado_em, str):
                try:
                    morador.criado_em = datetime.fromisoformat(morador.criado_em)
                except ValueError:
                    morador.criado_em = datetime.utcnow()
        db.session.commit()
        print("Datas corrigidas com sucesso!")
        

@app.route('/system/health')
def health_check():
    return jsonify({
        'face_recognition': len(ReconhecimentoFacial.known_face_encodings) > 0,
        'plate_recognition': True,
        'database': True,
        'status': 'ok'
    })

@app.route('/debug/dbcheck')
def db_check():
    """Rota para verificação do banco de dados"""
    try:
        moradores = Morador.query.limit(5).all()
        result = {
            'moradores_count': Morador.query.count(),
            'sample_data': [
                {
                    'id': m.id,
                    'nome': m.nome,
                    'casa': m.casa,
                    'criado_em': str(m.criado_em),
                    'criado_em_type': type(m.criado_em).__name__
                } for m in moradores
            ],
            'db_status': 'OK'
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'db_status': 'ERROR'}), 500


@app.route('/urls')
def show_urls():
    return '<pre>' + '\n'.join(str(rule) for rule in app.url_map.iter_rules()) + '</pre>'


def inicializar_vagas():
    """Cria até 73 vagas incluindo vagas para visitantes"""
    with app.app_context():
        if not VagaGaragem.query.first():
            moradores = Morador.query.order_by(Morador.casa).all()
            vagas = []
            vaga_count = 0

            # Vagas para moradores (70 vagas)
            for morador in moradores:
                if morador.tipo == 'proprietario':
                    qtd_vagas = 2
                else:
                    qtd_vagas = 1

                for i in range(qtd_vagas):
                    letra = chr(65 + i)  # A, B, etc.
                    numero_vaga = f"{morador.casa}{letra}"
                    vagas.append(VagaGaragem(
                        numero=numero_vaga, 
                        casa=morador.casa, 
                        ocupada=False
                    ))
                    vaga_count += 1

                    if vaga_count >= 70:  # 70 vagas para moradores
                        break
                if vaga_count >= 70:
                    break

            # Vagas para visitantes (3 vagas)
            for i in range(1, 4):
                vagas.append(VagaGaragem(
                    numero=f"VIS{i}",
                    casa="VISITANTE",  # Identificador especial
                    ocupada=False
                ))
            
            db.session.bulk_save_objects(vagas)
            db.session.commit()
            print(f"{len(vagas)} vagas criadas com sucesso (70 moradores + 3 visitantes)")

                

@app.route('/')
def index():
    try:
        moradores = Morador.query.order_by(Morador.casa, Morador.nome).all()
        
        # Verificar e inicializar vagas se necessário
        try:
            vagas = VagaGaragem.query.all()
            total_vagas = len(vagas)
            vagas_livres = sum(1 for vaga in vagas if not vaga.ocupada)
        except:
            # Se a tabela não existir ainda
            total_vagas = 73
            vagas_livres = 0
            flash("Sistema de vagas não configurado ainda", "warning")
        
        visitantes = Visitante.query.order_by(Visitante.hora_entrada.desc()).limit(5).all()
        
        return render_template('index.html', 
                            moradores=moradores,
                            total_vagas=total_vagas,
                            vagas_livres=vagas_livres,
                            visitantes=visitantes)
                            
    except Exception as e:
        app.logger.error(f"Erro na rota index: {str(e)}")
        return render_template('index.html',
                            moradores=[],
                            total_vagas=73,
                            vagas_livres=0,
                            visitantes=[])
        


@app.cli.command('init-vagas')
def init_vagas():
    """Inicializa vagas de acordo com as regras de negócio"""
    if VagaGaragem.query.count() > 0:
        print("Vagas já inicializadas!")
        return
    
    vagas = []
    
    # Total de 73 vagas para 90 casas
    # Distribuição: 2 vagas para proprietários, 1 para inquilinos
    # Vamos assumir que temos 30 proprietários e 60 inquilinos (exemplo)
    
    # Vagas para proprietários (30 casas com 2 vagas cada)
    for i in range(1, 31):
        vagas.append(VagaGaragem(numero=f'P{i}A', casa=str(i), tipo='proprietario'))
        vagas.append(VagaGaragem(numero=f'P{i}B', casa=str(i), tipo='proprietario'))
    
    # Vagas para inquilinos (60 casas com 1 vaga cada)
    for i in range(31, 91):
        vagas.append(VagaGaragem(numero=f'I{i}', casa=str(i), tipo='inquilino'))
    
    db.session.bulk_save_objects(vagas)
    db.session.commit()
    print(f"{len(vagas)} vagas criadas com sucesso (30 proprietários com 2 vagas, 60 inquilinos com 1 vaga)")
            


def carregar_cache_rostos():
    global rostos_cache
    rostos_cache = {}

    base_path = os.path.join('static', 'rostos_moradores')
    for file in os.listdir(base_path):
        if file.startswith('morador_') and file.lower().endswith(('.jpg', '.jpeg', '.png')):
            caminho = os.path.join(base_path, file)
            imagem = face_recognition.load_image_file(caminho)
            encodings = face_recognition.face_encodings(imagem)

            if encodings:
                id_morador = int(file.replace('morador_', '').split('.')[0])
                rostos_cache[id_morador] = encodings[0]

    print(f"{len(rostos_cache)} rostos carregados no cache.")

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    casas_disponiveis = gerar_lista_casas()
    if request.method == 'POST':
        try:
            # Criar novo morador
            novo = Morador(
                nome=request.form['nome'],
                casa=request.form['casa'],
                tipo=request.form['tipo'],
                tem_carro=request.form.get('tem_carro') == 'Sim',
                qtde_moradores=int(request.form['qtde_moradores']),
                foto_morador="",
                foto_placa=None
            )
            db.session.add(novo)
            db.session.commit()

            # Processar imagem se existir
            if 'foto_webcam' in request.form and request.form['foto_webcam']:
                try:
                    foto_base64 = request.form['foto_webcam'].split(",")[1]
                    imagem_bytes = base64.b64decode(foto_base64)
                    
                    
                    # Salvar imagem temporariamente para verificação
                    temp_path = os.path.join(TEMP_DIR, f"temp_{novo.id}.jpg")
                    with open(temp_path, 'wb') as f:
                        f.write(imagem_bytes)
                    
                    # Verificar se a imagem é válida
                    img = cv2.imread(temp_path)
                    if img is None:
                        raise ValueError("Imagem inválida ou corrompida")
                    
                    # Adicionar rosto ao reconhecedor
                    if app.config['RECONHECIMENTO_FACIAL'].adicionar_rosto(novo.id, imagem_bytes):
                        novo.foto_morador = f"rostos_moradores/morador_{novo.id}.jpg"
                        db.session.commit()
                    
                    # Remover arquivo temporário
                    os.remove(temp_path)
                    
                except Exception as e:
                    logger.error(f"Erro ao processar imagem: {str(e)}")
                    flash('Morador cadastrado, mas houve um erro ao salvar a imagem facial', 'warning')

            flash('Morador cadastrado com sucesso!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cadastrar morador: {str(e)}")
            flash(f'Erro ao cadastrar morador: {str(e)}', 'danger')
            return render_template('cadastro.html',casas_disponiveis=casas_disponiveis, form_data=request.form)

    return render_template('cadastro.html', casas_disponiveis=casas_disponiveis)

@app.route('/editar/<int:morador_id>', methods=['GET', 'POST'])
def editar_morador(morador_id):
    morador = Morador.query.get_or_404(morador_id)
    casas_disponiveis = gerar_lista_casas()

    if request.method == 'POST':
        morador.nome = request.form['nome']
        morador.casa = request.form['casa']
        morador.tipo = request.form['tipo']
        morador.tem_carro = request.form.get('tem_carro') == 'Sim'
        morador.qtde_moradores = int(request.form['qtde_moradores'])
        db.session.commit()
        flash('Dados atualizados com sucesso!', 'success')
        return redirect(url_for('index'))

    return render_template('editar.html', morador=morador, casas_disponiveis=casas_disponiveis)



@app.route('/moradores')
def visualizar_moradores():
    # Agrupa moradores por casa
    casas = db.session.query(Morador.casa).distinct().all()
    moradores_por_casa = {}
    
    for casa in casas:
        moradores = Morador.query.filter_by(casa=casa[0]).order_by(Morador.nome).all()
        moradores_por_casa[casa[0]] = moradores
    
    return render_template('visualizar_moradores.html', moradores_por_casa=moradores_por_casa)


@app.route('/visitante', methods=['GET', 'POST'])
def visitante():
    if request.method == 'POST':
        agora = datetime.utcnow()
        tempo_limite = timedelta(hours=2 if agora.weekday() < 5 else 4)

        novo = Visitante(
            nome=request.form['nome'],
            casa_destino=request.form['casa_destino'],
            placa=request.form['placa'],
            hora_entrada=agora,
            hora_limite=agora + tempo_limite,
            foto_visitante=""  # será atualizado após salvar a imagem
        )
        db.session.add(novo)
        db.session.commit()

        # ✅ Captura e salva imagem do visitante via webcam
        if 'foto_webcam' in request.form and request.form['foto_webcam']:
            try:
                import base64
                os.makedirs("visitantes", exist_ok=True)
                foto_base64 = request.form['foto_webcam'].split(",")[1]
                caminho_foto = f"visitantes/visitante_{novo.id}.jpg"
                with open(caminho_foto, "wb") as f:
                    f.write(base64.b64decode(foto_base64))
                novo.foto_visitante = caminho_foto
                db.session.commit()
            except Exception as e:
                print("Erro ao salvar foto do visitante:", e)

        flash('Visitante cadastrado com sucesso!', 'info')
        return redirect(url_for('index'))

    return render_template('visitante.html')


@app.route('/editar_visitante/<int:visitante_id>', methods=['GET', 'POST'])
def editar_visitante(visitante_id):
    visitante = Visitante.query.get_or_404(visitante_id)

    if request.method == 'POST':
        visitante.nome = request.form['nome']
        visitante.casa_destino = request.form['casa_destino']
        visitante.placa = request.form['placa']
        
        # Atualizar tempo de permanência se necessário
        tempo_limite = timedelta(hours=2 if visitante.hora_entrada.weekday() < 5 else 4)
        visitante.hora_limite = visitante.hora_entrada + tempo_limite
        
        db.session.commit()
        flash('Dados do visitante atualizados com sucesso!', 'success')
        return redirect(url_for('visualizar_visitantes'))

    return render_template('editar_visitante.html', visitante=visitante)

@app.route('/visitantes')
def visualizar_visitantes():
    visitantes = Visitante.query.all()
    return render_template('visualizar_visitantes.html', visitantes=visitantes)

@app.route('/veiculo/cadastrar', methods=['GET', 'POST'])
def cadastrar_veiculo():
    moradores = Morador.query.all()

    if request.method == 'POST':
        novo_veiculo = Veiculo(
            id_morador=request.form['id_morador'],
            placa=request.form['placa'],
            tipo_veiculo=request.form['tipo_veiculo'],
            qtde_veiculos=1
        )
        db.session.add(novo_veiculo)
        db.session.commit()
        flash("Veículo cadastrado com sucesso!", "success")
        return redirect(url_for('index'))

    return render_template('cadastrar_veiculo.html', moradores=moradores)


@app.route('/veiculo/editar/<int:veiculo_id>', methods=['GET', 'POST'])
def editar_veiculo(veiculo_id):
    veiculo = Veiculo.query.get_or_404(veiculo_id)
    moradores = Morador.query.all()

    if request.method == 'POST':
        veiculo.placa = request.form['placa']
        veiculo.tipo_veiculo = request.form['tipo_veiculo']
        veiculo.id_morador = request.form['id_morador']
        db.session.commit()
        flash("Veículo atualizado com sucesso!", "info")
        return redirect(url_for('index'))

    return render_template('editar_veiculo.html', veiculo=veiculo, moradores=moradores)

@app.route('/veiculos')
def visualizar_veiculos():
    veiculos = Veiculo.query.all()
    return render_template('visualizar_veiculos.html', veiculos=veiculos)

@app.route('/detectar_rosto', methods=['POST'])
def detectar_rosto():
    if 'image' not in request.files:
        return jsonify({'face_detected': False})
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'face_detected': False})
    
    nparr = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_img)
    
    return jsonify({'face_detected': len(face_locations) > 0})


def verificar_entrada(self, imagem_bytes, tipo):
    """
    Verifica uma tentativa de entrada
    Args:
        imagem_bytes: Bytes da imagem capturada
        tipo: 'facial' ou 'placa'
    Returns:
        Dicionário com resultado do reconhecimento
    """
    try:
        if tipo == 'facial':
            # Get recognition results
            results = self.reconhecimento_facial.processar_imagem(imagem_bytes)
            
            if results and len(results) > 0:
                # Extract the first match
                match = results[0]
                morador_id = int(match['id'].replace('morador_', ''))  # Convert to integer
                
                return {
                    'status': 'liberado',
                    'tipo': 'facial',
                    'id_morador': morador_id,  # Now an integer
                    'mensagem': 'Reconhecimento facial bem-sucedido'
                }
                
        elif tipo == 'placa':
            placa = self.reconhecimento_placas.reconhecer_de_imagem(imagem_bytes)
            if placa:
                return {
                    'status': 'liberado',
                    'tipo': 'placa',
                    'placa': placa,
                    'mensagem': 'Placa reconhecida com sucesso'
                }
                
        return {
            'status': 'negado',
            'mensagem': 'Não reconhecido'
        }
        
    except Exception as e:
        logger.error(f"Erro na verificação de entrada: {str(e)}")
        return {
            'status': 'erro',
            'mensagem': 'Erro no processamento'
        }

def verificar_por_reconhecimento_facial(imagem_bytes):
    id_morador = reconhecer_rosto(imagem_bytes)

    if id_morador:
        id_extraido = int(id_morador.replace('morador_', ''))
        return {
            'status': 'liberado',
            'tipo': 'facial',
            'id_morador': id_extraido
        }

    return {
        'status': 'negado',
        'mensagem': 'Rosto não reconhecido'
    }


def verificar_por_reconhecimento_placa(imagem_bytes):
    placa = reconhecer_placa(imagem_bytes)

    if placa:
        return {
            'status': 'liberado',
            'tipo': 'veiculo',
            'placa': placa
        }

    return {
        'status': 'negado',
        'mensagem': 'Placa não reconhecida'
    }
    
@app.route('/verificar_entrada', methods=['GET', 'POST'])
def verificar_entrada():
    if request.method == 'GET':
        return render_template('verificar_entrada.html')
    
    elif request.method == 'POST':
        try:
            # Get the image data
            imagem_bytes = obter_imagem_do_request(request)
            if isinstance(imagem_bytes, tuple):  # If it's an error response
                return imagem_bytes

            # Get the verification type from form data
            tipo = request.form.get('tipo', 'facial')  # Default to 'facial' if not specified
            
            # Validate tipo
            if tipo not in ('facial', 'placa'):
                return jsonify({
                    'status': 'erro', 
                    'mensagem': 'Tipo de verificação inválido. Use "facial" ou "placa"'
                }), 400
            
            # Initialize GerenciadorAcesso if not already done
            ga = app.config.get('GERENCIADOR_ACESSO')
            if ga is None:
                raise RuntimeError("Gerenciador de Acesso não inicializado")
            
            # Call the verification with both arguments
            resultado = ga.verificar_entrada(imagem_bytes, tipo)
            
            # Validate the response
            if not resultado or not isinstance(resultado, dict):
                raise ValueError("Resposta inválida do Gerenciador de Acesso")
                
            if 'status' not in resultado:
                raise ValueError("Resposta do Gerenciador de Acesso sem status")
                
            if resultado['status'] != 'liberado':
                registrar_acesso('desconhecido', None, False)
                return jsonify(resultado), 401

            # Process successful recognition
            if resultado.get('tipo') == 'facial':
                return processar_reconhecimento_facial(resultado)
            elif resultado.get('tipo') == 'placa':
                return processar_reconhecimento_veiculo(resultado)
                
            return jsonify({
                'status': 'erro',
                'mensagem': 'Tipo de reconhecimento inválido na resposta'
            }), 400
            
        except Exception as e:
            logger.error(f"Erro na verificação: {str(e)}", exc_info=True)
            return jsonify({
                'status': 'erro', 
                'mensagem': 'Erro interno no servidor',
                'detalhes': str(e)
            }), 500

# Funções auxiliares

def obter_imagem_do_request(req):
    if 'image' not in req.files:
        return jsonify({'error': 'Nenhuma imagem enviada'}), 400

    arquivo = req.files['image']

    if arquivo.filename == '':
        return jsonify({'status': 'erro', 'mensagem': 'Nenhum arquivo selecionado'}), 400

    if not arquivo.content_type.startswith('image/'):
        return jsonify({'status': 'erro', 'mensagem': 'Tipo de arquivo não suportado'}), 400

    return arquivo.read()


def processar_reconhecimento_facial(resultado):
    """Process facial recognition results"""
    try:
        morador_id = resultado.get('id_morador')
        if not morador_id:
            raise ValueError("ID do morador não encontrado na resposta")
            
        morador = Morador.query.get(morador_id)
        if not morador:
            raise ValueError(f"Morador com ID {morador_id} não encontrado")
            
        # Registrar acesso
        registrar_acesso('facial', morador_id, True)
        
        return jsonify({
            'status': 'liberado',
            'tipo': 'facial',
            'nome': morador.nome,
            'casa': morador.casa,
            'mensagem': 'Acesso permitido'
        })
        
    except Exception as e:
        logger.error(f"Erro no processamento facial: {str(e)}")
        return jsonify({
            'status': 'erro',
            'mensagem': str(e)
        }), 500

def processar_reconhecimento_veiculo(resultado):
    """Process vehicle recognition results"""
    try:
        placa = resultado.get('placa')
        if not placa:
            raise ValueError("Placa não encontrada na resposta")
            
        veiculo = Veiculo.query.filter_by(placa=placa).first()
        if not veiculo:
            raise ValueError(f"Veículo com placa {placa} não encontrado")
            
        # Registrar acesso
        registrar_acesso('veiculo', veiculo.id, True)
        
        return jsonify({
            'status': 'liberado',
            'tipo': 'placa',
            'placa': placa,
            'morador': veiculo.morador.nome,
            'casa': veiculo.morador.casa,
            'mensagem': 'Acesso permitido'
        })
        
    except Exception as e:
        logger.error(f"Erro no processamento de veículo: {str(e)}")
        return jsonify({
            'status': 'erro',
            'mensagem': str(e)
        }), 500


def registrar_acesso(tipo, id_referencia, reconhecido):
    """Registra o acesso no banco de dados, baseado no tipo e se foi reconhecido."""
    try:
        identificador = obter_identificador(tipo, id_referencia)

        novo_registro = Movimentacao(
            tipo=tipo,
            identificador=identificador,
            status='reconhecido' if reconhecido else 'nao_reconhecido'
        )

        db.session.add(novo_registro)
        db.session.commit()
        logger.info(f"Acesso registrado com sucesso: {tipo} - {identificador}")
        return True

    except Exception as e:
        logger.error(f"Erro ao registrar acesso: {str(e)}", exc_info=True)
        db.session.rollback()
        return False

def obter_identificador(tipo, id_referencia):
    """Retorna o identificador legível com base no tipo."""
    if tipo == 'facial':
        morador = Morador.query.get(id_referencia)
        return morador.nome if morador else "Morador não identificado"

    elif tipo == 'veiculo':
        veiculo = Veiculo.query.get(id_referencia)
        return veiculo.placa if veiculo else "Veículo não identificado"

    return "Desconhecido"
@app.route('/painel_vagas_visual')
def painel_vagas_visual():
    # Forçar recarregamento do banco
    db.session.expire_all()
    
    # Obter todas as vagas com join correto
    vagas = db.session.query(
        VagaGaragem,
        Veiculo,
        Morador
    ).outerjoin(
        Veiculo, VagaGaragem.veiculo_id == Veiculo.id
    ).outerjoin(
        Morador, Veiculo.id_morador == Morador.id
    ).order_by(
        VagaGaragem.numero
    ).all()
    
    # Preparar dados para template
    vagas_data = []
    for vaga, veiculo, morador in vagas:
        vagas_data.append({
            'id': vaga.id,
            'numero': vaga.numero,
            'ocupada': vaga.ocupada,
            'placa': vaga.placa,
            'veiculo_tipo': veiculo.tipo_veiculo if veiculo else None,
            'morador_nome': morador.nome if morador else None
        })
    
    # Contagem
    total_vagas = len(vagas_data)
    vagas_ocupadas = sum(1 for v in vagas_data if v['ocupada'])
    vagas_livres = total_vagas - vagas_ocupadas
    
    return render_template(
        'painel_vagas_visual.html',
        vagas=vagas_data,
        total_vagas=total_vagas,
        vagas_livres=vagas_livres,
        vagas_ocupadas=vagas_ocupadas,
        now=datetime.now(timezone.utc)
    )


@app.route('/api/vaga_status/<int:vaga_id>')
def vaga_status(vaga_id):
    vaga = VagaGaragem.query.get_or_404(vaga_id)
    return jsonify({
        'id': vaga.id,
        'numero': vaga.numero,
        'ocupada': vaga.ocupada,
        'placa': vaga.placa,
        'veiculo_id': vaga.veiculo_id,
        'casa': vaga.casa
    })
    

def reconhecer_placa_de_imagem(imagem_bytes):
    """Reconhece placa de veículo a partir de bytes de imagem"""
    try:
        # Converter bytes para imagem OpenCV
        nparr = np.frombuffer(imagem_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Pré-processamento da imagem
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        
        # Salvar temporariamente para processamento
        temp_path = os.path.join('static', 'temp', 'placa_temp.jpg')
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        cv2.imwrite(temp_path, gray)
        
        # Usar EasyOCR para reconhecer texto
        reader = easyocr.Reader(['pt'])
        resultados = reader.readtext(gray)
        
        # Padrões de placas brasileiras
        padroes = [
            r'[A-Z]{3}\d{4}',      # ABC1234 (modelo antigo)
            r'[A-Z]{3}\d[A-Z]\d{2}' # ABC1D23 (modelo Mercosul)
        ]
        
        # Procurar por padrões de placas
        for resultado in resultados:
            texto = re.sub(r'[^a-zA-Z0-9]', '', resultado[1]).upper()
            for padrao in padroes:
                if re.fullmatch(padrao, texto):
                    # Formatar placa no padrão brasileiro
                    placa = f"{texto[:3]}-{texto[3:]}"
                    return placa
                    
        return None
        
    except Exception as e:
        app.logger.error(f"Erro no reconhecimento de placa: {str(e)}")
        return None
    finally:
        # Limpar arquivo temporário
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)


def registrar_entrada_visitante(placa):
    """Registra entrada de veículo de visitante com vaga temporária"""
    try:
        # Verificar se já está estacionado
        if Movimentacao.query.filter_by(identificador=placa, saida=None).first():
            return False
        
        # Encontrar primeira vaga livre de visitante (vaga sem casa associada ou vaga especial)
        vaga = VagaGaragem.query.filter(
            (VagaGaragem.ocupada == False) & 
            ((VagaGaragem.casa == None) | (VagaGaragem.casa == 'VISITANTE'))
        ).first()
        
        if not vaga:
            app.logger.warning("Nenhuma vaga disponível para visitantes")
            return False
        
        # Registrar entrada
        nova_mov = Movimentacao(
            tipo='visitante',
            identificador=placa,
            status='manual',
            entrada=datetime.utcnow()
        )
        
        # Atualizar vaga
        vaga.ocupada = True
        vaga.placa = placa
        vaga.data_ocupacao = datetime.utcnow()
        
        db.session.add(nova_mov)
        db.session.commit()
        db.session.refresh(vaga)
        return True
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao registrar entrada de visitante: {str(e)}")
        return False


def registrar_entrada_veiculo(placa):
    """Registra entrada com validação de vagas por tipo de morador"""
    try:
        # Verificar se já está estacionado
        if Movimentacao.query.filter_by(identificador=placa, saida=None).first():
            app.logger.warning(f"Veículo {placa} já está estacionado")
            return False
        
        veiculo = Veiculo.query.filter_by(placa=placa).first()
        
        # Se for visitante
        if not veiculo or not veiculo.morador:
            app.logger.info(f"Registrando entrada de visitante com placa {placa}")
            return registrar_entrada_visitante(placa)
        
        # Processamento para moradores
        morador = veiculo.morador
        vagas_casa = VagaGaragem.query.filter_by(casa=morador.casa).all()
        
        # Verificar limite por tipo de morador
        limite = 2 if morador.tipo == 'proprietario' else 1
        
        # Contar vagas ocupadas pelo morador
        vagas_ocupadas = sum(1 for v in vagas_casa if v.ocupada and v.veiculo and v.veiculo.morador.id == morador.id)
        
        if vagas_ocupadas >= limite:
            app.logger.warning(f"Limite de {limite} vagas atingido para morador {morador.nome}")
            return False
        
        # Encontrar vaga disponível para a casa
        vaga = next((v for v in vagas_casa if not v.ocupada), None)
        
        if not vaga:
            app.logger.warning(f"Nenhuma vaga disponível para casa {morador.casa}")
            return False
            
        # Registrar movimento
        nova_mov = Movimentacao(
            tipo='veiculo',
            identificador=placa,
            status='manual',
            entrada=datetime.now(timezone.utc)
        )
        
        # Atualizar vaga
        vaga.ocupada = True
        vaga.placa = placa
        vaga.veiculo_id = veiculo.id
        vaga.data_ocupacao = datetime.now(timezone.utc)
        
        db.session.add(nova_mov)
        db.session.commit()
        db.session.refresh(vaga)
        
        app.logger.info(f"Entrada registrada para veículo {placa} na vaga {vaga.numero}")
        return True
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao registrar entrada de veículo: {str(e)}", exc_info=True)
        return False


@app.route('/painel_porteiro', methods=['GET', 'POST'])
def painel_porteiro():
    if request.method == 'POST':
        placa = request.form.get('placa')
        acao = request.form.get('acao', 'saida')  # Default para manter compatibilidade
        
        if placa:
            # Formatar placa (remover espaços e traços)
            placa = re.sub(r'[^a-zA-Z0-9]', '', placa).upper()
            
            veiculo = Veiculo.query.filter_by(placa=placa).first()
            
            if veiculo or acao == 'saida':  # Permitir saída mesmo sem veículo cadastrado
                if acao == 'entrada':
                    if registrar_entrada_veiculo(placa):
                        flash(f"Entrada do veículo {placa} registrada com sucesso!", "success")
                    else:
                        flash("Veículo já está estacionado!", "warning")
                else:  # ação de saída
                    if registrar_saida_veiculo(placa):
                        flash(f"Saída do veículo {placa} registrada com sucesso!", "success")
                    else:
                        flash("Veículo não estava estacionado!", "warning")
            else:
                flash("Placa não encontrada no sistema!", "warning")
        return redirect(url_for('painel_porteiro'))
    
    # Obter veículos estacionados - MODIFICADO
    veiculos_estacionados = db.session.query(
        Movimentacao, Morador, Veiculo
    ).join(
        Veiculo, Movimentacao.identificador == Veiculo.placa
    ).join(
        Morador, Veiculo.id_morador == Morador.id
    ).filter(
        Movimentacao.tipo == 'veiculo',
        Movimentacao.status == 'reconhecido',
        Movimentacao.saida == None
    ).order_by(
        Movimentacao.entrada.desc()
    ).all()
    
    # Obter histórico recente - MODIFICADO
    historico = db.session.query(
        Movimentacao, Morador, Veiculo
    ).outerjoin(
        Veiculo, Movimentacao.identificador == Veiculo.placa
    ).outerjoin(
        Morador, Veiculo.id_morador == Morador.id
    ).filter(
        Movimentacao.tipo == 'veiculo'
    ).order_by(
        Movimentacao.entrada.desc()
    ).limit(10).all()
    
    # Preparar os dados para o template
    veiculos_estacionados_data = []
    for mov, morador, veiculo in veiculos_estacionados:
        veiculos_estacionados_data.append({
            'movimentacao': mov,
            'morador': morador,
            'veiculo': veiculo,
            'identificador': mov.identificador
        })
    historico_data = []
    for mov, morador, veiculo in historico:
        historico_data.append({
            'movimentacao': mov,
            'morador': morador,
            'veiculo': veiculo,
            'identificador': mov.identificador
        })    
        
    
    return render_template(
        'painel_porteiro.html',
        veiculos_estacionados=veiculos_estacionados_data,
        historico=historico_data,
        agora=datetime.now()
    )

def registrar_saida_veiculo(placa):
    """Registra a saída de um veículo"""
    registro = Movimentacao.query.filter_by(
        tipo='veiculo',
        identificador=placa,
        saida=None
    ).order_by(Movimentacao.entrada.desc()).first()
    
    if registro:
        registro.saida = datetime.utcnow()
        
        # Liberar vaga associada
        vaga = VagaGaragem.query.filter_by(placa=placa).first()
        if vaga:
            vaga.ocupada = False
            vaga.placa = None
            vaga.data_ocupacao = None
            vaga.veiculo_id = None
        
        try:
            db.session.commit()
            app.logger.info(f"Saída do veículo {placa} registrada com sucesso")
            return True
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao registrar saída: {str(e)}")
            return False
    return False

def formatar_placa(placa):
    """Formata a placa para o padrão brasileiro"""
    placa = re.sub(r'[^a-zA-Z0-9]', '', placa).upper()
    if len(placa) == 7:
        return f"{placa[:3]}-{placa[3:]}"
    return placa


@app.route('/reconhecer_placa', methods=['POST'])
def reconhecer_placa_api():
    if 'image' not in request.files:
        return jsonify({'error': 'Nenhuma imagem enviada'}), 400
    
    imagem_bytes = request.files['image'].read()
    placa = ReconhecimentoPlacas.reconhecer_de_imagem(imagem_bytes)
    
    if placa:
        return jsonify({'placa': placa})
    return jsonify({'error': 'Placa não reconhecida'}), 400

    
@app.route('/registrar_saida/<placa>')
def registrar_saida(placa):
    registro = Movimentacao.query.filter_by(tipo='veiculo', identificador=placa, saida=None).order_by(Movimentacao.entrada.desc()).first()
    if registro:
        registro.saida = datetime.utcnow()
        db.session.commit()
        return f"Saída registrada para: {placa}"
    return f"Nenhum registro de entrada encontrado para {placa}"

@app.route('/historico')
def historico():
    # Obter parâmetros de filtro
    filtro = request.args.get('filtro', '')
    tipo = request.args.get('tipo', 'todos')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    # Construir query base
    query = Movimentacao.query
    
    # Aplicar filtros
    if filtro:
        query = query.filter(Movimentacao.identificador.ilike(f"%{filtro}%"))
    
    if tipo != 'todos':
        query = query.filter(Movimentacao.tipo == tipo)
    
    if data_inicio:
        try:
            inicio = datetime.strptime(data_inicio, '%Y-%m-%d')
            query = query.filter(Movimentacao.entrada >= inicio)
        except ValueError:
            pass
    
    if data_fim:
        try:
            fim = datetime.strptime(data_fim, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Movimentacao.entrada <= fim)
        except ValueError:
            pass
    
    # Ordenar e paginar
    registros = query.order_by(Movimentacao.entrada.desc()).all()
    
    return render_template(
        "historico.html",
        registros=registros,
        filtro=filtro,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim
    )


@app.route('/enviar_email', methods=['POST'])
def enviar_email():
    destinatario = request.form.get('destinatario')
    df = pd.read_sql(Movimentacao.query.statement, db.session.bind)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    msg = EmailMessage()
    msg['Subject'] = "Histórico do condomínio"
    msg['From'] = config['email']['from']
    msg['To'] = destinatario
    msg.set_content("Segue em anexo o histórico solicitado.")
    msg.add_attachment(output.read(), maintype='application', subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename='movimentacoes.xlsx')

    with smtplib.SMTP_SSL(config['email']['smtp_server'], config['email']['smtp_port']) as smtp:
        smtp.login(config['email']['from'], config['email']['password'])
        smtp.send_message(msg)

    return f"E-mail enviado para {destinatario}"

# Rodar o app
if __name__ == '__main__':
    with app.app_context():
        try:
            # Initialize database
            db.create_all()
            
            # Initialize recognition systems
            rf, rp, ga = init_recognition_systems(app)
            
            # Make sure templates are in the right location
            app.template_folder = 'templates'
            
            logger.info("Aplicação inicializada com sucesso")
            
        except Exception as e:
            logger.critical(f"Falha na inicialização: {str(e)}")
            sys.exit(1)

    app.run(debug=True, use_reloader=False)