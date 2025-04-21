from datetime import datetime, timezone
from flask import current_app

def register_filters(app):
    """Registra todos os filtros customizados no aplicativo Flask"""
    
    @app.template_filter('minutes_since')
    def minutes_since(dt):
        """Calcula minutos desde uma data até agora"""
        if dt is None:
            return 0
        agora = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (agora - dt).total_seconds() / 60

    @app.template_filter('format_placa')
    def format_placa_filter(placa):
        if not placa:
            return ""
        placa = placa.upper().replace('-', '').replace(' ', '')
        if len(placa) == 7:
            return f"{placa[:3]}-{placa[3:]}"
        return placa

    @app.template_filter('datetime_format')
    def datetime_format(dt, fmt='%d/%m/%Y %H:%M'):
        """Formata datetime para string"""
        if dt is None:
            return ""
        return dt.strftime(fmt)
    
    @app.template_filter('tempo_decorrido')
    def tempo_decorrido(dt):
        """Retorna string amigável de tempo decorrido"""
        if dt is None:
            return "Nunca"
        
        agora = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        delta = agora - dt
        
        if delta.days > 365:
            return f"{delta.days // 365} anos atrás"
        if delta.days > 30:
            return f"{delta.days // 30} meses atrás"
        if delta.days > 0:
            return f"{delta.days} dias atrás"
        if delta.seconds > 3600:
            return f"{delta.seconds // 3600} horas atrás"
        if delta.seconds > 60:
            return f"{delta.seconds // 60} minutos atrás"
        return "Agora mesmo"


def get_current_time():
    return datetime.now(timezone.utc)    
    