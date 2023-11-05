import asyncio

from bson.objectid import ObjectId
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template, redirect, url_for
from pymongo import MongoClient

from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import MongodbLoader
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.prompts import PromptTemplate
from langchain.vectorstores import Chroma

from dotenv import load_dotenv

load_dotenv()

__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

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

def generate_summary(items):
    names = [item['name'] for item in items]
    quantities = [item['quantity'] for item in items]
    total_quantity = sum(quantities)
    summary = f"The items in the collection are: {', '.join(names)}. The total quantity is {total_quantity}."
    return summary

async def get_response(query: str):
    mongo_loader = MongodbLoader('mongodb://localhost:27017/', 'pantry', 'items')
    docs = await mongo_loader.aload()
    embeddings = OpenAIEmbeddings()
    docsearch = Chroma.from_documents(docs, embeddings)

    qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(model_name="gpt-4", temperature=0.2), 
                                    chain_type="stuff",
                                    retriever=docsearch.as_retriever(),
                                    return_source_documents=True)

    prompt_template = PromptTemplate.from_template("{query} Heute ist der {date}, falls das Ablaufdatum vor dem heutigen Tag liegt, ist das Objekt nicht mehr haltbar. Das Datumsformat ist TT.MM.JJJJ.")

    date = datetime.now().strftime('%d.%m.%Y')

    query = prompt_template.format(date=date, query=query)
    response = qa(query)
    return response

@app.route('/langchain', methods=['GET', 'POST'])
def langchain_query():
    if request.method == 'POST':
        data = request.get_json()
        query = data['query']
        items = list(collection.find())

        if query == 'summary':
            summary = generate_summary(items)
            response = f"There are {len(items)} items in the collection. {summary}"
        else:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(get_response(query))
            response = res["result"]
        return jsonify({'response': response})
    else:
        return render_template('langchain.html')

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
