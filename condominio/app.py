import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from .extensions import init_extensions
from .config import config
from .models import db, Morador, VagaGaragem, Visitante, Movimentacao, Veiculo, ConfiguracaoVagas
from .reconhecimento import ReconhecimentoFacial, ReconhecimentoPlacas, GerenciadorAcesso

# Carrega variáveis de ambiente
load_dotenv()


# Create scheduler instance at module level
scheduler = BackgroundScheduler()

def create_app():
    """Factory principal para criar a aplicação Flask"""
    app = Flask(__name__, static_folder='static', template_folder='templates')
    
    # Configurações básicas
    app.config.from_object(config)
    
    # Inicializa extensões
    init_extensions(app)
    
    # Configuração de logging
    configure_logging(app)
    
    # Registra blueprints
    register_blueprints(app)
    
    # Inicializa sistemas de reconhecimento
    init_recognition_systems(app)
    
    # Cria diretórios necessários
    create_directories(app)
    
    
    # Configura handlers de erro
    register_error_handlers(app)
    
    # Registra comandos CLI  ← ADICIONE ESTA LINHA
    register_cli_commands(app) 
    
    # Initialize scheduler
    init_scheduler(app)
    
    # Register template filters
    from .filters import register_filters
    register_filters(app)

    # Shell context
    @app.shell_context_processor
    def make_shell_context():
        return {
            'db': db,
            'Morador': Morador,
            'VagaGaragem': VagaGaragem,
            'Visitante': Visitante,
            'Movimentacao': Movimentacao,
            'Veiculo': Veiculo,
            'ConfiguracaoVagas': ConfiguracaoVagas
        }
    
    return app

def configure_logging(app):
    """Configura o sistema de logging"""
    if not os.path.exists('logs'):
        os.mkdir('logs')
    
    file_handler = RotatingFileHandler(
        'logs/condominio.log',
        maxBytes=10240,
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Aplicação iniciada')

def register_blueprints(app):
    """Registra todos os blueprints"""
    from .routes import routes_bp  # Import aqui para evitar circular imports
    app.register_blueprint(routes_bp, url_prefix='/')

def init_recognition_systems(app):
    """Inicializa os sistemas de reconhecimento"""
    try:
        app.logger.info("Inicializando sistemas de reconhecimento...")
        
        # Inicializa reconhecimento facial
        rf = ReconhecimentoFacial()
        
        # Inicializa reconhecimento de placas
        rp = ReconhecimentoPlacas()
        
        # Inicializa gerenciador de acesso
        ga = GerenciadorAcesso(rf, rp)
        
        # Armazena nas configurações do app
        app.config['RECONHECIMENTO_FACIAL'] = rf
        app.config['RECONHECIMENTO_PLACAS'] = rp
        app.config['GERENCIADOR_ACESSO'] = ga
        
        app.logger.info("Sistemas de reconhecimento inicializados com sucesso")
        
    except Exception as e:
        app.logger.error(f"Falha na inicialização dos sistemas: {str(e)}", exc_info=True)
        raise RuntimeError(f"Falha na inicialização: {str(e)}")

def create_directories(app):
    """Cria diretórios necessários para a aplicação"""
    dirs = [
        app.config['UPLOAD_FOLDER'],
        app.config['DIR_ROSTOS'],
        app.config['DIR_PLACAS'],
        app.config['TEMP_DIR']
    ]
    
    for dir_path in dirs:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            app.logger.error(f"Erro ao criar diretório {dir_path}: {str(e)}")

def register_error_handlers(app):
    """Registra handlers de erro personalizados"""
    
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/500.html', error=str(e)), 500

def register_cli_commands(app):
    """Registra comandos personalizados para uso com 'flask command'"""
    
    @app.cli.command('init-db')
    def init_db():
        """Cria todas as tabelas do banco de dados"""
        db.create_all()
        app.logger.info("Banco de dados inicializado")

    @app.cli.command('init-vagas')
    def init_vagas():
        with app.app_context():  # Garante o contexto da aplicação
            from .models import db, VagaGaragem, ConfiguracaoVagas
        
        if not VagaGaragem.query.first():
            # Lógica de inicialização
            db.session.commit()
            print("Vagas inicializadas com sucesso!")
            return True
        print("Vagas já existem no banco")
        return False
    
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
            app.logger.info("Datas corrigidas com sucesso!")
    
    @app.cli.command('fix-saidas')
    def fix_saidas():
        from datetime import datetime, timedelta, timezone
        from .models import Movimentacao
        limite = datetime.now(timezone.utc) - timedelta(hours=24)
        pendentes = Movimentacao.query.filter(
            Movimentacao.saida == None,
            Movimentacao.entrada < limite
            ).all()
        for mov in pendentes:
            mov.saida = mov.entrada + timedelta(hours=1)  # Assume 1h de permanência
        db.session.commit()
        print(f"Corrigidas {len(pendentes)} saídas pendentes")        





def verificar_saidas_pendentes(app):
    """Verifica e fecha movimentações pendentes"""
    with app.app_context():
        limite = datetime.now(timezone.utc) - timedelta(hours=24)
        pendentes = Movimentacao.query.filter(
            Movimentacao.saida == None,
            Movimentacao.entrada < limite
        ).all()
        
        for mov in pendentes:
            mov.saida = mov.entrada + timedelta(hours=24)
            if mov.veiculo_id:
                vaga = VagaGaragem.query.filter_by(veiculo_id=mov.veiculo_id).first()
                if vaga:
                    vaga.ocupada = False
            
        db.session.commit()
        app.logger.info(f"Fechadas {len(pendentes)} movimentações pendentes")

def init_scheduler(app):
    """Inicializa o agendador de tarefas"""
    if not scheduler.running:
        # Agendar tarefa de verificação de saídas pendentes a cada 6 horas
        scheduler.add_job(
            lambda: verificar_saidas_pendentes(app),
            'interval',
            hours=6,
            id='verificar_saidas_pendentes'
        )
        
        # Iniciar o scheduler
        scheduler.start()
        app.logger.info("Agendador de tarefas inicializado")
        
        # Garantir que o scheduler seja desligado quando o app for encerrado
        @app.teardown_appcontext
        def shutdown_scheduler(exception=None):
            if scheduler.running:
                scheduler.shutdown(wait=False)
                app.logger.info("Agendador de tarefas desligado")
        
        # Garantir que o scheduler seja desligado quando o app for encerrado
        @app.teardown_appcontext
        def shutdown_scheduler(exception=None):
            if scheduler.running:
                scheduler.shutdown(wait=False)
                app.logger.info("Agendador de tarefas desligado")
                
                

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)