from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from flask_pymongo import PyMongo
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'
bcrypt = Bcrypt(app)

# MongoDB Connection
client = MongoClient("mongodb://localhost:27017/")
db = client["library_db"]
users_collection = db["users"]
books_collection = db["books"]
borrowed_books_collection = db["borrowed_books"]
reviews_collection = db["reviews"]

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        is_admin = username == "admin"
        
        if users_collection.find_one({"username": username}):
            flash("Username already exists!", "danger")
            return redirect(url_for('signup'))
        
        users_collection.insert_one({"username": username, "password": password, "is_admin": is_admin})
        flash("Signup successful! Please login.", "success")
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users_collection.find_one({"username": username})
        
        if user and bcrypt.check_password_hash(user['password'], password):
            session['user'] = username
            session['is_admin'] = user.get("is_admin", False)
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))
        
        flash("Invalid username or password", "danger")
    return render_template('login.html')

@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Fetch all books from MongoDB
    books = list(books_collection.find())

    # Ensure every book has a count field (if missing, set to 0)
    for book in books:
        book["count"] = book.get("count", 0)

    # Handle search query
    search_by = request.args.get('search_by', '')
    query = request.args.get('query', '').strip()

    if query:  # If a search query is entered
        search_filter = {search_by: {"$regex": query, "$options": "i"}}  # Case-insensitive search
        books = list(books_collection.find(search_filter))

    # Get borrowed books (admin sees all, users see their own)
    is_admin = session.get('is_admin', False)
    if is_admin:
        borrowed_books = list(borrowed_books_collection.find())  # Admin sees all borrowed books
    else:
        borrowed_books = list(borrowed_books_collection.find({"borrowed_by": session['user']}))  # User sees their own

    # Fix: Correctly calculate available and borrowed books
    total_available_books = sum(book.get("count", 0) for book in books)
    total_borrowed_books = borrowed_books_collection.count_documents({})  # Count borrowed books

    # Debugging logs (Check Flask console)
    print(f"✅ Search Query: {query} by {search_by}")
    print(f"✅ Total Available Books: {total_available_books}")
    print(f"✅ Total Borrowed Books: {total_borrowed_books}")

    return render_template('dashboard.html', 
                           books=books, 
                           borrowed_books=borrowed_books,
                           total_available_books=total_available_books, 
                           total_borrowed_books=total_borrowed_books,
                           username=session['user'], 
                           is_admin=is_admin)
@app.route('/leave_review', methods=['GET', 'POST'])
def leave_review():
    if request.method == 'POST':
        # Collect the form data
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']

        # Insert the review into the MongoDB collection
        reviews_collection = db["reviews"]
        reviews_collection.insert_one({"name": name, "email": email, "message": message})

        flash("Review submitted successfully!", "success")
        return redirect(url_for('home'))  # Redirect back to the home page after submission

    return render_template('review.html')  # Show the review form when GET request
@app.route('/admin/reviews', methods=['GET'])
def view_reviews():
    if 'user' not in session or not session.get('is_admin', False):
        return redirect(url_for('home'))  # Only allow admin to view reviews

    # Fetch all reviews from the MongoDB collection
    reviews_collection = db["reviews"]
    reviews = list(reviews_collection.find())  # Get all reviews from the database
    
    return render_template('admin_reviews.html', reviews=reviews)  # Pass the reviews to the template


@app.route('/search_books')
def search_books():
    query = request.args.get('query', '').strip()
    
    if not query:
        return jsonify([])  # Return empty list if no query

    search_filter = {
        "$or": [
            {"title": {"$regex": query, "$options": "i"}},
            {"author": {"$regex": query, "$options": "i"}},
            {"category": {"$regex": query, "$options": "i"}}
        ]
    }

    books = list(books_collection.find(search_filter, {"_id": 0}))  # Exclude _id from JSON
    return jsonify(books)

@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    if 'user' not in session or not session.get('is_admin', False):
        return redirect(url_for('dashboard'))  # Only admins can access

    if request.method == 'POST':
        title = request.form.get('title')
        author = request.form.get('author')
        isbn = request.form.get('isbn')
        category = request.form.get('category')
        count = int(request.form.get('count', 1))

        # Insert into the database
        books_collection.insert_one({
            "title": title,
            "author": author,
            "isbn": isbn,
            "category": category,
            "count": count
        })

        return redirect(url_for('dashboard'))  # Redirect after adding

    return render_template('add_book.html')  # Show add book form



@app.route('/delete_book/<string:isbn>')
def delete_book(isbn):
    if 'user' not in session or not session.get('is_admin', False):
        flash("You must be an admin to delete books.", "danger")
        return redirect(url_for('home'))
    
    books_collection.delete_one({"isbn": isbn})
    flash("Book deleted successfully!", "success")
    return redirect(url_for('dashboard'))

@app.route('/borrow/<isbn>', methods=['GET'])
def borrow_book(isbn):
    if 'user' not in session:
        flash("You need to log in to borrow a book.", "danger")
        return redirect(url_for('login'))

    book = books_collection.find_one({"isbn": isbn})  # Query MongoDB for the book

    if not book:
        flash("Book not found!", "danger")
        return redirect(url_for('dashboard'))

    if book["count"] <= 1:  # Prevent borrowing if only 1 copy is left
        flash("This book cannot be borrowed as only one copy remains in the library.", "warning")
        return redirect(url_for('dashboard'))

    # Reduce book count by 1
    books_collection.update_one({"isbn": isbn}, {"$inc": {"count": -1}})

    # Add record to borrowed_books_collection
    borrowed_books_collection.insert_one({
        "isbn": isbn,
        "title": book["title"],
        "borrowed_by": session['user'],
        "borrowed_at": datetime.now()
    })

    flash("Book borrowed successfully!", "success")
    return redirect(url_for('dashboard'))





@app.route('/return/<string:isbn>')
def return_book(isbn):
    if 'user' not in session:
        return redirect(url_for('login'))
    
    book = borrowed_books_collection.find_one({"isbn": isbn, "borrowed_by": session['user']})
    if book:
        books_collection.update_one({"isbn": isbn}, {"$inc": {"count": 1}})
        borrowed_books_collection.delete_one({"isbn": isbn, "borrowed_by": session['user']})
        flash("Book returned successfully!", "success")
    else:
        flash("You cannot return this book!", "danger")
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('is_admin', None)
    flash("Logged out successfully!", "info")
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
