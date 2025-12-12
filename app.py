from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
from datetime import datetime
import qrcode
import io
import base64

app = Flask(__name__)
DB = "billing.db"

# Database Create if Not Exists
def init_db():
    if not os.path.exists(DB):
        conn = sqlite3.connect(DB)
        conn.execute("CREATE TABLE customer(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, email TEXT)")
        conn.execute("CREATE TABLE product(id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL, stock INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE bill(id INTEGER PRIMARY KEY, customer_id INTEGER, date TEXT, total REAL, payment_method TEXT, payment_status TEXT DEFAULT 'Pending')")
        conn.execute("CREATE TABLE bill_items(id INTEGER PRIMARY KEY, bill_id INTEGER, product_id INTEGER, quantity INTEGER, price REAL)")
        conn.close()
    else:
        # Update schema if needed
        conn = sqlite3.connect(DB)
        try:
            conn.execute("ALTER TABLE customer ADD COLUMN phone TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE customer ADD COLUMN email TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE bill ADD COLUMN payment_method TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE bill ADD COLUMN payment_status TEXT DEFAULT 'Pending'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE product ADD COLUMN stock INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.close()

# Database Connect
def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# Home
@app.route('/')
def index():
    return render_template('index.html')

# Add Customer
@app.route('/add_customer', methods=['GET','POST'])
def add_customer():
    if request.method == "POST":
        name = request.form['name']
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        conn = get_conn()
        conn.execute("INSERT INTO customer(name, phone, email) VALUES (?, ?, ?)", (name, phone, email))
        conn.commit()
        conn.close()
        return redirect('/')
    return render_template('add_customer.html')

# Add Product
@app.route('/add_product', methods=['GET','POST'])
def add_product():
    if request.method == "POST":
        name = request.form['name']
        price = float(request.form['price'])
        stock = int(request.form.get('stock', 0))
        conn = get_conn()
        conn.execute("INSERT INTO product(name, price, stock) VALUES (?, ?, ?)", (name, price, stock))
        conn.commit()
        conn.close()
        return redirect('/')
    return render_template('add_product.html')

# Generate Bill
@app.route('/generate_bill', methods=['GET','POST'])
def generate_bill():
    conn = get_conn()
    customers = conn.execute("SELECT * FROM customer").fetchall()
    products = conn.execute("SELECT * FROM product").fetchall()

    if request.method == "POST":
        customer_id = request.form['customer']
        total = 0
        items = []

        for i in range(1, 6):
            product_id = request.form.get(f'product{i}')
            quantity_str = request.form.get(f'quantity{i}')
            if product_id and quantity_str:
                quantity = int(quantity_str)
                product = conn.execute("SELECT price, stock FROM product WHERE id=?", (product_id,)).fetchone()
                if product and product['stock'] >= quantity:
                    price = product['price']
                    total += price * quantity
                    items.append((product_id, quantity, price))

        if items:
            conn.execute("INSERT INTO bill(customer_id, date, total) VALUES (?, ?, ?)",
                         (customer_id, datetime.now(), total))
            bill_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for product_id, quantity, price in items:
                conn.execute("INSERT INTO bill_items(bill_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                             (bill_id, product_id, quantity, price))
            conn.commit()
            conn.close()
            return redirect(url_for('payment', bill_id=bill_id))
        else:
            conn.close()
            return "Insufficient stock for selected products", 400
    
    return render_template('generate_bill.html', customers=customers, products=products)

# View Bills
@app.route('/view_bills')
def view_bills():
    conn = get_conn()
    bills = conn.execute("""
        SELECT bill.id, customer.name, bill.date, bill.total
        FROM bill JOIN customer ON bill.customer_id = customer.id
    """).fetchall()
    conn.close()
    return render_template('view_bills.html', bills=bills)

# Dashboard
@app.route('/dashboard')
def dashboard():
    conn = get_conn()
    num_customers = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
    num_products = conn.execute("SELECT COUNT(*) FROM product").fetchone()[0]
    num_bills = conn.execute("SELECT COUNT(*) FROM bill").fetchone()[0]
    total_revenue = conn.execute("SELECT SUM(total) FROM bill").fetchone()[0] or 0
    conn.close()
    return render_template('dashboard.html', num_customers=num_customers, num_products=num_products, num_bills=num_bills, total_revenue=total_revenue)

# Payment
@app.route('/payment/<int:bill_id>', methods=['GET', 'POST'])
def payment(bill_id):
    conn = get_conn()
    bill = conn.execute("SELECT * FROM bill WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        conn.close()
        return "Bill not found", 404

    if request.method == 'POST':
        payment_method = request.form['payment_method']
        if payment_method == 'cash':
            conn.execute("UPDATE bill SET payment_method = 'Cash', payment_status = 'Paid' WHERE id = ?", (bill_id,))
        elif payment_method == 'upi':
            # For UPI, assume it's paid after showing QR
            conn.execute("UPDATE bill SET payment_method = 'UPI', payment_status = 'Paid' WHERE id = ?", (bill_id,))
        elif payment_method == 'card':
            # Dummy card processing
            card_number = request.form['card_number']
            expiry = request.form['expiry']
            cvv = request.form['cvv']
            # In real app, process card
            conn.execute("UPDATE bill SET payment_method = 'Card', payment_status = 'Paid' WHERE id = ?", (bill_id,))

        # Reduce stock for each item in the bill
        items = conn.execute("SELECT product_id, quantity FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
        for item in items:
            conn.execute("UPDATE product SET stock = stock - ? WHERE id = ?", (item['quantity'], item['product_id']))

        conn.commit()
        conn.close()
        return redirect(url_for('view_bill_details', bill_id=bill_id))

    # Generate QR for UPI
    upi_id = "merchant@upi"  # Dummy UPI ID
    amount = bill['total']
    qr_data = f"upi://pay?pa={upi_id}&pn=Merchant&am={amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_code = base64.b64encode(buffer.getvalue()).decode('utf-8')

    conn.close()
    return render_template('payment.html', bill=bill, qr_code=qr_code)

# View Bill Details
@app.route('/view_bill_details/<int:bill_id>')
def view_bill_details(bill_id):
    conn = get_conn()
    bill = conn.execute("""
        SELECT bill.id, customer.name, bill.date, bill.total, bill.payment_method, bill.payment_status
        FROM bill JOIN customer ON bill.customer_id = customer.id
        WHERE bill.id = ?
    """, (bill_id,)).fetchone()
    if not bill:
        conn.close()
        return "Bill not found", 404
    items = conn.execute("""
        SELECT product.name, bill_items.quantity, bill_items.price
        FROM bill_items JOIN product ON bill_items.product_id = product.id
        WHERE bill_items.bill_id = ?
    """, (bill_id,)).fetchall()
    conn.close()
    return render_template('view_bill_details.html', bill=bill, items=items)

# Stock Alerts
@app.route('/stock_alerts')
def stock_alerts():
    conn = get_conn()
    low_stock_products = conn.execute("SELECT * FROM product WHERE stock < 10").fetchall()
    conn.close()
    return render_template('stock_alerts.html', products=low_stock_products)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
