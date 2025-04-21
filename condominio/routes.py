# routes.py
from .extensions import db

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from .models import Morador, VagaGaragem, Visitante, Movimentacao, Veiculo, ConfiguracaoVagas
from werkzeug.utils import secure_filename

from flask import (
    Flask, 
    current_app,
    jsonify, 
    render_template, 
    request, 
    redirect, 
    url_for, 
    send_file, 
    flash, 
    Blueprint
)
from datetime import datetime, timedelta, timezone
import os
import re
import logging
import numpy as np
import cv2
import face_recognition
import easyocr
import pandas as pd
from io import BytesIO
from email.message import EmailMessage
import smtplib
import json


# Configuração inicial
routes_bp = Blueprint('routes', __name__)
logger = logging.getLogger(__name__)

# ============================
# FUNÇÕES AUXILIARES
# ============================

def validar_placa(placa):
    placa = placa.upper().strip()
    if len(placa) not in (7, 8):  # Account for hyphen
        return False
    
    # Lista de estados brasileiros para validar placas antigas
    estados_brasileiros = ['AC','AL','AP','AM','BA','CE','DF','ES',
                          'GO','MA','MT','MS','MG','PA','PB','PR',
                          'PE','PI','RJ','RN','RS','RO','RR','SC',
                          'SP','SE','TO']
    
    # Verifica se é placa mercosul (ABC1D23)
    if re.match(r'^[A-Z]{3}\d[A-Z0-9]\d{2}$', placa):
        return True
        
    # Verifica se é placa antiga (ABC1234)
    if re.match(r'^[A-Z]{3}\d{4}$', placa):
        return True
        
    # Verifica se é placa modelo antigo com sigla de estado (AAA9999)
    if len(placa) == 7 and placa[:3] in estados_brasileiros:
        return True
        
    return False
print(validar_placa("ABC1D23"))  # True (Mercosul)
print(validar_placa("ABC1234"))  # True (Antigo)
print(validar_placa("AB1C23"))   # False (inválido)

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def gerar_lista_casas():
    """Gera lista de casas disponíveis para cadastro"""
    casas = []
    for i in range(1, 46):  # 45 blocos
        casas.append(str(100 + i))  # térreo: 101 a 145
        casas.append(str(200 + i))  # superior: 201 a 245
    return sorted(casas, key=int)

def obter_imagem_do_request(req):
    if 'image' not in req.files:
        return jsonify({'error': 'Nenhuma imagem enviada'}), 400

    arquivo = req.files['image']
    if arquivo.filename == '':
        return jsonify({'status': 'erro', 'mensagem': 'Nenhum arquivo selecionado'}), 400

    if not arquivo.content_type.startswith('image/'):
        return jsonify({'status': 'erro', 'mensagem': 'Tipo de arquivo não suportado'}), 400

    return arquivo.read()

def registrar_acesso(tipo, id_referencia, reconhecido):
    """Registra o acesso no banco de dados"""
    from models import Movimentacao
    from extensions import db
    
    try:
        if tipo == 'facial':
            identificador = f"morador_{id_referencia}"
            morador_id = id_referencia
            veiculo_id = None
        elif tipo == 'placa':
            identificador = id_referencia
            veiculo = Veiculo.query.filter_by(placa=id_referencia).first()
            morador_id = veiculo.id_morador if veiculo else None
            veiculo_id = veiculo.id if veiculo else None
        else:
            identificador = "desconhecido"
            morador_id = None
            veiculo_id = None

        novo_registro = Movimentacao(
            tipo=tipo,
            identificador=identificador,
            status='reconhecido' if reconhecido else 'negado',
            entrada=datetime.now(timezone.utc),
            morador_id=morador_id,
            veiculo_id=veiculo_id
        )

        db.session.add(novo_registro)
        db.session.commit()
        return novo_registro
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erro ao registrar acesso: {str(e)}", exc_info=True)
        return None

def formatar_placa(placa):
    placa = re.sub(r'[^a-zA-Z0-9]', '', placa).upper()
    if len(placa) == 7:
        return f"{placa[:3]}-{placa[3:]}"
    return placa

# ============================
# ROTAS PRINCIPAIS
# ============================


@routes_bp.route('/')
def index():
    from .models import Morador, Visitante, ConfiguracaoVagas, VagaGaragem
    
    try:
        moradores = Morador.query.order_by(Morador.casa, Morador.nome).all()
        config = ConfiguracaoVagas.query.first()
        
        try:
            vagas = VagaGaragem.query.all()
            if not vagas and config:
                if inicializar_vagas():
                    vagas = VagaGaragem.query.all()
                    flash("Sistema de vagas inicializado com sucesso!", "success")
            
            total_vagas = len(vagas) if vagas else (config.total_vagas if config else 73)
            vagas_livres = sum(1 for vaga in vagas if not vaga.ocupada) if vagas else 0
            
        except Exception as e:
            logger.error(f"Erro ao verificar vagas: {str(e)}")
            total_vagas = config.total_vagas if config else 73
            vagas_livres = 0
            flash("Erro ao carregar sistema de vagas", "warning")
        
        visitantes = Visitante.query.order_by(Visitante.hora_entrada.desc()).limit(5).all()
        
        return render_template('index.html',
                            moradores=moradores,
                            total_vagas=total_vagas,
                            vagas_livres=vagas_livres,
                            visitantes=visitantes,
                            config=config)
    
    except Exception as e:
        logger.error(f"Erro na rota index: {str(e)}")
        return render_template('index.html',
                            moradores=[],
                            total_vagas=73,
                            vagas_livres=0,
                            visitantes=[])

def handle_regular_request(casas_disponiveis):
    """Handle regular form submission for resident registration"""
    nome = request.form['nome']
    casa = request.form['casa']
    tipo = request.form['tipo']
    tem_carro = request.form.get('tem_carro') == 'Sim'
    qtde_moradores = int(request.form['qtde_moradores'])
    
    novo_morador = Morador(
        nome=nome,
        casa=casa,
        tipo=tipo,
        tem_carro=tem_carro,
        qtde_moradores=qtde_moradores,
        criado_em=datetime.utcnow()
    )
    
    db.session.add(novo_morador)
    db.session.commit()
    
    flash('Morador cadastrado com sucesso!', 'success')
    return redirect(url_for('routes.index'))

def handle_ajax_request():
    """Handle AJAX request for resident registration"""
    data = request.get_json()
    # Process AJAX data here
    return jsonify({'status': 'success'})


@routes_bp.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    from .models import Morador
    casas_disponiveis = gerar_lista_casas()
    
    if request.method == 'POST':
        try:
            # Log para verificar se os arquivos estão chegando
            logger.info(f"Arquivos recebidos: {request.files}")
            
            # Criar morador primeiro para obter um ID
            novo_morador = Morador(
                nome=request.form['nome'],
                casa=request.form['casa'],
                tipo=request.form['tipo'],
                tem_carro=request.form.get('tem_carro') == 'Sim',
                qtde_moradores=int(request.form['qtde_moradores']),
                criado_em=datetime.utcnow()
            )
            
            db.session.add(novo_morador)
            db.session.commit()  # Precisamos do ID para nomear os arquivos
            
            # Processar upload da foto do morador
            if 'foto_morador' in request.files:
                foto = request.files['foto_morador']
                if foto.filename != '':
                    filename = secure_filename(f"morador_{novo_morador.id}_{foto.filename}")
                    os.makedirs(novo_morador.FOTO_DIR, exist_ok=True)
                    filepath = os.path.join(novo_morador.FOTO_DIR, filename)
                    foto.save(filepath)
                    novo_morador.foto_morador = filepath
                    logger.info(f"Foto do morador salva em: {filepath}")
            
            # Processar upload da foto da placa (se aplicável)
            if novo_morador.tem_carro and 'foto_placa' in request.files:
                placa = request.files['foto_placa']
                if placa.filename != '':
                    filename = secure_filename(f"placa_{novo_morador.id}_{placa.filename}")
                    os.makedirs(novo_morador.PLACA_DIR, exist_ok=True)
                    filepath = os.path.join(novo_morador.PLACA_DIR, filename)
                    placa.save(filepath)
                    novo_morador.foto_placa = filepath
                    logger.info(f"Foto da placa salva em: {filepath}")
            
            db.session.commit()
            
            flash('Morador cadastrado com sucesso!', 'success')
            return redirect(url_for('routes.index'))
            
        except Exception as e:
            logger.error(f"Erro no cadastro: {str(e)}", exc_info=True)
            flash(f'Erro ao cadastrar: {str(e)}', 'danger')
            return render_template('cadastro.html', 
                                casas_disponiveis=casas_disponiveis,
                                form_data=request.form)

    return render_template('cadastro.html', casas_disponiveis=casas_disponiveis)

@routes_bp.route('/visualizar_moradores')
def visualizar_moradores():
    """Rota para visualização de moradores agrupados por casa"""
    try:
        from .models import Morador
        from .extensions import db
        
        # Agrupa moradores por casa
        casas = db.session.query(Morador.casa).distinct().all()
        moradores_por_casa = {}
        
        for casa in casas:
            moradores = Morador.query.filter_by(casa=casa[0]).order_by(Morador.nome).all()
            moradores_por_casa[casa[0]] = moradores
        
        return render_template('visualizar_moradores.html', 
                            moradores_por_casa=moradores_por_casa)
    
    except Exception as e:
        current_app.logger.error(f"Erro ao visualizar moradores: {str(e)}")
        flash("Erro ao carregar lista de moradores", "danger")
        return redirect(url_for('routes.index'))

@routes_bp.route('/editar/<int:morador_id>', methods=['GET', 'POST'])
def editar_morador(morador_id):
    from .models import Morador, VagaGaragem
    
    morador = Morador.query.get_or_404(morador_id)
    casas_disponiveis = gerar_lista_casas()
    # Correção: Contar vagas associadas ao morador através do relacionamento
    vagas_afetadas = VagaGaragem.query.filter_by(morador_id=morador.id).count()
    
    if request.method == 'POST':
        try:
            # Atualizar dados básicos
            morador.nome = request.form['nome']
            morador.casa = request.form['casa']
            morador.tipo = request.form['tipo']
            tem_carro = request.form.get('tem_carro') == 'Sim'
            
            # Verificar se está removendo o veículo
            if morador.tem_carro and not tem_carro:
                # Limpar foto da placa se existir
                if morador.foto_placa and os.path.exists(morador.foto_placa):
                    try:
                        os.remove(morador.foto_placa)
                    except OSError as e:
                        logger.error(f"Erro ao remover foto da placa: {str(e)}")
                morador.foto_placa = None
            
            morador.tem_carro = tem_carro
            morador.qtde_moradores = int(request.form['qtde_moradores'])
            
            # Processar nova foto do morador
            if 'nova_foto_morador' in request.files:
                nova_foto = request.files['nova_foto_morador']
                if nova_foto.filename != '':
                    if not allowed_file(nova_foto.filename):
                        flash('Formato de arquivo não suportado para foto do morador. Use JPG, PNG ou WEBP.', 'warning')
                    else:
                        # Remover foto antiga se existir
                        if morador.foto_morador and os.path.exists(morador.foto_morador):
                            try:
                                os.remove(morador.foto_morador)
                            except OSError as e:
                                logger.error(f"Erro ao remover foto antiga: {str(e)}")
                        
                        # Salvar nova foto
                        filename = secure_filename(f"morador_{morador.id}_{nova_foto.filename}")
                        os.makedirs(morador.FOTO_DIR, exist_ok=True)
                        filepath = os.path.join(morador.FOTO_DIR, filename)
                        nova_foto.save(filepath)
                        morador.foto_morador = filepath
                        logger.info(f"Nova foto do morador salva em: {filepath}")
            
            # Processar nova foto da placa (se tiver carro)
            if morador.tem_carro and 'nova_foto_placa' in request.files:
                nova_placa = request.files['nova_foto_placa']
                if nova_placa.filename != '':
                    if not allowed_file(nova_placa.filename):
                        flash('Formato de arquivo não suportado para foto da placa. Use JPG, PNG ou WEBP.', 'warning')
                    else:
                        # Remover foto antiga se existir
                        if morador.foto_placa and os.path.exists(morador.foto_placa):
                            try:
                                os.remove(morador.foto_placa)
                            except OSError as e:
                                logger.error(f"Erro ao remover foto antiga da placa: {str(e)}")
                        
                        # Salvar nova foto
                        filename = secure_filename(f"placa_{morador.id}_{nova_placa.filename}")
                        os.makedirs(morador.PLACA_DIR, exist_ok=True)
                        filepath = os.path.join(morador.PLACA_DIR, filename)
                        nova_placa.save(filepath)
                        morador.foto_placa = filepath
                        logger.info(f"Nova foto da placa salva em: {filepath}")
            
            db.session.commit()
            flash('Dados e fotos atualizados com sucesso!', 'success')
            return redirect(url_for('routes.visualizar_moradores'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar morador: {str(e)}", exc_info=True)
            flash(f'Erro ao atualizar: {str(e)}', 'danger')
    
    return render_template('editar.html', morador=morador, casas_disponiveis=casas_disponiveis,vagas_afetadas=vagas_afetadas)
    
@routes_bp.route('/excluir_morador/<int:morador_id>', methods=['GET', 'POST'])
def excluir_morador(morador_id):
    morador = Morador.query.get_or_404(morador_id)
    
    if request.method == 'GET':
        # Calcular impactos da exclusão
        vagas_afetadas = VagaGaragem.query.filter_by(casa=morador.casa).count()
        return render_template('excluir_morador.html', 
                            morador=morador,
                            vagas_afetadas=vagas_afetadas)
    
    elif request.method == 'POST':
        try:
            # Delete associated files if they exist
            if morador.foto_morador:
                foto_path = os.path.join(app.root_path, 'static', morador.foto_morador)
                if os.path.exists(foto_path):
                    os.remove(foto_path)
            
            # Delete associated vehicles and their photos
            for veiculo in morador.veiculos:
                if veiculo.foto_placa:
                    placa_path = os.path.join(app.root_path, 'static', veiculo.foto_placa)
                    if os.path.exists(placa_path):
                        os.remove(placa_path)
                db.session.delete(veiculo)
            
            # Delete associated parking spots
            VagaGaragem.query.filter_by(casa=morador.casa).delete()
            
            # Delete the resident
            db.session.delete(morador)
            db.session.commit()
            
            flash(f'Morador {morador.nome} foi excluído com sucesso!', 'success')
            return redirect(url_for('visualizar_moradores'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir morador: {str(e)}", exc_info=True)
            flash(f'Erro ao excluir morador: {str(e)}', 'danger')
            return redirect(url_for('editar_morador', morador_id=morador_id))
        
    

@routes_bp.route('/verificar_entrada', methods=['GET', 'POST'])
def verificar_entrada():
    if request.method == 'GET':
        return render_template('verificar_entrada.html')
    
    elif request.method == 'POST':
        try:
            imagem_bytes = obter_imagem_do_request(request)
            if isinstance(imagem_bytes, tuple):
                return imagem_bytes

            tipo = request.form.get('tipo', 'facial')
            if tipo not in ('facial', 'placa'):
                return jsonify({
                    'status': 'erro', 
                    'mensagem': 'Tipo de verificação inválido'
                }), 400
            
            ga = current_app.config.get('GERENCIADOR_ACESSO')
            if ga is None:
                raise RuntimeError("Gerenciador de Acesso não inicializado")
            
            resultado = ga.verificar_entrada(imagem_bytes, tipo)
            
            if resultado['status'] == 'liberado':
                registro = registrar_acesso(
                    tipo=resultado['tipo'],
                    id_referencia=resultado.get('id_morador') or resultado.get('placa'),
                    reconhecido=True
                )
                
                if resultado['tipo'] == 'facial':
                    morador = Morador.query.get(resultado['id_morador'])
                    resultado.update({
                        'nome': morador.nome,
                        'casa': morador.casa,
                        'mensagem': 'Acesso permitido por reconhecimento facial'
                    })
                else:
                    veiculo = Veiculo.query.filter_by(placa=resultado['placa']).first()
                    if veiculo:
                        resultado.update({
                            'morador': veiculo.morador.nome,
                            'casa': veiculo.morador.casa,
                            'mensagem': 'Acesso permitido por reconhecimento de placa'
                        })
                
                return jsonify(resultado)
            else:
                registrar_acesso(
                    tipo=tipo,
                    identificador="desconhecido",
                    reconhecido=False
                )
                return jsonify(resultado), 401
                
        except Exception as e:
            logger.error(f"Erro na verificação: {str(e)}", exc_info=True)
            return jsonify({
                'status': 'erro', 
                'mensagem': 'Erro interno no servidor',
                'detalhes': str(e)
            }), 500



@routes_bp.route('/visitante', methods=['GET', 'POST'])
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




@routes_bp.route('/visitantes')
def visualizar_visitantes():
    visitantes = Visitante.query.all()
    return render_template('visualizar_visitantes.html', visitantes=visitantes)

@routes_bp.route('/editar_visitante/<int:visitante_id>', methods=['GET', 'POST'])
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


@routes_bp.route('/veiculo/cadastrar', methods=['GET', 'POST'])
def cadastrar_veiculo():
    moradores = Morador.query.order_by(Morador.nome).all()  # Ordena por nome
    
    if request.method == 'POST':
        try:
            # Validações
            if not all([request.form.get('placa'), request.form.get('id_morador'), request.form.get('tipo_veiculo')]):
                flash("Preencha todos os campos obrigatórios", "danger")
                return redirect(url_for('routes.cadastrar_veiculo'))

            placa = request.form['placa'].upper().strip().replace('-', '').replace(' ', '')
            
            # Validação reforçada da placa
            if not re.match(r'^[A-Z]{3}\d[A-Z0-9]\d{2}$|^[A-Z]{3}\d{4}$', placa):
                flash("Formato de placa inválido! Use ABC1D23 (Mercosul) ou ABC1234 (modelo antigo)", "danger")
                return redirect(url_for('routes.cadastrar_veiculo'))

            # Verifica se placa já existe
            if Veiculo.query.filter_by(placa=placa).first():
                flash("Esta placa já está cadastrada no sistema", "warning")
                return redirect(url_for('routes.cadastrar_veiculo'))

            morador = Morador.query.get(request.form['id_morador'])
            if not morador:
                flash("Morador não encontrado", "danger")
                return redirect(url_for('routes.cadastrar_veiculo'))

            # Formata a placa
            placa_formatada = f"{placa[:3]}-{placa[3:]}"
            
            tipo = request.form['tipo_veiculo'].upper()  # Converte para maiúsculas
            if tipo not in TipoVeiculo.get_values():
                flash("Tipo de veículo inválido", "danger")
                return redirect(url_for('routes.cadastrar_veiculo'))
            
            # Cria e salva o veículo
            novo_veiculo = Veiculo(
                morador_id=request.form['id_morador'],
                placa=placa_formatada,
                tipo_veiculo=request.form['tipo_veiculo'].capitalize(),  # Padroniza (Carro, Moto)
                qtde_veiculos=int(request.form.get('qtde_veiculos', 1))
            )
            
            db.session.add(novo_veiculo)
            db.session.commit()
            
            flash(f"Veículo {placa_formatada} cadastrado com sucesso para {morador.nome}!", "success")
            return redirect(url_for('routes.visualizar_veiculos'))  # Redireciona para lista de veículos
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao cadastrar veículo: {str(e)}", "danger")
            return redirect(url_for('routes.cadastrar_veiculo'))

    return render_template('cadastrar_veiculo.html', moradores=moradores)

@routes_bp.route('/veiculos')
def visualizar_veiculos():
    try:
        veiculos = Veiculo.query.all()
        return render_template('visualizar_veiculos.html', veiculos=veiculos)
    except Exception as e:
        logger.error(f"Error fetching vehicles: {str(e)}")
        flash("Error loading vehicle data", "danger")
        return redirect(url_for('routes.index'))


@routes_bp.route('/veiculo/editar/<int:veiculo_id>', methods=['GET', 'POST'])
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

@routes_bp.route('/painel_vagas_visual')
def painel_vagas_visual():
    from .models import ConfiguracaoVagas, VagaGaragem, Veiculo
    from datetime import datetime, timezone
    
    try:
        config = ConfiguracaoVagas.query.first()
        
        vagas = db.session.query(
            VagaGaragem,
            Veiculo
        ).outerjoin(
            Veiculo, VagaGaragem.veiculo_id == Veiculo.id
        ).order_by(
            VagaGaragem.numero
        ).all()
        
        vagas_data = []
        for vaga, veiculo in vagas:
            vagas_data.append({
                'id': vaga.id,
                'numero': vaga.numero,
                'ocupada': vaga.ocupada,
                'placa': vaga.placa or (veiculo.placa if veiculo else None),
                'tipo': vaga.tipo.value if vaga.tipo else None
            })
        
        total_vagas = config.total_vagas if config else len(vagas_data)
        vagas_ocupadas = sum(1 for v in vagas_data if v['ocupada'])
        vagas_livres = total_vagas - vagas_ocupadas
        
        current_time = datetime.now(timezone.utc)
        
        return render_template(
            'painel_vagas_visual.html',
            vagas=vagas_data,
            total_vagas=total_vagas,
            vagas_livres=vagas_livres,
            vagas_ocupadas=vagas_ocupadas,
            now=current_time,
            timestamp=int(current_time.timestamp())
        )
    except Exception as e:
        logger.error(f"Erro no painel de vagas: {str(e)}", exc_info=True)
        return render_template('error.html', error=str(e)), 500



@routes_bp.route('/painel_porteiro', methods=['GET', 'POST'])
def painel_porteiro():
    from .models import Movimentacao, Morador, Veiculo, Visitante, VagaGaragem
    from datetime import datetime, timedelta, timezone
    import re
    
    agora = datetime.now(timezone.utc)
    
    if request.method == 'POST':
        placa = request.form.get('placa')
        acao = request.form.get('acao', 'saida')
        tipo_entrada = request.form.get('tipo_entrada', 'cadastrado')
        
        if not placa:
            flash("Placa é obrigatória", "danger")
            return redirect(url_for('routes.painel_porteiro'))
        

        
        try:
            placa = re.sub(r'[^a-zA-Z0-9]', '', placa).upper()
            
            if acao == 'entrada':
                if tipo_entrada == 'visitante':
                    registrar_entrada_visitante(placa)
                else:
                    registrar_entrada_cadastrado(placa)
            elif acao == 'saida':
                registrar_saida_veiculo(placa)
                
            flash("Operação realizada com sucesso", "success")
            return redirect(url_for('routes.painel_porteiro'))
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro no registro: {str(e)}", exc_info=True)
            flash(f"Erro no processamento: {str(e)}", "danger")
            return redirect(url_for('routes.painel_porteiro'))
    
    veiculos_estacionados = obter_veiculos_estacionados()
    historico = obter_historico_recente()
    
    return render_template(
        'painel_porteiro.html',
        veiculos_estacionados=veiculos_estacionados,
        historico=historico,
        agora=agora, timezone=timezone)

def registrar_entrada_visitante(placa):
    """Registra entrada de visitante"""
    try:
        novo_visitante = Visitante(
            nome=f"Visitante {placa}",
            casa_destino="VISITANTE",
            placa=placa,
            hora_entrada=datetime.now(timezone.utc),
            hora_limite=datetime.now(timezone.utc) + timedelta(hours=2))
        db.session.add(novo_visitante)
        
        nova_mov = Movimentacao(
            tipo='manual',
            identificador=placa,
            status='reconhecido',
            entrada=datetime.now(timezone.utc),
            visitante_id=novo_visitante.id
        )
        db.session.add(nova_mov)
        db.session.commit()
        
        flash(f"Entrada de visitante com placa {placa} registrada", "success")
    except Exception as e:
        db.session.rollback()
        raise RuntimeError(f"Falha ao registrar visitante: {str(e)}")

def registrar_entrada_cadastrado(placa):
    """Registra entrada de veículo cadastrado"""
    try:
        veiculo = Veiculo.query.filter_by(placa=placa).first()
        if not veiculo:
            raise RuntimeError("Placa não cadastrada. Registre como visitante.")
        
        if Movimentacao.query.filter_by(veiculo_id=veiculo.id, saida=None).first():
            raise RuntimeError("Veículo já está estacionado!")
        
        nova_mov = Movimentacao(
            tipo='manual',
            identificador=placa,
            status='reconhecido',
            entrada=datetime.now(timezone.utc),
            veiculo_id=veiculo.id,
            morador_id=veiculo.morador_id
        )
        db.session.add(nova_mov)
        
        vaga = VagaGaragem.query.filter_by(veiculo_id=veiculo.id).first()
        if vaga:
            vaga.ocupada = True
            vaga.data_ocupacao = datetime.now(timezone.utc)
        
        db.session.commit()
        flash(f"Entrada do veículo {placa} registrada!", "success")
    except Exception as e:
        db.session.rollback()
        raise RuntimeError(f"Falha ao registrar entrada: {str(e)}")

def registrar_saida_veiculo(placa):
    """Registra saída de veículo"""
    try:
        mov = Movimentacao.query.filter(
            (Movimentacao.identificador == placa) & 
            (Movimentacao.saida == None)
        ).first()
        
        if not mov:
            raise RuntimeError("Nenhum registro de entrada encontrado!")
        
        mov.saida = datetime.now(timezone.utc)
        
        if mov.veiculo_id:
            vaga = VagaGaragem.query.filter_by(veiculo_id=mov.veiculo_id).first()
            if vaga:
                vaga.ocupada = False
                vaga.data_ocupacao = None
        
        db.session.commit()
        flash(f"Saída do veículo {placa} registrada!", "success")
    except Exception as e:
        db.session.rollback()
        raise RuntimeError(f"Falha ao registrar saída: {str(e)}")

def obter_veiculos_estacionados():
    """Retorna lista formatada de veículos estacionados"""
    try:
        resultados = db.session.query(
            Movimentacao,
            Morador,
            Veiculo
        ).join(
            Veiculo, Movimentacao.veiculo_id == Veiculo.id, isouter=True
        ).join(
            Morador, Veiculo.morador_id == Morador.id, isouter=True
        ).filter(
            Movimentacao.saida == None
        ).order_by(
            Movimentacao.entrada.desc()
        ).all()
        
        return [{
            'movimentacao': mov,
            'morador': morador,
            'veiculo': veiculo,
            'identificador': mov.identificador,
            'tipo': 'cadastrado' if veiculo else 'visitante'
        } for mov, morador, veiculo in resultados]
    except Exception as e:
        logger.error(f"Erro ao obter veículos estacionados: {str(e)}")
        return []

def obter_historico_recente():
    """Retorna histórico formatado de movimentações"""
    try:
        resultados = db.session.query(
            Movimentacao,
            Morador,
            Veiculo
        ).outerjoin(
            Veiculo, Movimentacao.veiculo_id == Veiculo.id
        ).outerjoin(
            Morador, Veiculo.morador_id == Morador.id
        ).order_by(
            Movimentacao.entrada.desc()
        ).limit(20).all()
        
        return [{
            'movimentacao': mov,
            'morador': morador,
            'veiculo': veiculo,
            'identificador': mov.identificador,
            'tipo': 'cadastrado' if veiculo else 'visitante'
        } for mov, morador, veiculo in resultados]
    except Exception as e:
        logger.error(f"Erro ao obter histórico: {str(e)}")
        return []


@routes_bp.route('/registrar_saida', methods=['POST'])
def registrar_saida():
    try:
        data = request.get_json()
        placa = data.get('placa')
        
        if not placa:
            return jsonify({'success': False, 'message': 'Placa é obrigatória'}), 400

        # Encontrar a movimentação mais recente sem saída para esta placa
        movimentacao = Movimentacao.query.filter(
            (Movimentacao.identificador == placa) & 
            (Movimentacao.saida == None)
        ).order_by(Movimentacao.entrada.desc()).first()

        if not movimentacao:
            return jsonify({'success': False, 'message': 'Nenhuma entrada registrada para esta placa'}), 404

        # Registrar a saída
        movimentacao.saida = datetime.now(timezone.utc)
        
        # Se for um veículo cadastrado, liberar a vaga associada
        if movimentacao.veiculo_id:
            vaga = VagaGaragem.query.filter_by(veiculo_id=movimentacao.veiculo_id).first()
            if vaga:
                vaga.ocupada = False
                vaga.veiculo_id = None  # Adicionado para limpar a referência
                vaga.data_ocupacao = None
        
        # Commit das alterações
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Saída do veículo {placa} registrada com sucesso!',
            'data': {
                'entrada': movimentacao.entrada.isoformat(),
                'saida': movimentacao.saida.isoformat(),
                'vaga_liberada': True if movimentacao.veiculo_id else False
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erro ao registrar saída: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Erro interno ao registrar saída',
            'error': str(e)
        }), 500


@routes_bp.route('/historico')
def historico():
    from datetime import datetime, timezone
    
    # Get filter parameters
    filtro = request.args.get('filtro', '')
    tipo = request.args.get('tipo', 'todos')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    # Base query
    query = Movimentacao.query
    
    # Apply filters
    if filtro:
        query = query.filter(
            (Movimentacao.identificador.ilike(f"%{filtro}%")) |
            (Movimentacao.morador.has(Morador.nome.ilike(f"%{filtro}%")) |
            (Movimentacao.veiculo.has(Veiculo.placa.ilike(f"%{filtro}%")) |
            (Movimentacao.visitante.has(Visitante.nome.ilike(f"%{filtro}%"))
            )
            ))
        )
    
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
    
    # Include related objects and order
    registros = query.options(
        db.joinedload(Movimentacao.morador),
        db.joinedload(Movimentacao.veiculo),
        db.joinedload(Movimentacao.visitante)
    ).order_by(Movimentacao.entrada.desc()).all()
    
    return render_template(
        "historico.html",
        registros=registros,
        filtro=filtro,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        now=datetime.now(timezone.utc)
    )
    
# ============================
# ROTAS DA API
# ============================

@routes_bp.route('/api/moradores')
def get_moradores():
    from .models import Morador
    moradores = Morador.query.all()
    return jsonify([m.serialize() for m in moradores])

@routes_bp.route('/api/vaga_status/<int:vaga_id>')
def vaga_status(vaga_id):
    from .models import VagaGaragem
    vaga = VagaGaragem.query.get_or_404(vaga_id)
    return jsonify({
        'id': vaga.id,
        'numero': vaga.numero,
        'ocupada': vaga.ocupada,
        'placa': vaga.placa,
        'veiculo_id': vaga.veiculo_id,
        'casa': vaga.casa
    })

@routes_bp.route('/api/configuracao_vagas')
def get_configuracao_vagas():
    from .models import ConfiguracaoVagas
    config = ConfiguracaoVagas.query.first()
    if not config:
        return jsonify({'error': 'Configuração não encontrada'}), 404
        
    return jsonify({
        'total_vagas': config.total_vagas,
        'vagas_proprietario': config.vagas_proprietario,
        'vagas_inquilino': config.vagas_inquilino,
        'vagas_visitantes': config.vagas_visitantes,
        'ultima_atualizacao': config.ultima_atualizacao.isoformat()
    })

# ============================
# FUNÇÕES DE CONTEXTO
# ============================

def inicializar_vagas():
    from .models import ConfiguracaoVagas, Morador, VagaGaragem
    
    try:
        config = ConfiguracaoVagas.query.first()
        if not config:
            config = ConfiguracaoVagas(
                total_vagas=73,
                vagas_proprietario=2,
                vagas_inquilino=1,
                vagas_visitantes=3
            )
            db.session.add(config)
            db.session.commit()

        if not VagaGaragem.query.first():
            moradores = Morador.query.order_by(Morador.casa).all()
            vagas = []
            vaga_count = 1

            vagas_moradores = config.total_vagas - config.vagas_visitantes
            
            for morador in moradores:
                num_vagas = config.vagas_proprietario if morador.tipo == 'proprietario' else config.vagas_inquilino
                for i in range(num_vagas):
                    if vaga_count <= vagas_moradores:
                        letra = chr(65 + i)
                        numero_vaga = f"{morador.casa}{letra}"
                        vagas.append(VagaGaragem(
                            numero=numero_vaga,
                            casa=morador.casa,
                            ocupada=False,
                            tipo=morador.tipo
                        ))
                        vaga_count += 1

            for i in range(config.vagas_visitantes):
                vagas.append(VagaGaragem(
                    numero=f"VIS{i+1:02d}",
                    casa="VISITANTE",
                    ocupada=False,
                    tipo='visitante'
                ))

            db.session.bulk_save_objects(vagas)
            db.session.commit()
            return True

    except Exception as e:
        logger.error(f"Erro ao inicializar vagas: {str(e)}")
        db.session.rollback()
        return False

def registrar_entrada_veiculo(placa):
    from .models import ConfiguracaoVagas, Veiculo, Movimentacao, VagaGaragem
    from datetime import datetime, timezone
    
    try:
        config = ConfiguracaoVagas.query.first()
        if not config:
            logger.error("Configuração de vagas não encontrada")
            raise RuntimeError("Configuração de vagas não encontrada no sistema")
        
        # Verifica se veículo já está estacionado
        if Movimentacao.query.filter_by(identificador=placa, saida=None).first():
            logger.warning(f"Veículo {placa} já está estacionado")
            raise RuntimeError(f"Veículo {placa} já está estacionado")
        
        veiculo = Veiculo.query.filter_by(placa=placa).first()
        
        # Se não for veículo cadastrado, registrar como visitante
        if not veiculo or not veiculo.morador:
            logger.info(f"Registrando entrada de visitante com placa {placa}")
            return registrar_entrada_visitante(placa)
        
        morador = veiculo.morador
        vagas_casa = VagaGaragem.query.filter_by(casa=morador.casa).all()
        
        limite = config.vagas_proprietario if morador.tipo == 'proprietario' else config.vagas_inquilino
        
        # Conta vagas ocupadas pelo morador
        vagas_ocupadas = sum(1 for v in vagas_casa if v.ocupada and v.veiculo and v.veiculo.morador.id == morador.id)
        
        if vagas_ocupadas >= limite:
            logger.warning(f"Limite de {limite} vagas atingido para morador {morador.nome}")
            raise RuntimeError(f"Limite de vagas atingido para esta residência")
        
        # Encontra primeira vaga livre
        vaga = next((v for v in vagas_casa if not v.ocupada), None)
        
        if not vaga:
            logger.warning(f"Nenhuma vaga disponível para casa {morador.casa}")
            raise RuntimeError("Nenhuma vaga disponível para esta residência")
            
        # Cria registro de movimentação
        nova_mov = Movimentacao(
            tipo='veiculo',
            identificador=placa,
            status='manual',
            entrada=datetime.now(timezone.utc),
            veiculo_id=veiculo.id,
            morador_id=morador.id
        )
        
        # Atualiza vaga
        vaga.ocupada = True
        vaga.placa = placa
        vaga.veiculo_id = veiculo.id
        vaga.data_ocupacao = datetime.now(timezone.utc)
        
        db.session.add(nova_mov)
        db.session.commit()
        
        logger.info(f"Entrada registrada para veículo {placa} na vaga {vaga.numero}")
        return True
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erro ao registrar entrada de veículo: {str(e)}", exc_info=True)
        raise  # Re-lança a exceção para ser tratada pela função chamadora

def registrar_saida_veiculo(placa):
    from .models import Movimentacao, VagaGaragem
    
    registro = Movimentacao.query.filter_by(
        tipo='veiculo',
        identificador=placa,
        saida=None
    ).order_by(Movimentacao.entrada.desc()).first()
    
    if registro:
        registro.saida = datetime.utcnow()
        
        vaga = VagaGaragem.query.filter_by(placa=placa).first()
        if vaga:
            vaga.ocupada = False
            vaga.placa = None
            vaga.data_ocupacao = None
            vaga.veiculo_id = None
        
        try:
            db.session.commit()
            logger.info(f"Saída do veículo {placa} registrada com sucesso")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao registrar saída: {str(e)}")
            return False
    return False


@routes_bp.route('/documentacao')
def documentacao():
    """Rota principal de documentação do sistema"""
    return render_template('documentacao.html')

@routes_bp.route('/docs/api')
def api_docs():
    """Redireciona para a documentação Swagger"""
    return redirect(url_for('flasgger.apidocs'))

@routes_bp.route('/docs/fluxo')
def fluxo_sistema():
    """Exibe o fluxo do sistema"""
    return render_template('fluxo_sistema.html')