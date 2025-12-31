import os
from datetime import datetime
from flask import Flask, request, send_from_directory, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_

# Config
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cf3310364d274f15905ff5a2fd435c7bb6c69dcf111832a60d19c51ba447cc61'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ✅ SWITCHED TO MYSQL (Local Development)
# Format: mysql+pymysql://user:password@host:port/database
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://owner:secure123@localhost:3306/songs_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_owner = db.Column(db.Boolean, default=False)
    profile_image = db.Column(db.String(200))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    playlists = db.relationship('Playlist', backref='creator', lazy=True)

class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    artist = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    cover_image = db.Column(db.String(200))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

playlist_songs = db.Table('playlist_songs',
    db.Column('playlist_id', db.Integer, db.ForeignKey('playlist.id'), primary_key=True),
    db.Column('song_id', db.Integer, db.ForeignKey('song.id'), primary_key=True)
)

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    songs = db.relationship('Song', secondary=playlist_songs, backref=db.backref('playlists', lazy='dynamic'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    if query:
        songs = Song.query.filter(
            or_(Song.title.ilike(f'%{query}%'), Song.artist.ilike(f'%{query}%'))
        ).all()
    else:
        songs = Song.query.all()
    return render_template('index.html', songs=songs)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect('/')
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if not current_user.is_owner:
        return "Access denied", 403
    if request.method == 'POST':
        file = request.files.get('file')
        cover = request.files.get('cover')
        title = request.form.get('title', '').strip()
        artist = request.form.get('artist', '').strip()
        
        if not file or not title or not artist:
            return render_template('upload.html', error='Title, artist, and audio file are required')
        if not allowed_file(file.filename):
            return render_template('upload.html', error='Invalid audio format. Use MP3, WAV, OGG, or FLAC.')
        
        audio_fn = save_file(file)
        cover_fn = None
        if cover and cover.filename:
            if allowed_image(cover.filename):
                cover_fn = save_file(cover)
            else:
                return render_template('upload.html', error='Cover image must be JPG or PNG.')
        
        song = Song(
            title=title,
            artist=artist,
            filename=audio_fn,
            cover_image=cover_fn,
            uploader_id=current_user.id
        )
        db.session.add(song)
        db.session.commit()
        return redirect('/')
    return render_template('upload.html')

@app.route('/playlists')
def playlists():
    return render_template('playlists.html', playlists=Playlist.query.all())

@app.route('/playlist/<int:playlist_id>')
def playlist_detail(playlist_id):
    playlist = Playlist.query.get_or_404(playlist_id)
    return render_template('playlist.html', playlist=playlist)

@app.route('/create_playlist', methods=['GET', 'POST'])
@login_required
def create_playlist():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name:
            pl = Playlist(name=name, created_by_id=current_user.id)
            db.session.add(pl)
            db.session.commit()
            return redirect(url_for('playlists'))
        return render_template('create_playlist.html', error='Playlist name is required')
    return render_template('create_playlist.html')

@app.route('/add_to_playlist/<int:song_id>', methods=['GET', 'POST'])
@login_required
def add_to_playlist(song_id):
    song = Song.query.get_or_404(song_id)
    if request.method == 'POST':
        pl = Playlist.query.get_or_404(request.form['playlist_id'])
        if song not in pl.songs:
            pl.songs.append(song)
            db.session.commit()
        return redirect(url_for('playlist_detail', playlist_id=pl.id))
    playlists = Playlist.query.filter_by(created_by_id=current_user.id).all()
    return render_template('add_to_playlist.html', song=song, playlists=playlists)

# File serving
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Handle missing files gracefully
    if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        return "File not found", 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/download/<filename>')
def download_file(filename):
    if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        return "File not found", 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/stream/<filename>')
def stream_file(filename):
    if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        return "File not found", 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Helpers
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'mp3', 'wav', 'ogg', 'flac'}

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'jpg', 'jpeg', 'png'}

def save_file(file):
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        filename = f"{base}_{counter}{ext}"
        counter += 1
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename

# Initialize database
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='owner').first():
            owner = User(username='owner', is_owner=True)
            owner.set_password('ChangeThisPassword123!')
            db.session.add(owner)
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run(debug=True)
