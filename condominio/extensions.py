from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_caching import Cache
from flask_marshmallow import Marshmallow
from flasgger import Swagger
from flask_cors import CORS

# Inicializa a extensão do banco de dados
db = SQLAlchemy()

# Inicializa a extensão de migração
migrate = Migrate()


# Inicializa o cache
cache = Cache(config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 300
})

# Inicializa o Marshmallow para serialização
ma = Marshmallow()

# Configuração padrão do Swagger
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/"
}

# Inicializa o Swagger
swagger = Swagger(config=swagger_config)

# Habilita CORS
cors = CORS(resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})


    
def init_extensions(app):
    """
    Inicializa todas as extensões com a aplicação Flask
    
    Args:
        app: Instância da aplicação Flask
    """
    # Configura o SQLAlchemy
    db.init_app(app)
    
    # Configura o Flask-Migrate
    migrate.init_app(app, db)
    
    # Configura o cache
    cache.init_app(app)
    
    # Configura o Marshmallow
    ma.init_app(app)
    
    # Configura o Swagger
    swagger.init_app(app)
    
    # Configura o CORS
    cors.init_app(app)
    
    # Configuração adicional para SQLAlchemy
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'pool_size': 10,
        'max_overflow': 20
    }
    
    # Cria tabelas se não existirem (apenas para desenvolvimento)
    with app.app_context():
        db.create_all()