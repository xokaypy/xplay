import os
import time
import uuid
import sqlite3
import random
import threading
import json
from flask import Flask, render_template_string, request, session
from flask_socketio import SocketIO, emit, join_room
from playwright.sync_api import sync_playwright

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key_pratik_secure_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

DB_FILE = 'raid_console_data.db'

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_raids (
            user_key TEXT PRIMARY KEY,
            session_id TEXT,
            thread_id TEXT,
            message TEXT,
            delay_val INTEGER DEFAULT 15,
            is_active INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            username TEXT DEFAULT 'NOT LOGGED IN'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS console_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT,
            log_message TEXT,
            log_type TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def save_log(user_key, message, log_type):
    timestamp = time.strftime('%H:%M:%S')
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO console_logs (user_key, log_message, log_type, timestamp) VALUES (?, ?, ?, ?)',
        (user_key, message, log_type, timestamp)
    )
    conn.commit()
    conn.close()

# Memory registry to track active authentication browser contexts across SocketIO cycles
active_browsers = {}

# --- HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PRATIK - SPAM PANEL</title>
    <script src="https://socket.io"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Consolas', monospace; }
        body { background-color: #0a0a0a; color: #0f0; min-height: 100vh; padding: 20px; overflow-x: hidden; }
        
        .header {
            position: relative; text-align: center; margin-bottom: 15px; padding: 20px 70px;
            background: linear-gradient(90deg, #ff0000, #ff7300, #fffb00, #48ff00, #00ffd5, #002bff, #7a00ff, #ff00c8, #ff0000);
            background-size: 400% 400%; animation: gradient 15s ease infinite; border-radius: 10px;
            box-shadow: 0 0 30px rgba(255, 0, 0, 0.5);
        }
        @keyframes gradient { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
        
        .icon-btn {
            position: absolute; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.6);
            color: #00ff00; border: 2px solid #00ff00; border-radius: 8px; width: 50px; height: 50px;
            font-size: 1.8rem; cursor: pointer; display: flex; align-items: center; justify-content: center;
            transition: all 0.3s ease; z-index: 10;
        }
        .icon-btn:hover { background: #00ff00; color: #000; box-shadow: 0 0 15px #00ff00; }
        .btn-menu { left: 15px; }
        .btn-add { right: 15px; }

        .tabs-bar { display: flex; gap: 10px; margin-bottom: 20px; overflow-x: auto; padding-bottom: 5px; }
        .tab-item {
            background: #111; color: #888; border: 1px solid #333; padding: 8px 16px; border-radius: 5px;
            cursor: pointer; white-space: nowrap; display: flex; align-items: center; gap: 10px;
        }
        .tab-item.active { color: #00ff00; border-color: #00ff00; background: #1e1e1e; box-shadow: 0 0 10px rgba(0, 255, 0, 0.2); }
        .tab-item .close-tab { color: #ff0000; font-weight: bold; margin-left: 5px; }

        .glowing-text { font-size: 3.5rem; font-weight: 900; color: white; text-shadow: 0 0 10px #ff0000, 0 0 20px #ff0000; letter-spacing: 2px; }

        .drawer {
            position: fixed; top: 0; left: -320px; width: 300px; height: 100%; background-color: #111;
            border-right: 2px solid #00ff00; box-shadow: 5px 0 25px rgba(0, 255, 0, 0.3); transition: left 0.3s ease; z-index: 100; padding: 20px;
        }
        .drawer.open { left: 0; }
        .drawer-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }
        .drawer-close { background: none; border: none; color: #ff0000; font-size: 1.5rem; cursor: pointer; }
        .pages-list { list-style: none; max-height: calc(100vh - 120px); overflow-y: auto; }
        .pages-list li { background: #222; margin-bottom: 10px; padding: 12px; border-radius: 5px; border: 1px solid #444; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
        .pages-list li:hover { border-color: #00ff00; }

        .container { display: flex; gap: 20px; max-width: 1800px; margin: 0 auto; }
        .left-panel { flex: 1; background-color: #111; border-radius: 10px; padding: 25px; border: 2px solid #ff0000; box-shadow: 0 0 20px rgba(255, 0, 0, 0.3); }
        .right-panel { flex: 2; background-color: #111; border-radius: 10px; padding: 25px; border: 2px solid #00ff00; box-shadow: 0 0 20px rgba(0, 255, 0, 0.3); min-height: 600px; }
        .panel-title { color: #ff0000; font-size: 1.8rem; margin-bottom: 20px; text-align: center; border-bottom: 2px solid #ff0000; text-shadow: 0 0 10px rgba(255, 0, 0, 0.5); }
        .panel-title.green { color: #00ff00; border-bottom-color: #00ff00; text-shadow: 0 0 10px rgba(0, 255, 0, 0.5); }
        
        .form-group { background-color: #222; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .input-group { margin-bottom: 15px; }
        .input-group label { display: block; color: #00ff00; margin-bottom: 8px; font-weight: bold; }
        .input-group input, .input-group textarea { width: 100%; padding: 12px; background: #000; border: 1px solid #444; color: #0f0; border-radius: 5px; outline: none; }
        .input-group input:focus, .input-group textarea:focus { border-color: #00ff00; }
        textarea { resize: vertical; min-height: 100px; }
        
        .button-group { display: flex; gap: 15px; margin-top: 15px; }
        .btn { flex: 1; padding: 15px; border: none; border-radius: 5px; font-size: 1.1rem; font-weight: bold; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
        .btn-login { background: linear-gradient(45deg, #ff0000, #ff4400); color: white; }
        .btn-start { background: linear-gradient(45deg, #00ff00, #00cc00); color: black; }
        .btn-stop { background: linear-gradient(45deg, #ff4444, #ff0000); color: white; }
        
        .stats { background-color: #222; padding: 20px; border-radius: 10px; margin-top: 20px; border: 1px solid #444; }
        .stat-item { display: flex; justify-content: space-between; margin-bottom: 10px; color: #0f0; font-size: 1.1rem; }
        
        .console-container { background-color: #000; border-radius: 10px; padding: 20px; height: 500px; overflow-y: auto; border: 2px solid #333; }
        .console-line { margin-bottom: 8px; padding-left: 10px; border-left: 3px solid transparent; animation: fadeIn 0.5s; }
        .console-line.success { color: #00ff00; border-left-color: #00ff00; }
        .console-line.error { color: #ff0000; border-left-color: #ff0000; }
        .console-line.info { color: #00ffff; border-left-color: #00ffff; }
        .console-line.warning { color: #ffff00; border-left-color: #ffff00; }
        @keyframes fadeIn { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
        
        .status-indicator { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }
        .status-online { background-color: #00ff00; box-shadow: 0 0 10px #00ff00; }
        .status-offline { background-color: #ff0000; box-shadow: 0 0 10px #ff0000; }
        
        #verificationArea { border-top: 1px dashed #555; margin-top: 15px; padding-top: 15px; display: none; }
        
        @media (max-width: 1200px) { .container { flex-direction: column; } .glowing-text { font-size: 2.5rem; } }
    </style>
</head>
<body>
    <div class="header">
        <button class="icon-btn btn-menu" onclick="toggleDrawer()">☰</button>
        <h1 class="glowing-text">PRATIK SPAM PANEL</h1>
        <button class="icon-btn btn-add" onclick="createNewPage(true)">+</button>
    </div>

    <div class="tabs-bar" id="tabsBar"></div>

    <div class="drawer" id="pagesDrawer">
        <div class="drawer-header">
            <h3>PAGES CREATED (<span id="totalPagesCount">0</span>)</h3>
            <button class="drawer-close" onclick="toggleDrawer()">✖</button>
        </div>
        <ul class="pages-list" id="pagesList"></ul>
    </div>
    
    <div class="container">
        <div class="left-panel">
            <h2 class="panel-title">CONTROL PANEL</h2>
            <div class="form-group">
                <div class="input-group">
                    <label for="igUsername">INSTAGRAM USERNAME</label>
                    <input type="text" id="igUsername" placeholder="Enter Username/Email">
                </div>
                <div class="input-group">
                    <label for="igPassword">INSTAGRAM PASSWORD</label>
                    <input type="password" id="igPassword" placeholder="Enter Password">
                </div>
                <div class="button-group">
                    <button class="btn btn-login" onclick="loginStep1()">1st IDP LOGIN</button>
                    <button class="btn btn-stop" onclick="logout()">LOGOUT</button>
                </div>
                
