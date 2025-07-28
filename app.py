# app.py
import os
import re
import requests
from math import ceil
from os.path import join, dirname, splitext
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
import bcrypt
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId

# ------------------------------ #
# 1) LOAD ENVIRONMENT VARIABLES  #
# ------------------------------ #
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

MONGODB_URI = os.environ.get("MONGODB_URI")
DB_NAME = os.environ.get("DB_NAME")

client = MongoClient(MONGODB_URI)
db = client[DB_NAME]

# ------------------------- #
# 2) INITIALIZE FLASK APP   #
# ------------------------- #
app = Flask(__name__)
app.secret_key = "mrpw07"  # Ganti dengan kunci sebenarnya di produksi



# ---------------------------- #
# 3) UPLOAD FOLDERS & CONFIG   #
# ---------------------------- #
# Folder untuk galeri
UPLOAD_FOLDER_MAIN_HEADERS = os.path.join(app.root_path, "static/images/main_headers")
os.makedirs(UPLOAD_FOLDER_MAIN_HEADERS, exist_ok=True)

UPLOAD_FOLDER_LOGO = os.path.join(app.root_path, "static/images/logo")
os.makedirs(UPLOAD_FOLDER_LOGO, exist_ok=True)

UPLOAD_FOLDER_HEADERS = os.path.join(app.root_path, "static/images/headers")
os.makedirs(UPLOAD_FOLDER_HEADERS, exist_ok=True)

UPLOAD_FOLDER_AVATAR = os.path.join(app.root_path, "static/images/avatars")
os.makedirs(UPLOAD_FOLDER_AVATAR, exist_ok=True)

UPLOAD_FOLDER_ABOUT = os.path.join(app.root_path, "static/images/about")
os.makedirs(UPLOAD_FOLDER_ABOUT, exist_ok=True)

UPLOAD_FOLDER_GALLERY = join(app.root_path, "static/images/gallery")
os.makedirs(UPLOAD_FOLDER_GALLERY, exist_ok=True)

UPLOAD_FOLDER_EXTRACURRICULAR = os.path.join(app.root_path, "static/images/extracurricular")
os.makedirs(UPLOAD_FOLDER_EXTRACURRICULAR, exist_ok=True)

UPLOAD_FOLDER_TEACHERS     = join(app.root_path, "static/images/teachers")
os.makedirs(UPLOAD_FOLDER_TEACHERS, exist_ok=True)

UPLOAD_FOLDER_PUBLICATIONS = join(app.root_path, "static/images/publications")
os.makedirs(UPLOAD_FOLDER_PUBLICATIONS, exist_ok=True)

app.config["UPLOAD_FOLDER_MAIN_HEADERS"] = UPLOAD_FOLDER_MAIN_HEADERS
app.config["UPLOAD_FOLDER_LOGO"] = UPLOAD_FOLDER_LOGO
app.config["UPLOAD_FOLDER_HEADERS"] = UPLOAD_FOLDER_HEADERS
app.config["UPLOAD_FOLDER_AVATAR"] = UPLOAD_FOLDER_AVATAR

app.config["UPLOAD_FOLDER_ABOUT"] = UPLOAD_FOLDER_ABOUT
app.config["UPLOAD_FOLDER_GALLERY"]     = UPLOAD_FOLDER_GALLERY
app.config["UPLOAD_FOLDER_EXTRACURRICULAR"] = UPLOAD_FOLDER_EXTRACURRICULAR
app.config["UPLOAD_FOLDER_TEACHERS"]    = UPLOAD_FOLDER_TEACHERS
app.config["UPLOAD_FOLDER_PUBLICATIONS"] = UPLOAD_FOLDER_PUBLICATIONS


# ----------------------------------------- #
# 4) HELPER: LOG ADMIN & NOTIFIKASI ACTION  #
# ----------------------------------------- #
def log_admin_action(admin_id, username, action, description=None):
    # Ambil semua admin ID selain pelaku
    other_admins = db.admin.find({"_id": {"$ne": ObjectId(admin_id)}}, {"_id": 1})
    unread_by = [admin["_id"] for admin in other_admins]

    db.admin_logs.insert_one({
        "admin_id": ObjectId(admin_id),
        "username": username,
        "action": action,
        "description": description or "",
        "timestamp": datetime.now(timezone.utc),
        "unread_by": unread_by
    })


def superadmin_required(fn):
    """Decorator: izinkan hanya jika role = superadmin."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # belum login ➜ ke halaman login
        if "admin_id" not in session:
            return redirect(url_for("login"))

        # sudah login tapi bukan superadmin ➜ tolak akses
        if session.get("admin_role") != "superadmin":
            # 1) kalau mau redirect pakai flash:
            flash("You do not have permission to access that page.", "danger")
            return redirect(url_for("dashboard"))
            # 2) atau cukup:
            # abort(403)
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_notifications():
    if "admin_id" not in session:
        return {}

    current_admin_id = ObjectId(session["admin_id"])

    latest_messages = db.contact_messages.find({"unread_by": current_admin_id}).sort("created_at", -1).limit(3)
    latest_logs = db.admin_logs.find({"unread_by": current_admin_id}).sort("timestamp", -1).limit(3)

    notifications = []

    for msg in latest_messages:
        notifications.append({
            "type": "message",
            "title": f"{msg.get('name')} mengirim pesan",
            "content": msg.get('message', '')[:50] + ("..." if len(msg.get('message', '')) > 50 else ""),
            "icon": "ti ti-mail",
            "time": msg.get("created_at"),
            "badge": "Pesan Baru",
            "badge_class": "bg-light-primary"
        })

    for log in latest_logs:
        notifications.append({
            "type": "log",
            "title": f"{log.get('username')} melakukan {log.get('action')}",
            "content": log.get("description", ""),
            "icon": "ti ti-activity",
            "time": log.get("timestamp"),
            "badge": "Aktivitas Admin",
            "badge_class": "bg-light-success"
        })

    return dict(notifications=notifications)


@app.route("/notifications/mark_all_read")
def mark_all_notifications_read():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    admin_id = ObjectId(session["admin_id"])

    # Hapus admin_id dari unread_by
    db.contact_messages.update_many(
        {"unread_by": admin_id},
        {"$pull": {"unread_by": admin_id}}
    )
    db.admin_logs.update_many(
        {"unread_by": admin_id},
        {"$pull": {"unread_by": admin_id}}
    )

    return redirect(request.referrer or url_for('dashboard'))


# ------------------------------- #
# 5) PUBLIC (FRONTEND) ROUTES     #
# ------------------------------- #
@app.route("/")
def home():
    facilities = list(db.facilities.find())
    about_data = db.about.find_one()
    publications = list(db.publications.find().sort("created_at", -1).limit(3))
    return render_template(
        "user/index.html",
        about=about_data,
        active_page="home",
        facilities=facilities,
        publications=publications
    )


@app.route("/about")
def about():
    about_data = db.about.find_one()
    return render_template("user/about.html", about=about_data, active_page="about")


@app.route("/extracurricular")
def extracurricular_page():
    data = list(db.extracurricular.find())
    return render_template("user/extracurricular.html", active_page="extracurricular_page", extracurriculars=data)


@app.route("/extracurricular/<extracurricular_id>")
def extracurricular_detail(extracurricular_id):
    try:
        obj_id = ObjectId(extracurricular_id)
    except:
        return redirect(url_for("extracurricular_page"))

    extracurricular = db.extracurricular.find_one({"_id": obj_id})
    if not extracurricular:
        return redirect(url_for("extracurricular_page"))

    other_extracurriculars = list(db.extracurricular.find({"_id": {"$ne": obj_id}}).limit(3))

    return render_template(
        "user/detail_extracurricular.html",
        extracurricular_data=extracurricular,
        other_classes=other_extracurriculars,
        active_page="extracurricular",
        detail_type="extracurricular"
    )


@app.route("/teachers")
def teachers():
    # Ambil daftar guru dari DB, urutkan berdasarkan nama
    teacher_docs = list(db.teachers.find().sort("name", 1))
    return render_template(
        "user/teachers.html",
        active_page="teacher",
        teachers=teacher_docs
    )


@app.route("/gallery")
def gallery():
    galleries = list(db.gallery.find().sort("uploaded_at", -1))
    for img in galleries:
        img["source"] = "gallery"
        img["category"] = "Other"
        img["uploaded_at"] = img.get("uploaded_at")

    publication_images = list(db.publications.find({"feature_image": {"$ne": None}}).sort("created_at", -1))
    for pub in publication_images:
        galleries.append({
            "_id": str(pub["_id"]),
            "filename": pub["feature_image"],
            "title": pub["title"],
            "source": "publication",
            "category": pub.get("category", "News"),
            "uploaded_at": pub.get("created_at")
        })

    return render_template("user/gallery.html", active_page="gallery", galleries=galleries)


@app.route("/news_articles")
def news_articles():
    per_page = 5
    page = int(request.args.get("page", 1))
    skip = (page - 1) * per_page

    # Ambil total artikel
    total_articles = db.publications.count_documents({})
    total_pages = ceil(total_articles / per_page)

    # Ambil artikel untuk halaman saat ini
    all_articles = list(
        db.publications.find().sort("created_at", -1).skip(skip).limit(per_page)
    )

    # Hitung komentar untuk setiap artikel
    for article in all_articles:
        article["comment_count"] = db.comments.count_documents({"article_id": str(article["_id"])})

    # Ambil kategori dan hitung jumlahnya
    categories = db.publications.distinct("category")
    category_counts = {
        cat: db.publications.count_documents({"category": cat}) for cat in categories
    }

    # Sidebar: Artikel terbaru per kategori dengan jumlah komentar
    latest_by_category = {}
    for cat in categories:
        posts = db.publications.find({"category": cat}).sort("created_at", -1).limit(3)
        post_list = []
        for post in posts:
            post = dict(post)
            post["comment_count"] = db.comments.count_documents({"article_id": str(post["_id"])})
            post_list.append(post)
        latest_by_category[cat] = post_list

    # Buat pagination
    if total_pages <= 5:
        pages = list(range(1, total_pages + 1))
    elif page <= 3:
        pages = list(range(1, 6))
    elif page >= total_pages - 2:
        pages = list(range(total_pages - 4, total_pages + 1))
    else:
        pages = list(range(page - 2, page + 3))

    return render_template(
        "user/news_articles.html",
        active_page="news_articles",
        articles=all_articles,
        category_counts=category_counts,
        latest_by_category=latest_by_category,
        page=page,
        pages=pages,
        total_pages=total_pages
    )


@app.route("/single/<article_id>", methods=["GET", "POST"])
def single(article_id):
    try:
        obj_id = ObjectId(article_id)
    except:
        return "Invalid article ID", 404

    article = db.publications.find_one({"_id": obj_id})
    if not article:
        return "Article not found", 404

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        comment_doc = {
            "article_id": article_id,
            "name": name,
            "email": email,
            "text": message,
            "avatar_url": None,
            "created_at": datetime.now(timezone.utc)
        }
        db.comments.insert_one(comment_doc)
        flash("Comment submitted successfully.", "success")
        return redirect(url_for("single", article_id=article_id))

    comments_list = list(
        db.comments.find({"article_id": article_id}).sort("created_at", 1)
    )
    for c in comments_list:
        c["created_at_formatted"] = c["created_at"].strftime("%d %b %Y at %I:%M %p")

    # Related posts (exclude current)
    related_docs = list(
        db.publications.find({
            "_id": {"$ne": obj_id},
            "category": article.get("category")
        }).sort("created_at", -1).limit(3)
    )
    related_posts = []
    for r in related_docs:
        r_id_str = str(r["_id"])
        cnt = db.comments.count_documents({"article_id": r_id_str})
        r["comments_count"] = cnt
        related_posts.append(r)

    # Latest posts dari kategori yang sama
    latest_posts = list(
        db.publications.find({
            "_id": {"$ne": obj_id},
            "category": article.get("category")
        }).sort("created_at", -1).limit(3)
    )

    category_counts = {
        cat: db.publications.count_documents({"category": cat})
        for cat in ["News", "Articles", "Announcement", "Event"]
    }

    return render_template(
        "user/single.html",
        article=article,
        related_posts=related_posts,
        comments=comments_list,
        category_counts=category_counts,
        latest_posts=latest_posts,
        active_page="single"
    )

@app.route("/contact")
def contact():
    contact_data = db.contact.find_one() or {}

    return render_template(
        "user/contact.html",
        active_page="contact",
        contact=contact_data
    )

RECAPTCHA_SECRET_KEY = "6Lc8EIorAAAAAGSezt6y9xhzlxBohBHMTRUOZBvb"
@app.route("/send_message", methods=["POST"])
def submit_contact_message():
    name    = request.form.get("name", "").strip()
    email   = request.form.get("email", "").strip()
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()
    recaptcha_response = request.form.get("g-recaptcha-response")

    # Validasi reCAPTCHA
    if not recaptcha_response:
        flash("Verifikasi CAPTCHA diperlukan.", "danger")
        return redirect(url_for("contact"))

    recaptcha_verify = requests.post(
        "https://www.google.com/recaptcha/api/siteverify",
        data={
            "secret": RECAPTCHA_SECRET_KEY,
            "response": recaptcha_response
        }
    )
    if not recaptcha_verify.json().get("success"):
        flash("Verifikasi CAPTCHA gagal. Silakan coba lagi.", "danger")
        return redirect(url_for("contact"))

    # Validasi email
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        flash("Alamat email tidak valid.", "danger")
        return redirect(url_for("contact"))

    # Cek duplikat pesan dalam 5 menit
    if db.contact_messages.find_one({"email": email, "created_at": {"$gt": datetime.now(timezone.utc) - timedelta(minutes=5)}}):
        flash("Anda sudah mengirim pesan. Silakan tunggu beberapa menit.", "warning")
        return redirect(url_for("contact"))

    # Simpan pesan
    all_admins = db.admin.find({}, {"_id": 1})
    unread_by = [admin["_id"] for admin in all_admins]
    db.contact_messages.insert_one({
        "name": name,
        "email": email,
        "subject": subject,
        "message": message,
        "created_at": datetime.now(timezone.utc),
        "unread_by": unread_by
    })

    flash("Pesan Anda berhasil dikirim.", "success")
    return redirect(url_for("contact"))


@app.route("/materials/classes")
def materials_classes():
    classes = list(db.classes.find().sort("title", 1))
    return render_template("user/classes.html", active_page="materials_classes",  classes=classes)


@app.route("/materials/subjects/<class_id>")
def materials_subjects(class_id):
    # dokumen kelas
    cls = db.classes.find_one({"_id": ObjectId(class_id)})

    # ⇢ konversi class_id URL (string) ke ObjectId terlebih dahulu
    subjects = list(
        db.subjects.find({"class_id": ObjectId(class_id)}).sort("title", 1)
    )

    return render_template(
        "user/subjects.html",
        class_data=cls,
        subjects=subjects
    )


@app.route("/materials/<subject_id>")
def materials(subject_id):
    subject = db.subjects.find_one({"_id": ObjectId(subject_id)})
    class_data = db.classes.find_one({"_id": ObjectId(subject["class_id"])})
    mats = list(db.materials.find({"subject_id": ObjectId(subject_id)}).sort("created_at", -1))
    return render_template(
        "user/materials.html",
        subject=subject,
        class_id=class_data["_id"],
        class_title=class_data["title"],
        materials=mats
    )


@app.route("/materials/detail/<material_id>")
def detail_material(material_id):
    material = db.materials.find_one({"_id": ObjectId(material_id)})
    subject = db.subjects.find_one({"_id": ObjectId(material["subject_id"])})
    class_data = db.classes.find_one({"_id": ObjectId(subject["class_id"])})
    more_materials = list(db.materials.find({
        "subject_id": str(subject["_id"]),
        "_id": {"$ne": ObjectId(material_id)}
    }).sort("created_at", -1).limit(3))
    return render_template(
        "user/detail_materials.html",
        material=material,
        subject=subject,
        class_id=class_data["_id"],
        class_title=class_data["title"],
        more_materials=more_materials
    )


# ---------------------------------- #
# 6) ADMIN AUTHENTICATION & PAGES    #
# ---------------------------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()
        remember = request.form.get("remember")

        admin = db.admin.find_one({"username": username})
        if admin:
            if admin.get("is_blocked", False):
                flash("Your account has been blocked. Please contact the administrator.", "danger")
                return redirect(url_for("login"))

            if bcrypt.checkpw(password.encode('utf-8'), admin['password_hash'].encode('utf-8')):
                session["admin_id"] = str(admin["_id"])
                session["admin_username"] = admin["username"]
                session["admin_role"] = admin["role"]
                session["admin_avatar"] = admin.get("avatar", "default_admin.png")

                if remember:
                    session.permanent = True
                    app.permanent_session_lifetime = timedelta(days=7)
                else:
                    session.permanent = False

                db.admin.update_one(
                    {"_id": admin["_id"]},
                    {"$set": {"last_login": datetime.now(timezone.utc)}}
                )
                log_admin_action(session["admin_id"], session["admin_username"], "Login successful")
                return redirect(url_for("dashboard"))
        
        flash("Incorrect username or password.", "danger")
        return redirect(url_for("login"))

    return render_template("admin/login.html", active_page="login")


@app.route("/logout")
def logout():
    if "admin_id" in session:
        log_admin_action(session["admin_id"], session["admin_username"], "Logout")
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username").strip()
        admin = db.admin.find_one({"username": username})
        if admin:
            flash(
                f"Reset request logged. Please contact superadmin to reset account '{username}'.",
                "info"
            )
        else:
            flash("Username not found", "danger")
        return redirect(url_for("forgot_password"))

    return render_template("admin/forgot_password.html", active_page="forgot")


@app.route("/dashboard")
def dashboard():
    if "admin_id" not in session:
        return redirect(url_for("login"))
    
    total_classes         = db.classes.count_documents({})
    total_extracurricular = db.extracurricular.count_documents({})
    total_publications    = db.publications.count_documents({})
    total_teachers        = db.teachers.count_documents({})
    total_admins          = db.admin.count_documents({"is_blocked": False})
    total_materials       = db.materials.count_documents({})
    total_gallery         = db.gallery.count_documents({})
    total_contacts        = db.contact_messages.count_documents({})

    latest_notifications = list(db.contact_messages.find().sort("created_at", -1).limit(5))
    recent_admin_logs    = list(db.admin_logs.find().sort("timestamp", -1).limit(5))

    return render_template(
        "admin/index.html",
        active_page="dashboard",
        total_classes=total_classes,
        total_extracurricular=total_extracurricular,
        total_publications=total_publications,
        total_teachers=total_teachers,
        total_admins=total_admins,
        total_materials=total_materials,
        total_gallery=total_gallery,
        total_contacts=total_contacts,
        latest_notifications=latest_notifications,
        recent_admin_logs=recent_admin_logs
    )



# ------------------------- #
# 7) ADMIN: MANAJEMEN GURU  #
# ------------------------- #
@app.route("/admin_teachers")
def admin_teachers():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # ── ambil keyword pencarian ─────────────────────────
    search = request.args.get("search", "").strip()

    # filter MongoDB bila ada search
    query = {
        "$or": [
            {"name":        {"$regex": search, "$options": "i"}},
            {"teacher_id":  {"$regex": search, "$options": "i"}},
            {"email":       {"$regex": search, "$options": "i"}},
            {"position":    {"$regex": search, "$options": "i"}},
            {"subject":     {"$regex": search, "$options": "i"}}
        ]
    } if search else {}

    # ── pagination ──────────────────────────────────────
    page      = int(request.args.get("page", 1))
    per_page  = 5
    start_idx = (page - 1) * per_page
    end_idx   = start_idx + per_page

    teacher_docs = list(db.teachers.find(query).sort("name", 1))

    total_teachers   = len(teacher_docs)
    total_pages      = ceil(total_teachers / per_page)
    teachers_display = teacher_docs[start_idx:end_idx]

    return render_template(
        "admin/teachers.html",
        active_page="teachers",
        teachers=teacher_docs,
        teachers_display=teachers_display,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        search=search
    )


@app.route("/teachers/add", methods=["POST"])
def add_teacher():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    teacher_id_input = request.form.get("teacher_id").strip()
    name = request.form.get("name").strip()
    position = request.form.get("position").strip()
    email = request.form.get("email").strip()
    phone = request.form.get("phone").strip()
    instagram = request.form.get("instagram").strip()
    facebook = request.form.get("facebook").strip()
    linkedin = request.form.get("linkedin").strip()

    # Cek duplikasi teacher_id
    existing = db.teachers.find_one({"teacher_id": teacher_id_input})
    if existing:
        flash(f"Teacher ID '{teacher_id_input}' is already in use.", "danger")
        return redirect(url_for("admin_teachers"))

    avatar_filename = None
    if "avatar" in request.files:
        file = request.files["avatar"]
        if file and file.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext = splitext(secure_filename(file.filename))
            new_filename = f"{timestamp}{ext}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER_TEACHERS"], new_filename)
            file.save(save_path)
            avatar_filename = new_filename

    teacher_doc = {
        "teacher_id": teacher_id_input,
        "name": name,
        "position": position,
        "email": email,
        "phone": phone,
        "instagram": instagram,
        "facebook": facebook,
        "linkedin": linkedin,
        "avatar": avatar_filename,
        "created_at": datetime.now(timezone.utc)
    }

    db.teachers.insert_one(teacher_doc)
    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Added teacher (teacher_id: {teacher_id_input})"
    )
    flash("Teacher successfully added.", "success")
    return redirect(url_for("admin_teachers"))


@app.route("/teachers/edit/<orig_teacher_id>", methods=["POST"])
def edit_teacher(orig_teacher_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    teacher = db.teachers.find_one({"teacher_id": orig_teacher_id})
    if not teacher:
        flash("Teacher not found.", "danger")
        return redirect(url_for("admin_teachers"))

    new_teacher_id = request.form.get("teacher_id").strip()
    name = request.form.get("name").strip()
    position = request.form.get("position").strip()
    email = request.form.get("email").strip()
    phone = request.form.get("phone").strip()
    instagram = request.form.get("instagram").strip()
    facebook = request.form.get("facebook").strip()
    linkedin = request.form.get("linkedin").strip()

    # Jika teacher_id berubah → cek duplikasi
    if new_teacher_id != orig_teacher_id:
        existing = db.teachers.find_one({"teacher_id": new_teacher_id})
        if existing:
            flash(f"Teacher ID '{new_teacher_id}' is already in use.", "danger")
            return redirect(url_for("admin_teachers"))

    avatar = teacher.get("avatar")
    if "avatar" in request.files:
        file = request.files["avatar"]
        if file and file.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext = splitext(secure_filename(file.filename))
            new_filename = f"{timestamp}{ext}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER_TEACHERS"], new_filename)
            file.save(save_path)
            avatar = new_filename

    db.teachers.update_one(
        {"teacher_id": orig_teacher_id},
        {"$set": {
            "teacher_id": new_teacher_id,
            "name": name,
            "position": position,
            "email": email,
            "phone": phone,
            "instagram": instagram,
            "facebook": facebook,
            "linkedin": linkedin,
            "avatar": avatar,
            "updated_at": datetime.now(timezone.utc)
        }}
    )
    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Edited teacher (orig_teacher_id: {orig_teacher_id}, new_teacher_id: {new_teacher_id})"
    )
    flash("Teacher updated successfully.", "success")
    return redirect(url_for("admin_teachers"))


@app.route("/teachers/delete/<teacher_id>", methods=["POST"])
def delete_teacher(teacher_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    db.teachers.delete_one({"teacher_id": teacher_id})
    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Deleted teacher (teacher_id: {teacher_id})"
    )
    flash("Teacher deleted successfully.", "success")
    return redirect(url_for("admin_teachers"))


# ----------------------------------------- #
# 8) ADMIN: MANAJEMEN NEWS & ARTICLES       #
# ----------------------------------------- #
@app.route("/admin_news_articles")
def admin_news_articles():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # ── ambil keyword pencarian ───────────────────────
    search = request.args.get("search", "").strip()

    query_filter = {
        "$or": [
            {"title":    {"$regex": search, "$options": "i"}},
            {"category": {"$regex": search, "$options": "i"}},
            {"author":   {"$regex": search, "$options": "i"}}
        ]
    } if search else {}

    # ── pagination ────────────────────────────────────
    page     = int(request.args.get("page", 1))
    per_page = 5
    start    = (page - 1) * per_page
    end      = start + per_page

    # ambil artikel yang sudah difilter
    article_docs = list(db.publications.find(query_filter).sort("created_at", -1))

    total_pages      = ceil(len(article_docs) / per_page)
    articles_display = article_docs[start:end]

    return render_template(
        "admin/news_articles.html",
        active_page="news_articles",
        articles=article_docs,            
        articles_display=articles_display,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search=search                    
    )


@app.route("/articles/add", methods=["POST"])
def add_article():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    title = request.form.get("title").strip()
    category = request.form.get("category").strip()
    content = request.form.get("content")  # HTML dari contenteditable

    # **Hanya satu gambar feature**
    feature_image = None
    if "feature_image" in request.files:
        file = request.files["feature_image"]
        if file and file.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext = splitext(secure_filename(file.filename))
            filename = f"{timestamp}{ext}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER_PUBLICATIONS"], filename)
            file.save(save_path)
            feature_image = filename

    # **Menangani lampiran (attachment)**
    attachment = None
    if "attachment" in request.files:
        file_att = request.files["attachment"]
        if file_att and file_att.filename:
            timestamp2 = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext_att = splitext(secure_filename(file_att.filename))
            filename_att = f"{timestamp2}_att{ext_att}"
            save_path_att = os.path.join(app.config["UPLOAD_FOLDER_PUBLICATIONS"], filename_att)
            file_att.save(save_path_att)
            attachment = filename_att

    new_doc = {
        "title": title,
        "category": category,
        "content": content,
        "feature_image": feature_image,
        "attachment": attachment,  # Simpan nama file lampiran
        "author": session.get("admin_username"),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    inserted = db.publications.insert_one(new_doc)
    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Added article (ID: {inserted.inserted_id})"
    )
    flash("Article added successfully.", "success")
    return redirect(url_for("admin_news_articles"))


@app.route("/articles/edit/<article_id>", methods=["POST"])
def edit_article(article_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    try:
        obj_id = ObjectId(article_id)
    except:
        flash("Invalid article ID.", "danger")
        return redirect(url_for("admin_news_articles"))

    existing = db.publications.find_one({"_id": obj_id})
    if not existing:
        flash("Article not found.", "danger")
        return redirect(url_for("admin_news_articles"))

    title = request.form.get("title").strip()
    category = request.form.get("category").strip()
    content = request.form.get("content")

    # Ambil nama file lama (jika ada)
    feature_image = existing.get("feature_image")
    attachment = existing.get("attachment")

    # Jika ada upload baru untuk feature_image, simpan dan timpa
    if "feature_image" in request.files:
        file = request.files["feature_image"]
        if file and file.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext = splitext(secure_filename(file.filename))
            filename = f"{timestamp}{ext}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER_PUBLICATIONS"], filename)
            file.save(save_path)
            feature_image = filename

    # Jika ada upload baru untuk lampiran (attachment), simpan dan timpa
    if "attachment" in request.files:
        file_att = request.files["attachment"]
        if file_att and file_att.filename:
            timestamp2 = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext_att = splitext(secure_filename(file_att.filename))
            filename_att = f"{timestamp2}_att{ext_att}"
            save_path_att = os.path.join(app.config["UPLOAD_FOLDER_PUBLICATIONS"], filename_att)
            file_att.save(save_path_att)
            attachment = filename_att

    db.publications.update_one(
        {"_id": obj_id},
        {"$set": {
            "title": title,
            "category": category,
            "content": content,
            "feature_image": feature_image,
            "attachment": attachment,
            "updated_at": datetime.now(timezone.utc)
        }}
    )
    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Edited article (ID: {article_id})"
    )
    flash("Article updated successfully.", "success")
    return redirect(url_for("admin_news_articles"))


@app.route("/articles/delete/<article_id>", methods=["POST"])
def delete_article(article_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    try:
        obj_id = ObjectId(article_id)
    except:
        flash("Invalid article ID.", "danger")
        return redirect(url_for("admin_news_articles"))

    db.publications.delete_one({"_id": obj_id})
    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Deleted article (ID: {article_id})"
    )
    flash("Article deleted successfully.", "success")
    return redirect(url_for("admin_news_articles"))


# --------------------------------- #
# 9) ADMIN: MANAJEMEN GALLERY       #
# --------------------------------- #
@app.route("/admin_gallery")
def admin_gallery():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # ── ambil keyword pencarian ──────────────────────
    search = request.args.get("search", "").strip().lower()

    # ── pagination param ─────────────────────────────
    page     = int(request.args.get("page", 1))
    per_page = 5
    skip     = (page - 1) * per_page

    # ── ambil gambar gallery ─────────────────────────
    galleries = list(db.gallery.find().sort("uploaded_at", -1))
    for img in galleries:
        img["source"] = "gallery"

    # ── ambil gambar publications (feature_image) ───
    publication_images = list(
        db.publications.find({"feature_image": {"$ne": None}})
                       .sort("created_at", -1)
    )
    publications_gallery = [
        {
            "_id": str(pub["_id"]),
            "filename": pub["feature_image"],
            "title": pub["title"],
            "uploaded_at": pub.get("created_at", datetime.now(timezone.utc)),
            "source": "publication"
        } for pub in publication_images
    ]

    # ── gabung & sort terbaru ───────────────────────
    combined = galleries + publications_gallery
    combined.sort(key=lambda x: x["uploaded_at"], reverse=True)

    # ── filter search (title atau filename) ─────────
    if search:
        combined = [
            img for img in combined
            if search in img["title"].lower() or search in img["filename"].lower()
        ]

    # ── hitung total & slice pagination ─────────────
    total        = len(combined)
    total_pages  = ceil(total / per_page) or 1
    paginated    = combined[skip:skip + per_page]

    return render_template(
        "admin/gallery.html",
        galleries=paginated,
        page=page,
        total_pages=total_pages,
        search=search 
    )


@app.route("/add_gallery", methods=["POST"])
def add_gallery():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    file = request.files.get("image_file")
    title = request.form.get("title", "").strip()

    if file and file.filename:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext = os.path.splitext(secure_filename(file.filename))
        filename = f"{timestamp}{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER_GALLERY"], filename)
        file.save(save_path)

        db.gallery.insert_one({
            "filename": filename,
            "title": title,
            "uploaded_at": datetime.now(timezone.utc)
        })

        log_admin_action(
            session["admin_id"],
            session["admin_username"],
            f"Added gallery image (filename: {filename})"
        )

        flash("Image uploaded successfully.", "success")
    else:
        flash("No file selected.", "danger")

    return redirect(url_for("admin_gallery"))


@app.route("/edit_gallery/<gallery_id>", methods=["POST"])
def edit_gallery(gallery_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    try:
        obj_id = ObjectId(gallery_id)
    except:
        flash("Invalid gallery ID.", "danger")
        return redirect(url_for("admin_gallery"))

    gallery = db.gallery.find_one({"_id": obj_id})
    if not gallery:
        flash("Gallery image not found.", "danger")
        return redirect(url_for("admin_gallery"))

    title = request.form.get("title", "").strip()

    # Ganti gambar jika ada file baru
    filename = gallery.get("filename")
    if "image_file" in request.files:
        file = request.files["image_file"]
        if file and file.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext = os.path.splitext(secure_filename(file.filename))
            new_filename = f"{timestamp}{ext}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER_GALLERY"], new_filename)
            file.save(save_path)
            filename = new_filename

    db.gallery.update_one(
        {"_id": obj_id},
        {"$set": {
            "title": title,
            "filename": filename,
            "updated_at": datetime.now(timezone.utc)
        }}
    )

    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        f"Edited gallery image (ID: {gallery_id})"
    )

    flash("Gallery image updated successfully.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/delete_gallery/<gallery_id>", methods=["POST"])
def delete_gallery(gallery_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    try:
        obj_id = ObjectId(gallery_id)
    except:
        flash("Invalid gallery ID.", "danger")
        return redirect(url_for("admin_gallery"))

    img = db.gallery.find_one({"_id": obj_id})
    if img:
        # Hapus file dari folder
        img_path = os.path.join(app.config["UPLOAD_FOLDER_GALLERY"], img["filename"])
        if os.path.exists(img_path):
            os.remove(img_path)

        # Hapus dari database
        db.gallery.delete_one({"_id": obj_id})

        log_admin_action(
            session["admin_id"],
            session["admin_username"],
            f"Deleted gallery image (ID: {gallery_id}, filename: {img['filename']})"
        )

        flash("Image deleted successfully.", "success")
    else:
        flash("Image not found.", "danger")

    return redirect(url_for("admin_gallery"))


# ------------------------------- #
# 10) ADMIN: MANAJEMEN CONTACT    #
# ------------------------------- #
from flask import request
from math import ceil

@app.route("/admin_contact")
def admin_contact():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    contact = db.contact.find_one() or {}

    # Ambil search keyword
    search = request.args.get("search", "").strip().lower()

    # Ambil semua data dan filter berdasarkan search
    all_messages = list(db.contact_messages.find().sort("created_at", -1))
    if search:
        all_messages = [
            m for m in all_messages if
            search in m.get("name", "").lower() or
            search in m.get("email", "").lower() or
            search in m.get("subject", "").lower()
        ]

    # Pagination
    page      = int(request.args.get("page", 1))
    per_page  = 5
    start_idx = (page - 1) * per_page
    end_idx   = start_idx + per_page

    total_messages  = len(all_messages)
    total_pages     = ceil(total_messages / per_page) or 1
    contact_messages = all_messages[start_idx:end_idx]

    return render_template(
        "admin/contact.html",
        contact=contact,
        contact_messages=contact_messages,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search=search 
    )


@app.route("/update_contact", methods=["POST"])
def update_contact():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # Ambil data input
    address  = request.form.get("address", "").strip()
    email    = request.form.get("email", "").strip()
    phone    = request.form.get("phone", "").strip()
    hours    = request.form.get("hours", "").strip()
    map_url  = request.form.get("map_url", "").strip()

    data = {
        "address": address,
        "email": email,
        "phone": phone,
        "hours": hours,
        "map_url": map_url,
        "updated_at": datetime.now(timezone.utc)
    }

    if db.contact.count_documents({}) > 0:
        db.contact.update_one({}, {"$set": data})
        action = f"Updated contact info: Address='{address}', Email='{email}', Phone='{phone}', Hours='{hours}', Map URL='{map_url}'"
    else:
        db.contact.insert_one(data)
        action = f"Inserted contact info: Address='{address}', Email='{email}', Phone='{phone}', Hours='{hours}', Map URL='{map_url}'"

    log_admin_action(
        session["admin_id"],
        session["admin_username"],
        action
    )

    flash("Contact info updated successfully.", "success")
    return redirect(url_for("admin_contact"))


@app.route("/delete_contact_message/<message_id>", methods=["POST"])
def delete_contact_message(message_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    try:
        message = db.contact_messages.find_one({"_id": ObjectId(message_id)})
        if not message:
            flash("Message not found.", "warning")
            return redirect(url_for("admin_contact"))

        # Hapus pesan
        db.contact_messages.delete_one({"_id": ObjectId(message_id)})

        # Catat log admin
        action = f"Deleted contact message from '{message.get('name', '')}' with subject '{message.get('subject', '')}'."
        log_admin_action(session["admin_id"], session["admin_username"], action)

        flash("Message deleted successfully.", "success")

    except Exception as e:
        flash(f"Error deleting message: {e}", "danger")

    return redirect(url_for("admin_contact"))


# --------------------------------- #
# 11) ADMIN: MANAJEMEN ABOUT        #
# --------------------------------- #
@app.route("/admin_about", methods=["GET", "POST"])
def admin_about():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    about_data = db.about.find_one()
    settings = db.settings.find_one({}) or {}

    # --- POST update About Section (Deskripsi, Visi, Misi, Gambar Deskripsi) ---
    if request.method == "POST" and request.form.get("form_type") is None:
        description = request.form.get("description", "").strip()
        vision_raw = request.form.get("vision", "").strip()
        mission_raw = request.form.get("mission", "").strip()
        description_image_file = request.files.get("description_image")

        content = {
            "description": description,
            "vision": [v.strip() for v in vision_raw.splitlines() if v.strip()],
            "mission": [m.strip() for m in mission_raw.splitlines() if m.strip()],
            "updated_at": datetime.now(timezone.utc)
        }

        # Simpan gambar deskripsi jika diunggah
        if description_image_file and description_image_file.filename and allowed_image(description_image_file.filename):
            ext = os.path.splitext(secure_filename(description_image_file.filename))[1]
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            fname = f"{ts}{ext}"
            description_image_file.save(os.path.join(app.config['UPLOAD_FOLDER_ABOUT'], fname))
            content["description_image"] = fname

        if about_data:
            db.about.update_one({}, {"$set": content})
            log_admin_action(session["admin_id"], session["admin_username"], "Updated About section")
            flash("Konten tentang sekolah berhasil diperbarui.", "success")
        else:
            db.about.insert_one(content)
            log_admin_action(session["admin_id"], session["admin_username"], "Inserted About section")
            flash("Konten tentang sekolah berhasil ditambahkan.", "success")

        return redirect(url_for("admin_about"))

    # --- POST update School Settings (Logo, Header, Banner Utama, Tagline) ---
    if request.method == "POST" and request.form.get("form_type") == "school":
        school_name = request.form.get("school_name", "").strip()
        school_tagline = request.form.get("school_tagline", "").strip()  # ← Tambahan
        header_file = request.files.get("header_image")
        logo_file = request.files.get("school_logo")
        main_banner_file = request.files.get("main_banner_image")

        update = {
            "school_name": school_name,
            "school_tagline": school_tagline  # ← Tambahan
        }

        if header_file and header_file.filename and allowed_image(header_file.filename):
            ext = os.path.splitext(secure_filename(header_file.filename))[1]
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            fname = f"{ts}{ext}"
            header_file.save(os.path.join(app.config['UPLOAD_FOLDER_HEADERS'], fname))
            update["header_image"] = fname

        if logo_file and logo_file.filename and allowed_image(logo_file.filename):
            ext = os.path.splitext(secure_filename(logo_file.filename))[1]
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            fname = f"{ts}{ext}"
            logo_file.save(os.path.join(app.config['UPLOAD_FOLDER_LOGO'], fname))
            update["school_logo"] = fname

        if main_banner_file and main_banner_file.filename and allowed_image(main_banner_file.filename):
            ext = os.path.splitext(secure_filename(main_banner_file.filename))[1]
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            fname = f"{ts}{ext}"
            main_banner_file.save(os.path.join(app.config['UPLOAD_FOLDER_MAIN_HEADERS'], fname))
            update["main_banner_image"] = fname

        db.settings.update_one({}, {"$set": update}, upsert=True)
        log_admin_action(session["admin_id"], session["admin_username"], "Updated school settings (from About page)")
        flash("Pengaturan sekolah berhasil diperbarui.", "success")
        return redirect(url_for("admin_about"))

    # --- POST update Headmaster Message ---
    if request.method == "POST" and request.form.get("form_type") == "headmaster":
        headmaster_name = request.form.get("headmaster_name", "").strip()
        headmaster_message = request.form.get("headmaster_message", "").strip()
        headmaster_photo = request.files.get("headmaster_photo")

        update = {
            "headmaster_name": headmaster_name,
            "headmaster_message": headmaster_message
        }

        if headmaster_photo and headmaster_photo.filename and allowed_image(headmaster_photo.filename):
            ext = os.path.splitext(secure_filename(headmaster_photo.filename))[1]
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            fname = f"{ts}{ext}"
            headmaster_photo.save(os.path.join(app.config['UPLOAD_FOLDER_AVATAR'], fname))
            update["headmaster_photo"] = fname

        db.settings.update_one({}, {"$set": update}, upsert=True)
        log_admin_action(session["admin_id"], session["admin_username"], "Updated headmaster message")
        flash("Sambutan kepala sekolah berhasil diperbarui.", "success")
        return redirect(url_for("admin_about"))

    return render_template(
        "admin/about.html",
        active_page="admin_about",
        about=about_data,
        settings=settings
    )


# ---------------------------------------- #
# 12) ADMIN: MANAJEMEN EXTRACURRICULAR     #
# ---------------------------------------- #
@app.route("/admin_extracurricular", methods=["GET", "POST"])
def admin_extracurricular():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # Ambil parameter pencarian
    search_query = request.args.get("search", "").strip()

    # Filter berdasarkan pencarian
    query_filter = {
        "$or": [
            {"name": {"$regex": search_query, "$options": "i"}},
            {"description": {"$regex": search_query, "$options": "i"}}
        ]
    } if search_query else {}

    # Pagination
    page = int(request.args.get("page", 1))
    per_page = 5
    skip = (page - 1) * per_page
    total = db.extracurricular.count_documents(query_filter)
    extracurriculars = list(
        db.extracurricular.find(query_filter)
        .sort("name", 1)
        .skip(skip)
        .limit(per_page)
    )
    total_pages = ceil(total / per_page)

    return render_template(
        "admin/extracurricular.html",
        active_page="admin_extracurricular",
        extracurriculars=extracurriculars,
        page=page,
        total_pages=total_pages,
        search=search_query
    )


@app.route("/add_extracurricular", methods=["POST"])
def add_extracurricular():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_file = request.files.get("image")

    filename = ""
    if image_file and image_file.filename:
        if not allowed_image(image_file.filename):
            flash("Image type not allowed", "danger")
            return redirect(url_for("admin_extracurricular"))
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext = os.path.splitext(secure_filename(image_file.filename))
        filename = f"{timestamp}{ext}"
        image_path = os.path.join(app.config["UPLOAD_FOLDER_EXTRACURRICULAR"], filename)
        image_file.save(image_path)

    db.extracurricular.insert_one({
        "name": name,
        "description": description,
        "image": filename,
        "created_at": datetime.now(timezone.utc)
    })

    log_admin_action(session["admin_id"], session["admin_username"], f"Added extracurricular: {name}")
    flash("Extracurricular added successfully.", "success")
    return redirect(url_for("admin_extracurricular"))


@app.route("/edit_extracurricular/<id>", methods=["POST"])
def edit_extracurricular(id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_file = request.files.get("image")

    update_data = {
        "name": name,
        "description": description
    }

    if image_file and image_file.filename:
        if not allowed_image(image_file.filename):
            flash("Image type not allowed", "danger")
            return redirect(url_for("admin_extracurricular"))
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext = os.path.splitext(secure_filename(image_file.filename))
        filename = f"{timestamp}{ext}"
        image_path = os.path.join(app.config["UPLOAD_FOLDER_EXTRACURRICULAR"], filename)
        image_file.save(image_path)
        update_data["image"] = filename

    db.extracurricular.update_one({"_id": ObjectId(id)}, {"$set": update_data})

    log_admin_action(session["admin_id"], session["admin_username"], f"Updated extracurricular: {name}")
    flash("Extracurricular updated successfully.", "success")
    return redirect(url_for("admin_extracurricular"))


@app.route("/delete_extracurricular/<id>", methods=["POST"])
def delete_extracurricular(id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    item = db.extracurricular.find_one({"_id": ObjectId(id)})
    if item:
        db.extracurricular.delete_one({"_id": ObjectId(id)})
        log_admin_action(session["admin_id"], session["admin_username"], f"Deleted extracurricular: {item.get('name', 'Unknown')}")
        flash("Extracurricular deleted successfully.", "success")
    else:
        flash("Extracurricular not found.", "danger")
    return redirect(url_for("admin_extracurricular"))


# ---------------------------------------- #
# 13) ADMIN: LOG ADMIN                     #
# ---------------------------------------- #
@app.route("/admin_logs")
def admin_logs():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # —── jumlah baris yang ingin ditampilkan —──
    limit_param = request.args.get("limit", "25")   # default 25
    logs_all    = list(db.admin_logs.find().sort("timestamp", -1))

    if limit_param.lower() == "all":
        logs_page = logs_all
    else:
        try:
            limit = int(limit_param)
        except ValueError:
            limit = 25
        logs_page = logs_all[:limit]

    return render_template(
        "admin/log_admin.html",
        logs=logs_page,               
        limit_param=limit_param       
    )


# ---------------------------------------- #
# 14) ADMIN: SETTING                       #
# ---------------------------------------- #
# Upload folders (hanya untuk avatar admin)
app.config['UPLOAD_FOLDER_AVATAR'] = os.path.join(app.root_path, 'static', 'images', 'avatars')
os.makedirs(app.config['UPLOAD_FOLDER_AVATAR'], exist_ok=True)

ALLOWED_IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTS

@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    admin_record = db.admin.find_one({"_id": ObjectId(session["admin_id"])})
    settings     = db.settings.find_one({}) or {}

    if request.method == "POST":
        form = request.form.get("form_type")

        # ── PROFILE ─────────────────────
        if form == "profile":
            username     = request.form.get("username", "").strip()
            name         = request.form.get("name", "").strip()
            email        = request.form.get("email", "").strip()
            avatar_file  = request.files.get("avatar")

            update = {"username": username, "name": name, "email": email}
            if avatar_file and avatar_file.filename and allowed_image(avatar_file.filename):
                ext      = os.path.splitext(secure_filename(avatar_file.filename))[1]
                ts       = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                filename = f"{ts}{ext}"
                avatar_file.save(os.path.join(app.config['UPLOAD_FOLDER_AVATAR'], filename))
                update["avatar"] = filename

            db.admin.update_one({"_id": admin_record["_id"]}, {"$set": update})
            session["admin_username"] = username
            log_admin_action(
                session["admin_id"],
                session["admin_username"],
                "Updated own profile"
            )
            flash("Profile updated.", "success")

        # ── SECURITY & PASSWORD ─────────
        elif form == "security":
            current_pw = request.form.get("current_password", "")
            new_pw     = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")

            if not bcrypt.checkpw(current_pw.encode(), admin_record["password_hash"].encode()):
                flash("Current password is incorrect.", "danger")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "danger")
            else:
                new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
                db.admin.update_one(
                    {"_id": admin_record["_id"]},
                    {"$set": {"password_hash": new_hash}}
                )
                log_admin_action(
                    session["admin_id"],
                    session["admin_username"],
                    "Changed own password"
                )
                flash("Password changed successfully.", "success")

        return redirect(url_for("admin_settings"))

    # on GET, re-load records
    admin_record = db.admin.find_one({"_id": ObjectId(session["admin_id"])})
    settings     = db.settings.find_one({}) or {}
    return render_template(
        "admin/settings.html",
        admin=admin_record,
        settings=settings,
        active_page="settings"
    )


@app.context_processor
def inject_settings():
    settings = db.settings.find_one({}) or {}
    return {'settings': settings}


@app.context_processor
def inject_globals():
    settings = db.settings.find_one({}, {"_id": 0}) or {}
    contact  = db.contact.find_one({}, {"_id": 0})  or {}
    about    = db.about.find_one({},   {"_id": 0})  or {}
    return dict(settings=settings, contact=contact, about=about)


# ---------------------------------------- #
# 15) ADMIN: E-LEARNING ADMIN              #
# ---------------------------------------- #
# ─── Upload folders ──────────────────────
UPLOAD_FOLDER_MATERIALS = os.path.join(app.root_path, "static/images/materials")
UPLOAD_FOLDER_SUBJECTS  = os.path.join(app.root_path, "static/images/subjects")
UPLOAD_FOLDER_CLASSES   = os.path.join(app.root_path, "static/images/img_classes")

# ⇢ Buat folder jika belum ada
os.makedirs(UPLOAD_FOLDER_MATERIALS, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_SUBJECTS,  exist_ok=True)
os.makedirs(UPLOAD_FOLDER_CLASSES,   exist_ok=True)

# ⇢ Tambahkan ke konfigurasi Flask
app.config.update(
    UPLOAD_FOLDER_MATERIALS=UPLOAD_FOLDER_MATERIALS,
    UPLOAD_FOLDER_SUBJECTS=UPLOAD_FOLDER_SUBJECTS,
    UPLOAD_FOLDER_CLASSES=UPLOAD_FOLDER_CLASSES,
)

# ⇢ Ekstensi file yang diizinkan
ALLOWED_MATERIAL_EXT = {"pdf", "ppt", "pptx", "doc", "docx", "mp4"}
ALLOWED_IMAGE_EXT    = {"png", "jpg", "jpeg", "gif"}

# ⇢ Fungsi validasi ekstensi
def allowed_material(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_MATERIAL_EXT

def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXT


@app.route("/admin_materials")
def admin_materials():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # ────────────────────────────── query-string params ──────────────────────
    page         = int(request.args.get("page", 1))           # materials page
    class_page   = int(request.args.get("class_page", 1))     # classes  page
    subject_page = int(request.args.get("subject_page", 1))   # subjects page

    # keyword pencarian
    search_query   = request.args.get("search", "").strip()
    class_search   = request.args.get("class_search", "").strip()
    subject_search = request.args.get("subject_search", "").strip()

    # batas per-halaman
    per_page         = 5      # materials
    class_per_page   = 3      # classes
    subject_per_page = 3      # subjects

    # ────────────────────────────── CLASSES ──────────────────────────────────
    class_filter = {}
    if class_search:
        class_filter = {
            "$or": [
                {"title":       {"$regex": class_search, "$options": "i"}},
                {"description": {"$regex": class_search, "$options": "i"}}
            ]
        }

    classes_cursor  = db.classes.find(class_filter).sort("created_at", -1)
    classes_list    = [{**cls, "_id": str(cls["_id"])} for cls in classes_cursor]

    total_classes     = len(classes_list)
    class_total_pages = max(ceil(total_classes / class_per_page), 1)
    cls_start         = (class_page - 1) * class_per_page
    cls_end           = cls_start + class_per_page
    classes_display   = classes_list[cls_start:cls_end]

    # ────────────────────────────── SUBJECTS ─────────────────────────────────
    subject_filter = {}
    if subject_search:
        subject_filter = {
            "$or": [
                {"title":       {"$regex": subject_search, "$options": "i"}},
                {"description": {"$regex": subject_search, "$options": "i"}}
            ]
        }

    subjects_cursor = db.subjects.find(subject_filter).sort("created_at", -1)
    subjects_list   = []
    for subj in subjects_cursor:
        subj["_id"]     = str(subj["_id"])
        subj["class_id"] = str(subj.get("class_id", ""))
        subjects_list.append(subj)

    total_subjects      = len(subjects_list)
    subject_total_pages = max(ceil(total_subjects / subject_per_page), 1)
    sub_start           = (subject_page - 1) * subject_per_page
    sub_end             = sub_start + subject_per_page
    subjects_display    = subjects_list[sub_start:sub_end]

    # ────────────────────────────── lookup maps ──────────────────────────────
    class_map   = {c["_id"]: c for c in classes_list}
    subject_map = {s["_id"]: s for s in subjects_list}

    # ────────────────────────────── MATERIALS ────────────────────────────────
    material_filter = {}
    if search_query:
        material_filter = {
            "$or": [
                {"title":       {"$regex": search_query, "$options": "i"}},
                {"description": {"$regex": search_query, "$options": "i"}}
            ]
        }

    skip = (page - 1) * per_page
    total_materials = db.materials.count_documents(material_filter)
    total_pages     = max(ceil(total_materials / per_page), 1)

    materials_cursor = (db.materials.find(material_filter)
                                    .sort("created_at", -1)
                                    .skip(skip)
                                    .limit(per_page))

    materials_list = []
    for mat in materials_cursor:
        mat["_id"]       = str(mat["_id"])
        subj_id          = str(mat.get("subject_id", ""))
        cls_id           = str(mat.get("class_id", ""))
        mat["subject"]   = subject_map.get(subj_id, {}).get("title", "-")
        mat["class_name"] = class_map.get(cls_id, {}).get("title", "-")
        materials_list.append(mat)

    # ────────────────────────────── render page ──────────────────────────────
    return render_template(
        "admin/materials.html",
        active_page="admin_materials",

        # dropdown & JS helper → list lengkap
        classes=classes_list,
        subjects=subjects_list,

        # tabel (paginated)
        classes_display=classes_display,
        subjects_display=subjects_display,
        materials=materials_list,

        # pagination numbers
        page=page,                       total_pages=total_pages,
        class_page=class_page,           class_total_pages=class_total_pages,
        subject_page=subject_page,       subject_total_pages=subject_total_pages,
        class_per_page=class_per_page,   subject_per_page=subject_per_page,

        # kirim kembali kata kunci pencarian supaya <input> tetap terisi
        search_query=search_query,
        class_search=class_search,
        subject_search=subject_search
    )


# ─── CLASS CRUD ─────────────────────────
@app.route("/add_class_materials", methods=["POST"])
def add_class_materials():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    title       = request.form["title"].strip()
    description = request.form.get("description", "").strip()
    img         = request.files.get("image")
    img_name    = ""

    if img and img.filename:
        if not allowed_image(img.filename):
            flash("Image type not allowed", "danger")
            return redirect(url_for("admin_materials"))
        # ⇢ rename with date-time
        timestamp  = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext     = os.path.splitext(secure_filename(img.filename))
        img_name   = f"{timestamp}{ext}"
        img.save(join(app.config["UPLOAD_FOLDER_CLASSES"], img_name))

    cls_id = db.classes.insert_one({
        "title": title,
        "description": description,
        "image": img_name,
        "created_at": datetime.now(timezone.utc),
    }).inserted_id

    log_admin_action(session["admin_id"], session["admin_username"], f"Added class {cls_id}")
    flash("Class added", "success")
    return redirect(url_for("admin_materials"))


@app.route("/edit_class_materials/<class_id>", methods=["POST"])
def edit_class_materials(class_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    cls = db.classes.find_one({"_id": ObjectId(class_id)})
    if not cls:
        flash("Class not found", "danger")
        return redirect(url_for("admin_materials"))

    title       = request.form["title"].strip()
    description = request.form.get("description", "").strip()
    img         = request.files.get("image")

    update = {
        "title": title,
        "description": description,
        "updated_at": datetime.now(timezone.utc)
    }

    if img and img.filename:
        if not allowed_image(img.filename):
            flash("Image type not allowed", "danger")
            return redirect(url_for("admin_materials"))
        # hapus gambar lama (jika ada)
        if cls.get("image"):
            old = join(app.config["UPLOAD_FOLDER_CLASSES"], cls["image"])
            if os.path.exists(old):
                os.remove(old)
        # rename baru
        timestamp  = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext     = os.path.splitext(secure_filename(img.filename))
        img_name   = f"{timestamp}{ext}"
        img.save(join(app.config["UPLOAD_FOLDER_CLASSES"], img_name))
        update["image"] = img_name

    db.classes.update_one({"_id": cls["_id"]}, {"$set": update})
    log_admin_action(session["admin_id"], session["admin_username"], f"Edited class {class_id}")
    flash("Class updated", "success")
    return redirect(url_for("admin_materials"))


@app.route("/delete_class_materials/<class_id>", methods=["POST"])
def delete_class_materials(class_id):
    if "admin_id" not in session: return redirect(url_for("login"))
    cls=db.classes.find_one({'_id':ObjectId(class_id)})
    if not cls: flash("Class not found","danger"); return redirect(url_for('admin_materials'))
    if cls.get('image'):
        p=join(app.config['UPLOAD_FOLDER_CLASSES'],cls['image']);
        if os.path.exists(p): os.remove(p)
    db.classes.delete_one({'_id':cls['_id']})
    log_admin_action(session['admin_id'], session['admin_username'], f"Deleted class {class_id}")
    flash("Class deleted","success")
    return redirect(url_for('admin_materials'))


# ─── SUBJECT CRUD ───────────────────────
@app.route("/add_subject_materials", methods=["POST"])
def add_subject_materials():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    title       = request.form["title"].strip()
    description = request.form.get("description", "").strip()
    class_id    = request.form.get("class_id")
    img         = request.files.get("image")
    img_name    = ""

    if img and img.filename:
        if not allowed_image(img.filename):
            flash("Image type not allowed", "danger")
            return redirect(url_for("admin_materials"))
        timestamp  = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext     = os.path.splitext(secure_filename(img.filename))
        img_name   = f"{timestamp}{ext}"
        img.save(join(app.config["UPLOAD_FOLDER_SUBJECTS"], img_name))

    subj_id = db.subjects.insert_one({
        "class_id": ObjectId(class_id),
        "title": title,
        "description": description,
        "image": img_name,
        "created_at": datetime.now(timezone.utc)
    }).inserted_id

    log_admin_action(session["admin_id"], session["admin_username"], f"Added subject {subj_id}")
    flash("Subject added", "success")
    return redirect(url_for("admin_materials"))


@app.route("/edit_subject_materials/<subject_id>", methods=["POST"])
def edit_subject_materials(subject_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    subj = db.subjects.find_one({"_id": ObjectId(subject_id)})
    if not subj:
        flash("Subject not found", "danger")
        return redirect(url_for("admin_materials"))

    title       = request.form["title"].strip()
    description = request.form.get("description", "").strip()
    class_id    = request.form.get("class_id")
    img         = request.files.get("image")

    update = {
        "title": title,
        "description": description,
        "class_id": ObjectId(class_id),
        "updated_at": datetime.now(timezone.utc)
    }

    if img and img.filename:
        if not allowed_image(img.filename):
            flash("Image type not allowed", "danger")
            return redirect(url_for("admin_materials"))
        if subj.get("image"):
            old = join(app.config["UPLOAD_FOLDER_SUBJECTS"], subj["image"])
            if os.path.exists(old):
                os.remove(old)
        timestamp  = datetime.now().strftime("%Y%m%d%H%M%S")
        _, ext     = os.path.splitext(secure_filename(img.filename))
        img_name   = f"{timestamp}{ext}"
        img.save(join(app.config["UPLOAD_FOLDER_SUBJECTS"], img_name))
        update["image"] = img_name

    db.subjects.update_one({"_id": subj["_id"]}, {"$set": update})
    log_admin_action(session["admin_id"], session["admin_username"], f"Edited subject {subject_id}")
    flash("Subject updated", "success")
    return redirect(url_for("admin_materials"))


@app.route("/delete_subject_materials/<subject_id>", methods=["POST"])
def delete_subject_materials(subject_id):
    if "admin_id" not in session: return redirect(url_for("login"))
    subj=db.subjects.find_one({'_id':ObjectId(subject_id)})
    if not subj: flash("Subject not found","danger"); return redirect(url_for('admin_materials'))
    if subj.get('image'):
        p=join(app.config['UPLOAD_FOLDER_SUBJECTS'],subj['image']);
        if os.path.exists(p): os.remove(p)
    db.subjects.delete_one({'_id':subj['_id']})
    log_admin_action(session['admin_id'], session['admin_username'], f"Deleted subject {subject_id}")
    flash("Subject deleted","success")
    return redirect(url_for('admin_materials'))


# ─── MATERIAL CRUD ───────────────────────
@app.route("/add_material", methods=["POST"])
def add_material():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    title       = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    subject_id  = request.form.get('subject_id')
    class_id    = request.form.get('class_id')
    video_link  = request.form.get('video_link', '').strip()

    # ambil list file
    files = request.files.getlist('files')
    filenames = []

    for f in files:
        if f and f.filename:
            if not allowed_material(f.filename):
                flash("One or more file types not allowed.", "danger")
                return redirect(url_for("admin_materials"))
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            _, ext = os.path.splitext(secure_filename(f.filename))
            new_fn = f"{ts}{ext}"              # <-- only timestamp + extension
            f.save(os.path.join(app.config['UPLOAD_FOLDER_MATERIALS'], new_fn))
            filenames.append(new_fn)

    mat_doc = {
        'subject_id': ObjectId(subject_id),
        'class_id'  : ObjectId(class_id),
        'title'      : title,
        'description': description,
        'filenames'  : filenames,
        'video_link' : video_link,
        'created_at' : datetime.now(timezone.utc)
    }
    mat_id = db.materials.insert_one(mat_doc).inserted_id

    log_admin_action(session['admin_id'], session['admin_username'], f"Added material {mat_id}")
    flash("Material added successfully.", "success")
    return redirect(url_for('admin_materials'))


@app.route("/edit_material/<material_id>", methods=["POST"])
def edit_material(material_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    mat = db.materials.find_one({'_id': ObjectId(material_id)})
    if not mat:
        flash("Material not found.", "danger")
        return redirect(url_for('admin_materials'))

    title       = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    subject_id  = request.form.get('subject_id')
    class_id    = request.form.get('class_id')
    video_link  = request.form.get('video_link', '').strip()

    update = {
        'title'      : title,
        'description': description,
        'subject_id' : ObjectId(subject_id),
        'class_id'   : ObjectId(class_id),
        'video_link' : video_link,
        'updated_at' : datetime.now(timezone.utc)
    }

    # jika ada upload baru, replace semua file lama
    new_files = request.files.getlist('files')
    if any(f.filename for f in new_files):
        # hapus file lama
        for old_fn in mat.get('filenames', []):
            old_path = os.path.join(app.config['UPLOAD_FOLDER_MATERIALS'], old_fn)
            if os.path.exists(old_path):
                os.remove(old_path)
        # simpan file baru
        filenames = []
        for f in new_files:
            if f and f.filename:
                if not allowed_material(f.filename):
                    flash("One or more file types not allowed.", "danger")
                    return redirect(url_for("admin_materials"))
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                _, ext = os.path.splitext(secure_filename(f.filename))
                new_fn = f"{ts}{ext}"         # <-- only timestamp + extension
                f.save(os.path.join(app.config['UPLOAD_FOLDER_MATERIALS'], new_fn))
                filenames.append(new_fn)
        update['filenames'] = filenames

    db.materials.update_one({'_id': mat['_id']}, {'$set': update})
    log_admin_action(session['admin_id'], session['admin_username'], f"Edited material {material_id}")
    flash("Material updated.", "success")
    return redirect(url_for('admin_materials'))


@app.route("/delete_material/<material_id>", methods=["POST"])
def delete_material(material_id):
    if "admin_id" not in session: return redirect(url_for("login"))
    mat=db.materials.find_one({'_id':ObjectId(material_id)})
    if not mat: flash("Material not found.","danger"); return redirect(url_for('admin_materials'))
    if mat.get('filename'):
        p=join(app.config['UPLOAD_FOLDER_MATERIALS'],mat['filename']);
        if os.path.exists(p): os.remove(p)
    db.materials.delete_one({'_id':mat['_id']})
    log_admin_action(session['admin_id'], session['admin_username'], f"Deleted material {material_id}")
    flash("Material deleted.","success")
    return redirect(url_for('admin_materials'))


# ---------------------------------------- #
# 15) ADMIN: SETTING ADMIN               #
# ---------------------------------------- #
# Folder avatar jika diperlukan
UPLOAD_FOLDER_AVATAR = os.path.join(app.root_path, "static", "images", "avatars")
os.makedirs(UPLOAD_FOLDER_AVATAR, exist_ok=True)
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif"}

def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTS


@app.route("/admin/admins")
@superadmin_required
def admin_list():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    # ── parameter halaman dan search ─────────────────────────
    page    = int(request.args.get("page", 1))
    search  = request.args.get("search", "").strip().lower()
    per_page = 5
    start   = (page - 1) * per_page
    end     = start + per_page

    # Ambil dan filter admin
    admins_all = list(db.admin.find().sort("username", 1))
    if search:
        admins_all = [
            a for a in admins_all if
            search in a.get("username", "").lower() or
            search in a.get("name", "").lower() or
            search in a.get("email", "").lower()
        ]

    total_pages = ceil(len(admins_all) / per_page) or 1
    admins_page = admins_all[start:end]

    return render_template(
        "admin/admin.html",
        admins=admins_all,
        admins_page=admins_page,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search=search,
        active_page="admins"
    )


@app.route("/add_admin", methods=["POST"])
def add_admin():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    username = request.form.get("username").strip()
    name     = request.form.get("name").strip()
    email    = request.form.get("email").strip()
    password = request.form.get("password").strip()
    role     = request.form.get("role")
    avatar   = request.files.get("avatar")

    avatar_filename = "default_admin.png"
    if avatar and avatar.filename and allowed_image(avatar.filename):
        ext = os.path.splitext(secure_filename(avatar.filename))[1]
        fname = datetime.utcnow().strftime("%Y%m%d%H%M%S") + ext
        avatar.save(os.path.join(UPLOAD_FOLDER_AVATAR, fname))
        avatar_filename = fname

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    db.admin.insert_one({
        "username": username,
        "name": name,
        "email": email,
        "password_hash": hashed,
        "role": role,
        "avatar": avatar_filename,
        "is_blocked": False,
        "created_at": datetime.utcnow(),
    })

    log_admin_action(session["admin_id"], session["admin_username"], f"Added admin: {username}")
    return redirect(url_for("admin_list"))


@app.route("/delete_admin/<admin_id>", methods=["POST"])
def delete_admin(admin_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    admin = db.admin.find_one({"_id": ObjectId(admin_id)})
    if admin:
        db.admin.delete_one({"_id": ObjectId(admin_id)})
        log_admin_action(session["admin_id"], session["admin_username"], f"Deleted admin: {admin['username']}")

    return redirect(url_for("admin_list"))


@app.route("/block_admin/<admin_id>", methods=["POST"])
def block_admin(admin_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    admin = db.admin.find_one({"_id": ObjectId(admin_id)})
    if admin:
        new_status = not admin.get("is_blocked", False)
        db.admin.update_one({"_id": ObjectId(admin_id)}, {"$set": {"is_blocked": new_status}})
        status_txt = "Blocked" if new_status else "Unblocked"
        log_admin_action(session["admin_id"], session["admin_username"], f"{status_txt} admin: {admin['username']}")

    return redirect(url_for("admin_list"))


@app.route("/edit_admin/<admin_id>", methods=["POST"])
def edit_admin(admin_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    name   = request.form.get("name").strip()
    email  = request.form.get("email").strip()
    role   = request.form.get("role")

    db.admin.update_one(
        {"_id": ObjectId(admin_id)},
        {"$set": {"name": name, "email": email, "role": role}}
    )

    log_admin_action(session["admin_id"], session["admin_username"], f"Edited admin: {admin_id}")
    return redirect(url_for("admin_list"))


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, debug=True)