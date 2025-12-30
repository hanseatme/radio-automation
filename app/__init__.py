import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO

db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/streamserver.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload

    # Media paths
    app.config['MEDIA_PATH'] = '/media'
    app.config['CATEGORIES'] = ['music', 'promos', 'jingles', 'ads', 'random-moderation', 'planned-moderation', 'musicbeds']

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    login_manager.login_message = 'Bitte melden Sie sich an.'
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet')

    # Import and register blueprints
    from app.routes import main_bp
    from app.api import api_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    # Create database tables
    with app.app_context():
        db.create_all()

    # Start scheduler
    from app.scheduler import init_scheduler
    init_scheduler(app)

    # Import mic streaming WebSocket handlers
    from app import mic_streaming

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return User.query.get(int(user_id))
