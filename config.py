import os

class Config:
    """Base configuration class for the Trekking Management Application."""
    # secret key for sessions and csrf signing
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_trekking_key_987654321_viva_prep')
    
    # SQLite database configuration
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'trekking.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Photo upload configuration
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'photos')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB file upload limit
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

