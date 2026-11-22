import os

class Config:
    """Base configuration class for the Trekking Management Application."""
    # secret key for sessions and csrf signing
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_trekking_key_987654321_viva_prep')
    
    # SQLite database configuration. DATABASE_URL lets the tests (or a local
    # check of the MCP endpoint) use a throwaway database instead of trekking.db.
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = (os.environ.get('DATABASE_URL')
                               or 'sqlite:///' + os.path.join(BASE_DIR, 'trekking.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Photo upload configuration
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'photos')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB file upload limit
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

    # MCP endpoint for AI agents (see docs/MCP.md). POST /mcp answers 404 until
    # MCP_TOKEN is set, and from then on needs "Authorization: Bearer <MCP_TOKEN>".
    MCP_TOKEN = os.environ.get('MCP_TOKEN', '').strip()
    # Browser origins allowed to call /mcp, comma-separated. Empty by default: the
    # endpoint is for server-to-server calls, so a request with an Origin is refused.
    MCP_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get('MCP_ALLOWED_ORIGINS', '').split(',')
                           if o.strip()]

