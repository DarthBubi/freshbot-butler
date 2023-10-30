from bson.objectid import ObjectId
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for
from pymongo import MongoClient

app = Flask(__name__)
client = MongoClient('mongodb://localhost:27017/')
db = client['pantry']
collection = db['items']

def get_expired_items():
    items = collection.find()
    expired_items = []
    expiring_items = []
    for item in items:
        expiration_date = datetime.strptime(item['expiration'], '%Y-%m-%d')
        if expiration_date < datetime.now():
            expired_items.append(item)
        elif expiration_date <= datetime.now() + timedelta(days=3):
            expiring_items.append(item)
    return expired_items, expiring_items

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/pantry', methods=['GET', 'POST'])
def get_items():
    if request.method == 'POST':
        item_id = request.form['item_id']
        return redirect(url_for('delete_item', item_id=item_id))
    
    items = collection.find()
    expired_items, expiring_items = get_expired_items()
    warning = 'Some items are expired!' if expired_items else None
    expiring_warning = 'Some items are about to expire!' if expiring_items else None
    return render_template('pantry.html', items=items, expired_items=expired_items, expiring_items=expiring_items, warning=warning, expiring_warning=expiring_warning)

@app.route('/add_item', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        item = request.form.to_dict()
        collection.insert_one(item)
        return redirect(url_for('get_items'))

    return render_template('add_item.html')

@app.route('/delete_item/<item_id>', methods=['POST'])
def delete_item(item_id):
    collection.delete_one({'_id': ObjectId(item_id)})
    return redirect(url_for('get_items'))

if __name__ == '__main__':
    app.run(debug=True)