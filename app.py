import os
from datetime import datetime
import re
import sys
from dotenv import load_dotenv

# Fix Windows console encoding to support all characters
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Load environment variables first
if getattr(sys, 'frozen', False):
    basedir = os.path.dirname(sys.executable)
else:
    basedir = os.path.abspath(os.path.dirname(__file__))

env_path = os.path.join(basedir, '.env')
load_dotenv(dotenv_path=env_path, override=True)

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.exceptions import HTTPException
from models import db, Customer, ServiceEntry, ReturnEntry, Product, ServiceCenter, CompanyInfo, User
import pymysql

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'service-tracker-secret-key-123')
CORS(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# MySQL database configuration
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'admin')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '3306')
DB_NAME = os.getenv('DB_NAME', 'service_tracker_db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
}

db.init_app(app)

def ensure_db_exists():
    """Ensure the MySQL database exists before initializing SQLAlchemy."""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=int(DB_PORT)
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        conn.close()
        print(f"Database '{DB_NAME}' ensured.")
    except Exception as e:
        print(f"Error ensuring database exists: {e}")

def migrate_database():
    try:
        with db.engine.connect() as conn:
            # ── Customer table ──
            try:
                conn.execute(db.text("ALTER TABLE customer ADD COLUMN dcno VARCHAR(100)"))
                conn.commit()
            except: pass
            try:
                conn.execute(db.text("ALTER TABLE customer MODIFY COLUMN serial VARCHAR(100)"))
                conn.commit()
            except: pass
            try:
                conn.execute(db.text("ALTER TABLE customer MODIFY COLUMN model VARCHAR(100)"))
                conn.commit()
            except: pass

            # ── ServiceEntry table ──
            try:
                conn.execute(db.text("ALTER TABLE service_entry ADD COLUMN print_dc_no VARCHAR(20)"))
                conn.commit()
            except: pass
            try:
                conn.execute(db.text("ALTER TABLE service_entry MODIFY COLUMN serial VARCHAR(100)"))
                conn.commit()
            except: pass
            try:
                conn.execute(db.text("ALTER TABLE service_entry MODIFY COLUMN model VARCHAR(100)"))
                conn.commit()
            except: pass

            # ── ReturnEntry table ──
            try:
                conn.execute(db.text("ALTER TABLE return_entry ADD COLUMN sc_dc_no VARCHAR(100)"))
                conn.commit()
            except: pass
            try:
                conn.execute(db.text("ALTER TABLE return_entry MODIFY COLUMN serial VARCHAR(100)"))
                conn.commit()
            except: pass
            try:
                conn.execute(db.text("ALTER TABLE return_entry MODIFY COLUMN model VARCHAR(100)"))
                conn.commit()
            except: pass
            try:
                # Expand status column to support longer 'Others / ...' values
                conn.execute(db.text("ALTER TABLE return_entry MODIFY COLUMN status VARCHAR(200)"))
                conn.commit()
            except: pass

            # ── Product table ──
            try:
                conn.execute(db.text("ALTER TABLE product MODIFY COLUMN model_no VARCHAR(100)"))
                conn.commit()
            except: pass

            print("Database migration completed!")
    except Exception as e:
        print(f"Migration error: {e}")

# NOTE: migrate_database() is called below inside app context

# Create tables and initial data
with app.app_context():
    ensure_db_exists()
    db.create_all()
    migrate_database()
    
    # Pre-populate products if empty
    if not Product.query.first():
        initial_products = ['CCTV Camera', 'DVR', 'NVR', 'UPS', 'Security System']
        for p_name in initial_products:
            db.session.add(Product(name=p_name))  # type: ignore
            
    # Pre-populate service centers if empty
    if not ServiceCenter.query.first():
        initial_scs = [
            {'name':'Dynamic Conglomerate Pvt Ltd', 'area':'Chennai', 'pin':'600 002', 'phone':'044-43219181, 87545 64387, 7299915627'},
            {'name':'Kaizen Infoserve Private Limited', 'area':'Chennai', 'pin':'600002', 'phone':'044-45120227'},
            {'name':'Quantum Hi-Tech Merchandising Pvt ltd', 'area':'Chennai', 'pin':'600 002', 'phone':'7845324677, 9999294668'},
            {'name':'Topnotch Infotronics', 'area':'Chennai', 'pin':'600007', 'phone':'044-43936028'},
            {'name':'ACME PC Components', 'area':'Chennai', 'pin':'', 'phone':'044 - 25295115, 9382130092'},
            {'name':'Nuevotech Industries Pvt Ltd', 'area':'Chennai', 'pin':'600 002', 'phone':'044-42141847'},
            {'name':'Magnanim Systems', 'area':'Puducherry', 'pin':'605 001', 'phone':'0413-4201112'},
            {'name':'Accel Frontline Services Limited', 'area':'Chennai', 'pin':'600116', 'phone':'044-66873116'},
            {'name':'Allied Electronics', 'area':'New Delhi', 'pin':'110020', 'phone':''},
            {'name':'Microfine Computers', 'area':'Chennai', 'pin':'600002', 'phone':'044-43227553'},
            {'name':'Sai Infotech', 'area':'Coimbatore', 'pin':'641001', 'phone':'0422-2301122'},
            {'name':'Ravi Solutions', 'area':'Madurai', 'pin':'625001', 'phone':'0452-4567890'}
        ]
        for sc in initial_scs:
            db.session.add(ServiceCenter(**sc))
            
    db.session.commit()

    # Ensure company info is up to date
    info = CompanyInfo.query.first()
    if not info:
        info = CompanyInfo()
        db.session.add(info)
    
    # Force update the address and phone if they match defaults or are being changed
    info.address = '#76, Jenbaga Complex, S.P. Koil Street, Chidambaram - 608001.'
    info.phone1 = '9443221432'
    info.phone2 = '' # Clear the second number as per user request
    
    # Ensure default admin user exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin')  # type: ignore
        admin.set_password('kanwar')
        db.session.add(admin)
        
    db.session.commit()

# --- API ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        # Handle both JSON (API) and Form (Template) requests
        if request.is_json:
            data = request.json
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')
            
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            if request.is_json:
                return jsonify({"status": "success", "user": {"username": user.username}})
            return redirect(url_for('index'))
        
        if request.is_json:
            return jsonify({"error": "Invalid username or password"}), 401
        flash('Invalid username or password')
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('GulabServiceTracker.html', user=current_user)

@app.route('/api/customers', methods=['GET', 'POST'])
@login_required
def manage_customers():
    if request.method == 'GET':
        customers = Customer.query.order_by(Customer.id.desc()).all()
        return jsonify([c.to_dict() for c in customers])
    
    data = request.json
    if 'model' in data and data['model']:
        data['model'] = str(data['model'])[:100]
    if 'serial' in data and data['serial']:
        data['serial'] = str(data['serial'])[:100]
    new_cust = Customer(**data)
    db.session.add(new_cust)
    db.session.commit()
    return jsonify(new_cust.to_dict()), 201

@app.route('/api/services', methods=['GET', 'POST'])
@login_required
def manage_services():
    if request.method == 'GET':
        services = ServiceEntry.query.order_by(ServiceEntry.id.desc()).all()
        return jsonify([s.to_dict() for s in services])
    
    data = request.json
    if 'model' in data and data['model']:
        data['model'] = str(data['model'])[:100]
    if 'serial' in data and data['serial']:
        data['serial'] = str(data['serial'])[:100]
    try:
        # Clean numeric data to prevent crashes
        if 'qty' in data:
            try:
                # Remove any non-numeric junk if accidentally pasted
                clean_qty = re.sub(r'[^0-9]', '', str(data['qty']))
                data['qty'] = int(clean_qty) if clean_qty else 1
            except Exception:
                data['qty'] = 1
        
        new_svc = ServiceEntry(**data)
        db.session.add(new_svc)
        db.session.commit()
        return jsonify(new_svc.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error saving service: {e}")
        return jsonify({"error": str(e)}), 400

@app.route('/api/services/<int:id>/print', methods=['POST'])
@login_required
def generate_print_dc(id):
    svc = ServiceEntry.query.get_or_404(id)
    if not svc.print_dc_no:
        # Generate new DC No with YYNNNN format
        current_year = datetime.now().strftime("%y")
        last_svc = ServiceEntry.query.filter(
            ServiceEntry.print_dc_no.isnot(None),
            ServiceEntry.print_dc_no.like(f"{current_year}%")
        ).order_by(ServiceEntry.id.desc()).first()
        
        next_num = 1
        if last_svc and last_svc.print_dc_no and len(last_svc.print_dc_no) == 6:
            try:
                next_num = int(last_svc.print_dc_no[2:]) + 1
            except ValueError:
                pass
        svc.print_dc_no = f"{current_year}{next_num:04d}"
        db.session.commit()
    return jsonify(svc.to_dict())

@app.route('/api/services/print-multi', methods=['POST'])
@login_required
def generate_multi_print_dc():
    ids = request.json.get('ids', [])
    if not ids:
        return jsonify({"error": "No IDs provided"}), 400
        
    services = ServiceEntry.query.filter(ServiceEntry.id.in_(ids)).all()
    if not services:
        return jsonify({"error": "Entries not found"}), 404
        
    # Verify same Service Center
    scs = {s.sc for s in services}
    if len(scs) > 1:
        return jsonify({"error": "Selected entries must belong to the same Service Center"}), 400
        
    # Handle DC Number logic
    # We always generate a NEW shared DC number for this specific selected batch
    # to ensure they are grouped together cleanly.
    current_year = datetime.now().strftime("%y")
    last_svc = ServiceEntry.query.filter(
        ServiceEntry.print_dc_no.isnot(None),
        ServiceEntry.print_dc_no.like(f"{current_year}%")
    ).order_by(ServiceEntry.id.desc()).first()
    
    next_num = 1
    if last_svc and last_svc.print_dc_no and len(last_svc.print_dc_no) == 6:
        try:
            next_num = int(last_svc.print_dc_no[2:]) + 1
        except ValueError:
            pass
    current_dc = f"{current_year}{next_num:04d}"
        
    for s in services:
        s.print_dc_no = current_dc
        
    db.session.commit()
    return jsonify([s.to_dict() for s in services])

@app.route('/api/customers/<int:id>', methods=['GET', 'DELETE'])
@login_required
def manage_customer_individual(id):
    cust = Customer.query.get_or_404(id)
    if request.method == 'DELETE':
        db.session.delete(cust)
        db.session.commit()
        return jsonify({"status": "Deleted"})
    return jsonify(cust.to_dict())

@app.route('/api/services/<int:id>', methods=['GET', 'DELETE', 'PUT'])
@login_required
def manage_service_individual(id):
    svc = ServiceEntry.query.get_or_404(id)
    if request.method == 'DELETE':
        db.session.delete(svc)
        db.session.commit()
        return jsonify({"status": "Deleted"})
    
    if request.method == 'PUT':
        data = request.json
        if 'model' in data and data['model']:
            data['model'] = str(data['model'])[:100]
        if 'serial' in data and data['serial']:
            data['serial'] = str(data['serial'])[:100]
        if 'qty' in data:
            try:
                clean_qty = re.sub(r'[^0-9]', '', str(data['qty']))
                data['qty'] = int(clean_qty) if clean_qty else svc.qty
            except Exception:
                pass  # fallback to original if impossible
        
        for key, value in data.items():
            if hasattr(svc, key) and key != 'id':
                setattr(svc, key, value)
        
        db.session.commit()
        return jsonify(svc.to_dict())
        
    return jsonify(svc.to_dict())

@app.route('/api/returns', methods=['GET', 'POST'])
@login_required
def manage_returns():
    if request.method == 'GET':
        returns = ReturnEntry.query.order_by(ReturnEntry.id.desc()).all()
        return jsonify([r.to_dict() for r in returns])
    
    data = request.json
    if 'model' in data and data['model']:
        data['model'] = str(data['model'])[:100]
    if 'serial' in data and data['serial']:
        data['serial'] = str(data['serial'])[:100]
    try:
        if 'qty' in data:
            try:
                clean_qty = re.sub(r'[^0-9]', '', str(data['qty']))
                data['qty'] = int(clean_qty) if clean_qty else 1
            except Exception:
                data['qty'] = 1
                
        new_ret = ReturnEntry(**data)
        db.session.add(new_ret)
        db.session.commit()
        return jsonify(new_ret.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error saving return: {e}")
        return jsonify({"error": str(e)}), 400

@app.route('/api/returns/<int:id>', methods=['GET', 'DELETE', 'PUT'])
@login_required
def manage_return_individual(id):
    ret = ReturnEntry.query.get_or_404(id)
    if request.method == 'DELETE':
        db.session.delete(ret)
        db.session.commit()
        return jsonify({"status": "Deleted"})
        
    if request.method == 'PUT':
        data = request.json
        if 'model' in data and data['model']:
            data['model'] = str(data['model'])[:100]
        if 'serial' in data and data['serial']:
            data['serial'] = str(data['serial'])[:100]
        if 'qty' in data:
            try:
                clean_qty = re.sub(r'[^0-9]', '', str(data['qty']))
                data['qty'] = int(clean_qty) if clean_qty else ret.qty
            except Exception:
                pass
                
        for key, value in data.items():
            if hasattr(ret, key) and key != 'id':
                setattr(ret, key, value)
                
        db.session.commit()
        return jsonify(ret.to_dict())
        
    return jsonify(ret.to_dict())

@app.route('/api/products', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def manage_products():
    if request.method == 'GET':
        products = Product.query.all()
        return jsonify([p.to_dict() for p in products])
    
    if request.method == 'POST':
        name = request.json.get('name')
        model_no = request.json.get('model_no')
        if model_no:
            model_no = str(model_no)[:100]
        if not Product.query.filter_by(name=name, model_no=model_no).first():
            db.session.add(Product(name=name, model_no=model_no))  # type: ignore
            db.session.commit()
            return jsonify({"status": "Product added"}), 201
        return jsonify({"error": "Already exists"}), 400

    if request.method == 'PUT':
        product_id = request.args.get('id')
        new_name = request.json.get('name')
        new_model = request.json.get('model_no')
        if new_model is not None:
            new_model = str(new_model)[:100]
        p = Product.query.get(product_id) if product_id else None
        if not p and request.args.get('old_name'):
            p = Product.query.filter_by(name=request.args.get('old_name')).first()
            
        if p:
            existing = Product.query.filter_by(name=new_name, model_no=new_model).first()
            if existing and existing.id != p.id:
                return jsonify({"error": "Product with new name and model already exists"}), 400
            p.name = new_name
            if new_model is not None:
                p.model_no = new_model
            db.session.commit()
            return jsonify({"status": "Updated"})
        return jsonify({"error": "Not found"}), 404

    if request.method == 'DELETE':
        product_id = request.args.get('id')
        p = Product.query.get(product_id) if product_id else None
        if not p and request.args.get('name'):
            p = Product.query.filter_by(name=request.args.get('name')).first()
            
        if p:
            db.session.delete(p)
            db.session.commit()
            return jsonify({"status": "Deleted"})
        return jsonify({"error": "Not found"}), 404

@app.route('/api/service-centers', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def manage_scs():
    if request.method == 'GET':
        scs = ServiceCenter.query.all()
        return jsonify([s.to_dict() for s in scs])
    
    if request.method == 'POST':
        data = request.json
        new_sc = ServiceCenter(**data)
        db.session.add(new_sc)
        db.session.commit()
        return jsonify(new_sc.to_dict()), 201

    if request.method == 'PUT':
        sc_id = request.args.get('id')
        name = request.args.get('name')
        
        sc = None
        if sc_id:
            sc = ServiceCenter.query.get(sc_id)
        elif name:
            sc = ServiceCenter.query.filter_by(name=name).first()
            
        if sc:
            data = request.json
            for key, val in data.items():
                if key != 'id':
                    setattr(sc, key, val)
            db.session.commit()
            return jsonify(sc.to_dict())
        return jsonify({"error": "Not found"}), 404

    if request.method == 'DELETE':
        sc_id = request.args.get('id')
        name = request.args.get('name')
        
        sc = None
        if sc_id:
            sc = ServiceCenter.query.get(sc_id)
        elif name:
            sc = ServiceCenter.query.filter_by(name=name).first()
            
        if sc:
            db.session.delete(sc)
            db.session.commit()
            return jsonify({"status": "Deleted"})
        return jsonify({"error": "Not found"}), 404

@app.route('/api/company', methods=['GET', 'PUT'])
@login_required
def manage_company():
    info = CompanyInfo.query.first()
    if not info:
        info = CompanyInfo()
        db.session.add(info)
        db.session.commit()

    if request.method == 'GET':
        return jsonify(info.to_dict())

    data = request.json
    for key, val in data.items():
        if hasattr(info, key) and key != 'id':
            setattr(info, key, val)
    db.session.commit()
    return jsonify(info.to_dict())



@app.errorhandler(Exception)
def handle_exception(e):
    # Pass through HTTP errors
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    # Handle non-HTTP exceptions
    print(f"Unhandled Exception: {e}")
    return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
