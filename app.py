import sqlite3
import os
from datetime import datetime
from functools import wraps

import uuid

from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(APP_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

app = Flask(__name__)
app.secret_key = "kisandirect-dev-secret-key-change-in-production"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + (1 * 1024 * 1024)

# Copyright-safe demo images sourced from Wikimedia Commons.
# These are remote only for seeded/demo listings; farmer uploads remain local files.
DEMO_IMAGE_MAP = {
    "Tomato": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tomato_vegetable.jpg",
    "Onion": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Regular_yellow_onion.jpg",
    "Potato": "https://commons.wikimedia.org/wiki/Special:Redirect/file/A_Potato.jpg",
    "Wheat": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Wheat_Grain.jpg",
    "Rice": "https://commons.wikimedia.org/wiki/Special:Redirect/file/A_healthy_rice_grain.jpg",
    "Maize": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Corn_or_maize.jpg",
    "Mango": "https://commons.wikimedia.org/wiki/Special:Redirect/file/G_mango.jpg",
    "Banana": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Banana_Bunch.jpg",
    "Grapes": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Stack_of_Grapes.jpg",
    "Turmeric": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Curcuma_longa-5-yercaud-salem-India.JPG",
}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def demo_image_for(product_name):
    return DEMO_IMAGE_MAP.get(product_name)


@app.template_filter("product_image")
def product_image(filename):
    if not filename:
        return None
    if filename.startswith(("http://", "https://")):
        return filename
    return url_for("static", filename="uploads/" + filename)


def save_product_image(file_storage):
    """Save an uploaded product photo and return its stored filename, or None."""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_name))
    return unique_name

# ---------- Admin credentials (not shown on homepage) ----------
ADMIN_EMAIL = "admin@kisandirect.in"
ADMIN_PASSWORD_HASH = generate_password_hash("Admin@123")

# Simplified transparent-pricing constants (illustrative demo values)
LOGISTICS_COST_PER_UNIT = 3
PLATFORM_FEE_PER_UNIT = 1


# ---------------------- Database helpers ----------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    fresh = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            city TEXT,
            district TEXT,
            state TEXT,
            preferred_crops TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            quantity REAL,
            unit TEXT,
            quality TEXT,
            price REAL,
            harvest_date TEXT,
            location TEXT,
            description TEXT,
            status TEXT DEFAULT 'Available',
            image_filename TEXT,
            created_at TEXT,
            FOREIGN KEY (farmer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER NOT NULL,
            farmer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity REAL,
            product_price REAL,
            logistics_cost REAL,
            platform_fee REAL,
            total_amount REAL,
            farmer_earnings REAL,
            delivery_address TEXT,
            contact_number TEXT,
            status TEXT DEFAULT 'Order Placed',
            created_at TEXT,
            FOREIGN KEY (buyer_id) REFERENCES users(id),
            FOREIGN KEY (farmer_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crop_name TEXT,
            price REAL,
            suggested_min REAL,
            suggested_max REAL
        );
        """
    )
    conn.commit()

    # Migration: add image_filename to products table if it doesn't exist yet
    # (covers databases created before photo uploads were added)
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(products)").fetchall()]
    if "image_filename" not in existing_cols:
        c.execute("ALTER TABLE products ADD COLUMN image_filename TEXT")
        conn.commit()

    # Backfill images for the existing seeded/demo listings. Farmer-uploaded images are left untouched.
    for crop_name, image_url in DEMO_IMAGE_MAP.items():
        c.execute(
            "UPDATE products SET image_filename=? WHERE name=? AND (image_filename IS NULL OR image_filename='')",
            (image_url, crop_name),
        )
    conn.commit()

    if fresh:
        seed_demo_data(conn)

    conn.close()


def seed_demo_data(conn):
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    farmers = [
        ("Ramesh Patil", "ramesh@example.com", "9876500001", "Baramati", "Pune", "Maharashtra", "Tomato, Onion"),
        ("Suresh Yadav", "suresh@example.com", "9876500002", "Nashik", "Nashik", "Maharashtra", "Onion, Grapes"),
        ("Lakshmi Devi", "lakshmi@example.com", "9876500003", "Kurnool", "Kurnool", "Andhra Pradesh", "Rice, Turmeric"),
        ("Harpreet Singh", "harpreet@example.com", "9876500004", "Ludhiana", "Ludhiana", "Punjab", "Wheat, Maize"),
        ("Meena Kumari", "meena@example.com", "9876500005", "Nagpur", "Nagpur", "Maharashtra", "Banana, Mango"),
    ]
    farmer_ids = []
    for f in farmers:
        pw = generate_password_hash("password123")
        c.execute(
            "INSERT INTO users (name, email, phone, password, role, city, district, state, preferred_crops, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f[0], f[1], f[2], pw, "farmer", f[3], f[4], f[5], f[6], now),
        )
        farmer_ids.append(c.lastrowid)

    buyers = [
        ("Anjali Sharma", "anjali@example.com", "9876600001", "Pune", "Pune", "Maharashtra"),
        ("Rahul Verma", "rahul@example.com", "9876600002", "Mumbai", "Mumbai", "Maharashtra"),
        ("Priya Nair", "priya@example.com", "9876600003", "Bengaluru", "Bengaluru", "Karnataka"),
        ("Vikram Rao", "vikram@example.com", "9876600004", "Hyderabad", "Hyderabad", "Telangana"),
        ("Sneha Joshi", "sneha@example.com", "9876600005", "Nagpur", "Nagpur", "Maharashtra"),
    ]
    buyer_ids = []
    for b in buyers:
        pw = generate_password_hash("password123")
        c.execute(
            "INSERT INTO users (name, email, phone, password, role, city, district, state, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (b[0], b[1], b[2], pw, "buyer", b[3], b[4], b[5], now),
        )
        buyer_ids.append(c.lastrowid)

    market_prices = [
        ("Tomato", 28, 27, 30),
        ("Onion", 32, 30, 33),
        ("Potato", 25, 24, 27),
        ("Wheat", 30, 29, 32),
        ("Rice", 40, 38, 42),
        ("Maize", 22, 21, 24),
        ("Mango", 60, 55, 65),
        ("Banana", 35, 32, 38),
        ("Grapes", 70, 65, 75),
        ("Turmeric", 90, 85, 95),
    ]
    for m in market_prices:
        c.execute(
            "INSERT INTO market_prices (crop_name, price, suggested_min, suggested_max) VALUES (?,?,?,?)",
            m,
        )

    products = [
        ("Tomato", "Vegetables", 500, "kg", "Grade A", 27, "2026-08-20", "Baramati, Pune", "Fresh farm tomatoes."),
        ("Onion", "Vegetables", 800, "kg", "Grade A", 31, "2026-08-18", "Nashik, Nashik", "Well-cured red onions."),
        ("Potato", "Vegetables", 600, "kg", "Grade B", 25, "2026-08-15", "Baramati, Pune", "Table potatoes."),
        ("Wheat", "Grains", 1000, "quintal", "Grade A", 30, "2026-08-10", "Ludhiana, Ludhiana", "High-protein wheat."),
        ("Rice", "Grains", 700, "quintal", "Grade A", 40, "2026-08-05", "Kurnool, Kurnool", "Sona Masoori rice."),
        ("Maize", "Grains", 500, "quintal", "Grade B", 22, "2026-08-08", "Ludhiana, Ludhiana", "Yellow maize."),
        ("Mango", "Fruits", 300, "kg", "Grade A", 58, "2026-08-01", "Nagpur, Nagpur", "Kesar mangoes."),
        ("Banana", "Fruits", 400, "dozen", "Grade A", 34, "2026-08-22", "Nagpur, Nagpur", "Robusta bananas."),
        ("Grapes", "Fruits", 250, "kg", "Grade A", 68, "2026-08-12", "Nashik, Nashik", "Thompson seedless grapes."),
        ("Turmeric", "Spices", 150, "kg", "Grade A", 88, "2026-07-30", "Kurnool, Kurnool", "Finger turmeric, high curcumin."),
        ("Tomato", "Vegetables", 300, "kg", "Grade B", 26, "2026-08-19", "Nashik, Nashik", "Slightly smaller tomatoes."),
        ("Onion", "Vegetables", 450, "kg", "Grade B", 29, "2026-08-14", "Baramati, Pune", "Medium sized onions."),
        ("Wheat", "Grains", 800, "quintal", "Grade B", 28, "2026-08-11", "Nagpur, Nagpur", "Sharbati wheat."),
        ("Mango", "Fruits", 200, "kg", "Grade B", 52, "2026-08-02", "Kurnool, Kurnool", "Totapuri mangoes."),
        ("Turmeric", "Spices", 100, "kg", "Grade B", 82, "2026-07-28", "Nagpur, Nagpur", "Bulb turmeric."),
    ]
    farmer_cycle = farmer_ids * 3
    for i, p in enumerate(products):
        fid = farmer_cycle[i]
        c.execute(
            """INSERT INTO products
            (farmer_id, name, category, quantity, unit, quality, price, harvest_date, location, description, status, image_filename, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fid, p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], "Available", demo_image_for(p[0]), now),
        )

    sample_orders = [
        (buyer_ids[0], farmer_ids[0], 1, 10, "Order Placed"),
        (buyer_ids[1], farmer_ids[1], 2, 20, "Farmer Accepted"),
        (buyer_ids[2], farmer_ids[2], 5, 15, "Completed"),
    ]
    for so in sample_orders:
        buyer_id, farmer_id, product_id, qty, status = so
        c.execute("SELECT price FROM products WHERE id=?", (product_id,))
        row = c.fetchone()
        price = row[0] if row else 25
        logistics = LOGISTICS_COST_PER_UNIT * qty
        fee = PLATFORM_FEE_PER_UNIT * qty
        total = price * qty + logistics + fee
        earnings = price * qty
        c.execute(
            """INSERT INTO orders
            (buyer_id, farmer_id, product_id, quantity, product_price, logistics_cost, platform_fee,
             total_amount, farmer_earnings, delivery_address, contact_number, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (buyer_id, farmer_id, product_id, qty, price, logistics, fee, total, earnings,
             "123 Demo Street, Pune", "9998887770", status, now),
        )

    conn.commit()


# ---------------------- Auth helpers ----------------------
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("You are not authorized to view that page.", "error")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def current_user():
    if "user_id" not in session:
        return None
    if session.get("role") == "admin":
        return {"name": "Admin", "role": "admin"}
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()


@app.context_processor
def inject_user():
    return {"current_user": current_user(), "session": session}


# ---------------------- Public pages ----------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/impact")
def impact():
    return render_template("impact.html")


# ---------------------- Registration ----------------------
@app.route("/register/farmer", methods=["GET", "POST"])
def register_farmer():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        village = request.form.get("village", "").strip()
        district = request.form.get("district", "").strip()
        state = request.form.get("state", "").strip()
        crops = request.form.get("crops", "").strip()

        if not all([name, phone, email, password, village, district, state]):
            flash("Please fill all required fields.", "error")
            return render_template("register_farmer.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            flash("An account with this email already exists.", "error")
            return render_template("register_farmer.html")

        db.execute(
            "INSERT INTO users (name, email, phone, password, role, city, district, state, preferred_crops, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, email, phone, generate_password_hash(password), "farmer", village, district, state, crops,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register_farmer.html")


@app.route("/register/buyer", methods=["GET", "POST"])
def register_buyer():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        city = request.form.get("city", "").strip()
        district = request.form.get("district", "").strip()
        state = request.form.get("state", "").strip()

        if not all([name, phone, email, password, city, district, state]):
            flash("Please fill all required fields.", "error")
            return render_template("register_buyer.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            flash("An account with this email already exists.", "error")
            return render_template("register_buyer.html")

        db.execute(
            "INSERT INTO users (name, email, phone, password, role, city, district, state, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (name, email, phone, generate_password_hash(password), "buyer", city, district, state,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register_buyer.html")


# ---------------------- Login / Logout ----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE (email=? OR phone=?) AND role=?",
            (identifier, identifier, role),
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["name"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("farmer_dashboard" if role == "farmer" else "buyer_dashboard"))
        else:
            flash("Invalid credentials or role.", "error")

    return render_template("login.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if email == ADMIN_EMAIL and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["user_id"] = 0
            session["role"] = "admin"
            session["name"] = "Admin"
            flash("Welcome, Admin.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.", "error")
    return render_template("admin_login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ---------------------- Farmer routes ----------------------
@app.route("/farmer/dashboard")
@login_required(role="farmer")
def farmer_dashboard():
    db = get_db()
    fid = session["user_id"]
    active_listings = db.execute(
        "SELECT COUNT(*) c FROM products WHERE farmer_id=? AND status='Available'", (fid,)
    ).fetchone()["c"]
    pending_orders = db.execute(
        "SELECT COUNT(*) c FROM orders WHERE farmer_id=? AND status NOT IN ('Completed','Delivered')", (fid,)
    ).fetchone()["c"]
    completed_orders = db.execute(
        "SELECT COUNT(*) c FROM orders WHERE farmer_id=? AND status='Completed'", (fid,)
    ).fetchone()["c"]
    total_earnings = db.execute(
        "SELECT COALESCE(SUM(farmer_earnings),0) s FROM orders WHERE farmer_id=? AND status='Completed'", (fid,)
    ).fetchone()["s"]
    return render_template(
        "farmer/dashboard.html",
        active_listings=active_listings,
        pending_orders=pending_orders,
        completed_orders=completed_orders,
        total_earnings=total_earnings,
    )


@app.route("/farmer/products")
@login_required(role="farmer")
def farmer_products():
    db = get_db()
    products = db.execute(
        "SELECT * FROM products WHERE farmer_id=? ORDER BY created_at DESC", (session["user_id"],)
    ).fetchall()
    return render_template("farmer/products.html", products=products)


@app.route("/farmer/products/<int:product_id>/delete")
@login_required(role="farmer")
def farmer_delete_product(product_id):
    db = get_db()
    product = db.execute(
        "SELECT image_filename FROM products WHERE id=? AND farmer_id=?", (product_id, session["user_id"])
    ).fetchone()
    db.execute("DELETE FROM products WHERE id=? AND farmer_id=?", (product_id, session["user_id"]))
    db.commit()
    if product and product["image_filename"] and not product["image_filename"].startswith(("http://", "https://")):
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], product["image_filename"])
        if os.path.exists(img_path):
            os.remove(img_path)
    flash("Product removed.", "success")
    return redirect(url_for("farmer_products"))


@app.route("/farmer/add_product", methods=["GET", "POST"])
@login_required(role="farmer")
def add_product():
    db = get_db()
    suggestion = None
    check_crop = request.args.get("check_crop", "").strip()
    check_price = request.args.get("check_price", type=float)
    if check_crop:
        row = db.execute(
            "SELECT * FROM market_prices WHERE LOWER(crop_name)=LOWER(?)", (check_crop,)
        ).fetchone()
        if row:
            suggestion = {
                "crop": check_crop,
                "ref_price": row["price"],
                "min": row["suggested_min"],
                "max": row["suggested_max"],
                "entered": check_price,
            }
        else:
            base = check_price if check_price else 25
            suggestion = {
                "crop": check_crop,
                "ref_price": None,
                "min": round(base * 0.9, 2),
                "max": round(base * 1.1, 2),
                "entered": check_price,
            }

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category")
        quantity = request.form.get("quantity", type=float)
        unit = request.form.get("unit")
        quality = request.form.get("quality")
        price = request.form.get("price", type=float)
        harvest_date = request.form.get("harvest_date")
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()

        if not all([name, category, quantity, unit, quality, price, harvest_date, location]):
            flash("Please fill all required fields.", "error")
        else:
            image_file = request.files.get("image")
            if image_file and image_file.filename and not allowed_file(image_file.filename):
                flash("Photo must be a PNG, JPG, GIF, or WEBP file.", "error")
                return render_template("farmer/add_product.html", suggestion=suggestion,
                                       check_crop=check_crop, check_price=check_price)
            image_filename = save_product_image(image_file)

            db.execute(
                """INSERT INTO products
                (farmer_id, name, category, quantity, unit, quality, price, harvest_date, location, description, status, image_filename, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session["user_id"], name, category, quantity, unit, quality, price, harvest_date, location,
                 description, "Available", image_filename, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            db.commit()
            flash("Your product has been successfully listed.", "success")
            return redirect(url_for("farmer_products"))

    return render_template("farmer/add_product.html", suggestion=suggestion,
                           check_crop=check_crop, check_price=check_price)


@app.route("/farmer/market_prices")
@login_required(role="farmer")
def market_prices():
    db = get_db()
    prices = db.execute("SELECT * FROM market_prices ORDER BY crop_name").fetchall()
    return render_template("farmer/market_prices.html", prices=prices)


@app.route("/farmer/orders", methods=["GET", "POST"])
@login_required(role="farmer")
def farmer_orders():
    db = get_db()
    if request.method == "POST":
        order_id = request.form.get("order_id", type=int)
        action = request.form.get("action")

        order = db.execute(
            "SELECT * FROM orders WHERE id=? AND farmer_id=?", (order_id, session["user_id"])
        ).fetchone()
        if order:
            if action == "accept":
                db.execute("UPDATE orders SET status='Farmer Accepted' WHERE id=?", (order_id,))
            elif action == "reject":
                db.execute("UPDATE orders SET status='Rejected' WHERE id=?", (order_id,))
            elif action in ("Preparing", "Ready for Delivery", "Delivered", "Completed"):
                db.execute("UPDATE orders SET status=? WHERE id=?", (action, order_id))
            db.commit()
            flash("Order updated.", "success")

    orders = db.execute(
        """SELECT o.*, p.name as product_name, u.name as buyer_name
           FROM orders o
           JOIN products p ON o.product_id = p.id
           JOIN users u ON o.buyer_id = u.id
           WHERE o.farmer_id=? ORDER BY o.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    return render_template("farmer/orders.html", orders=orders)


@app.route("/farmer/earnings")
@login_required(role="farmer")
def farmer_earnings():
    db = get_db()
    fid = session["user_id"]
    total_sales = db.execute("SELECT COUNT(*) c FROM orders WHERE farmer_id=?", (fid,)).fetchone()["c"]
    completed_orders = db.execute(
        "SELECT COUNT(*) c FROM orders WHERE farmer_id=? AND status='Completed'", (fid,)
    ).fetchone()["c"]
    total_earnings = db.execute(
        "SELECT COALESCE(SUM(farmer_earnings),0) s FROM orders WHERE farmer_id=? AND status='Completed'", (fid,)
    ).fetchone()["s"]
    pending_earnings = db.execute(
        "SELECT COALESCE(SUM(farmer_earnings),0) s FROM orders WHERE farmer_id=? AND status!='Completed' AND status!='Rejected'",
        (fid,),
    ).fetchone()["s"]
    return render_template(
        "farmer/earnings.html",
        total_sales=total_sales,
        completed_orders=completed_orders,
        total_earnings=total_earnings,
        pending_earnings=pending_earnings,
    )


# ---------------------- Buyer routes ----------------------
@app.route("/buyer/dashboard")
@login_required(role="buyer")
def buyer_dashboard():
    db = get_db()
    bid = session["user_id"]
    available_products = db.execute("SELECT COUNT(*) c FROM products WHERE status='Available'").fetchone()["c"]
    my_orders = db.execute("SELECT COUNT(*) c FROM orders WHERE buyer_id=?", (bid,)).fetchone()["c"]
    pending_orders = db.execute(
        "SELECT COUNT(*) c FROM orders WHERE buyer_id=? AND status NOT IN ('Completed','Rejected')", (bid,)
    ).fetchone()["c"]
    completed_orders = db.execute(
        "SELECT COUNT(*) c FROM orders WHERE buyer_id=? AND status='Completed'", (bid,)
    ).fetchone()["c"]
    return render_template(
        "buyer/dashboard.html",
        available_products=available_products,
        my_orders=my_orders,
        pending_orders=pending_orders,
        completed_orders=completed_orders,
    )


@app.route("/buyer/products")
@login_required(role="buyer")
def buyer_products():
    db = get_db()
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    location = request.args.get("location", "").strip()
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)

    sql = """SELECT p.*, u.name as farmer_name FROM products p
             JOIN users u ON p.farmer_id = u.id WHERE p.status='Available'"""
    params = []
    if q:
        sql += " AND p.name LIKE ?"
        params.append(f"%{q}%")
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if location:
        sql += " AND p.location LIKE ?"
        params.append(f"%{location}%")
    if min_price is not None:
        sql += " AND p.price >= ?"
        params.append(min_price)
    if max_price is not None:
        sql += " AND p.price <= ?"
        params.append(max_price)
    sql += " ORDER BY p.created_at DESC"

    products = db.execute(sql, params).fetchall()
    categories = ["Vegetables", "Fruits", "Grains", "Pulses", "Spices", "Other"]
    return render_template(
        "buyer/products.html", products=products, categories=categories,
        q=q, category=category, location=location, min_price=min_price, max_price=max_price,
    )


@app.route("/buyer/product/<int:product_id>", methods=["GET", "POST"])
@login_required(role="buyer")
def product_details(product_id):
    db = get_db()
    product = db.execute(
        """SELECT p.*, u.name as farmer_name, u.district as farmer_district, u.state as farmer_state
           FROM products p JOIN users u ON p.farmer_id = u.id WHERE p.id=?""",
        (product_id,),
    ).fetchone()
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("buyer_products"))

    if request.method == "POST":
        quantity = request.form.get("quantity", type=float)
        address = request.form.get("address", "").strip()
        contact = request.form.get("contact", "").strip()

        if not quantity or quantity <= 0 or quantity > product["quantity"]:
            flash("Please enter a valid quantity.", "error")
        elif not address or not contact:
            flash("Delivery address and contact number are required.", "error")
        else:
            logistics = LOGISTICS_COST_PER_UNIT * quantity
            fee = PLATFORM_FEE_PER_UNIT * quantity
            farmer_earnings = product["price"] * quantity
            total = farmer_earnings + logistics + fee

            db.execute(
                """INSERT INTO orders
                (buyer_id, farmer_id, product_id, quantity, product_price, logistics_cost, platform_fee,
                 total_amount, farmer_earnings, delivery_address, contact_number, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session["user_id"], product["farmer_id"], product_id, quantity, product["price"],
                 logistics, fee, total, farmer_earnings, address, contact, "Order Placed",
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            new_qty = product["quantity"] - quantity
            new_status = "Sold Out" if new_qty <= 0 else "Available"
            db.execute("UPDATE products SET quantity=?, status=? WHERE id=?", (new_qty, new_status, product_id))
            db.commit()
            flash("Order placed successfully!", "success")
            return redirect(url_for("buyer_orders"))

    trad_farmer = round(product["price"] * 0.72, 2)
    trad_consumer = round(product["price"] * 1.4, 2)
    kd_consumer = round(product["price"] + LOGISTICS_COST_PER_UNIT + PLATFORM_FEE_PER_UNIT, 2)

    return render_template(
        "buyer/product_details.html",
        product=product,
        trad_farmer=trad_farmer,
        trad_consumer=trad_consumer,
        kd_consumer=kd_consumer,
        logistics=LOGISTICS_COST_PER_UNIT,
        fee=PLATFORM_FEE_PER_UNIT,
    )


@app.route("/buyer/orders")
@login_required(role="buyer")
def buyer_orders():
    db = get_db()
    orders = db.execute(
        """SELECT o.*, p.name as product_name, u.name as farmer_name
           FROM orders o
           JOIN products p ON o.product_id = p.id
           JOIN users u ON o.farmer_id = u.id
           WHERE o.buyer_id=? ORDER BY o.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    return render_template("buyer/orders.html", orders=orders)


# ---------------------- Admin routes ----------------------
@app.route("/admin/dashboard")
@login_required(role="admin")
def admin_dashboard():
    db = get_db()
    stats = {
        "farmers": db.execute("SELECT COUNT(*) c FROM users WHERE role='farmer'").fetchone()["c"],
        "buyers": db.execute("SELECT COUNT(*) c FROM users WHERE role='buyer'").fetchone()["c"],
        "products": db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        "orders": db.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
        "completed_orders": db.execute("SELECT COUNT(*) c FROM orders WHERE status='Completed'").fetchone()["c"],
        "transaction_value": db.execute("SELECT COALESCE(SUM(total_amount),0) s FROM orders").fetchone()["s"],
    }
    return render_template("admin/dashboard.html", stats=stats)


@app.route("/admin/farmers")
@login_required(role="admin")
def admin_farmers():
    db = get_db()
    farmers = db.execute(
        """SELECT u.*, (SELECT COUNT(*) FROM products p WHERE p.farmer_id=u.id) as listing_count
           FROM users u WHERE role='farmer' ORDER BY u.created_at DESC"""
    ).fetchall()
    return render_template("admin/farmers.html", farmers=farmers)


@app.route("/admin/buyers")
@login_required(role="admin")
def admin_buyers():
    db = get_db()
    buyers = db.execute(
        """SELECT u.*, (SELECT COUNT(*) FROM orders o WHERE o.buyer_id=u.id) as order_count
           FROM users u WHERE role='buyer' ORDER BY u.created_at DESC"""
    ).fetchall()
    return render_template("admin/buyers.html", buyers=buyers)


@app.route("/admin/products")
@login_required(role="admin")
def admin_products():
    db = get_db()
    products = db.execute(
        """SELECT p.*, u.name as farmer_name FROM products p
           JOIN users u ON p.farmer_id = u.id ORDER BY p.created_at DESC"""
    ).fetchall()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/<int:product_id>/delete")
@login_required(role="admin")
def admin_delete_product(product_id):
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (product_id,))
    db.commit()
    flash("Listing removed.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@login_required(role="admin")
def admin_orders():
    db = get_db()
    orders = db.execute(
        """SELECT o.*, p.name as product_name, f.name as farmer_name, b.name as buyer_name
           FROM orders o
           JOIN products p ON o.product_id = p.id
           JOIN users f ON o.farmer_id = f.id
           JOIN users b ON o.buyer_id = b.id
           ORDER BY o.created_at DESC"""
    ).fetchall()
    return render_template("admin/orders.html", orders=orders)


@app.route("/admin/analytics")
@login_required(role="admin")
def admin_analytics():
    db = get_db()
    most_listed = db.execute(
        "SELECT name, COUNT(*) c FROM products GROUP BY name ORDER BY c DESC LIMIT 5"
    ).fetchall()
    most_ordered = db.execute(
        """SELECT p.name, COUNT(*) c FROM orders o JOIN products p ON o.product_id=p.id
           GROUP BY p.name ORDER BY c DESC LIMIT 5"""
    ).fetchall()
    total_listed_qty = db.execute("SELECT COALESCE(SUM(quantity),0) s FROM products").fetchone()["s"]
    total_sold_qty = db.execute("SELECT COALESCE(SUM(quantity),0) s FROM orders").fetchone()["s"]
    total_transaction_value = db.execute("SELECT COALESCE(SUM(total_amount),0) s FROM orders").fetchone()["s"]
    avg_price = db.execute("SELECT COALESCE(AVG(price),0) a FROM products").fetchone()["a"]

    comparison = [
        ("Tomato", 35, 29, 18, 25),
        ("Onion", 40, 34, 24, 30),
        ("Potato", 32, 27, 16, 23),
        ("Wheat", 38, 33, 22, 28),
    ]
    return render_template(
        "admin/analytics.html",
        most_listed=most_listed,
        most_ordered=most_ordered,
        total_listed_qty=total_listed_qty,
        total_sold_qty=total_sold_qty,
        total_transaction_value=total_transaction_value,
        avg_price=avg_price,
        comparison=comparison,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
