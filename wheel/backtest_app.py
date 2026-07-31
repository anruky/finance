#!/usr/bin/env python3
"""
Wheel Strategy Backtest Web App
================================
Interactive web UI for running wheel strategy backtests with adjustable
state-specific parameters. Supports GOOGL / QQQ / Tencent datasets.
Stores run history in SQLite.

Usage:
  python3 backtest_app.py
  Then open http://localhost:5566 in your browser.
"""

import os
import sys
import json
import sqlite3
import subprocess
from datetime import datetime

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'backtest_history.db')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
os.makedirs(REPORTS_DIR, exist_ok=True)

PYTHON = sys.executable
RUNNER = os.path.join(BASE_DIR, 'backtest_runner.py')

DATASETS = {
    'GOOGL': {'file': 'googl_data.json', 'ticker': 'GOOGL', 'label': 'Google (GOOGL)'},
    'QQQ': {'file': 'qqq_data.json', 'ticker': 'QQQ', 'label': 'QQQ (Nasdaq 100)'},
    'Tencent': {'file': 'tencent_data.json', 'ticker': 'Tencent (0700.HK)', 'label': 'Tencent (0700.HK)'},
}

STATE_INFO = {
    'A': {'name': 'Low Volatility', 'desc': 'Both expired', 'color': '#667eea'},
    'B': {'name': 'Big Gain', 'desc': 'Call assigned (Act1)', 'color': '#27ae60'},
    'C': {'name': 'Volatile Down', 'desc': 'Put assigned (Act1)', 'color': '#e74c3c'},
    'D': {'name': 'Gain Then Back', 'desc': 'Both expired (Act1)', 'color': '#f39c12'},
    'E': {'name': 'Big Drop', 'desc': 'Put assigned', 'color': '#e67e22'},
}


# ============================================================
# Database
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            dataset TEXT NOT NULL,
            ticker TEXT NOT NULL,
            params_json TEXT NOT NULL,
            annualized_return REAL,
            total_return REAL,
            max_drawdown REAL,
            net_pnl REAL,
            total_premium REAL,
            num_cycles INTEGER,
            num_action1 INTEGER,
            state_counts_json TEXT,
            bh_annualized REAL,
            bh_max_drawdown REAL,
            total_income REAL,
            total_cost REAL,
            financing_cost REAL,
            report_filename TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def save_run(dataset, ticker, targets, s, report_filename, advanced=None):
    net_pnl = s['final_value'] - s['initial_capital']
    total_income = s['total_premium'] + s['total_stock_gains']
    total_cost = s['total_stock_losses'] + s['total_margin_interest']
    # Store targets + advanced params together so Apply can restore everything
    full_params = {'targets': targets}
    if advanced:
        full_params['dte'] = advanced.get('dte', 18)
        full_params['put_iv'] = advanced.get('put_iv', 30)
        full_params['call_iv'] = advanced.get('call_iv', 22)
        full_params['margin_rate'] = advanced.get('margin_rate', 11)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT INTO runs (timestamp, dataset, ticker, params_json,
                          annualized_return, total_return, max_drawdown, net_pnl,
                          total_premium, num_cycles, num_action1, state_counts_json,
                          bh_annualized, bh_max_drawdown, total_income, total_cost,
                          financing_cost, report_filename)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        dataset, ticker, json.dumps(full_params),
        s['annualized_return_pct'], s['total_return_pct'], s['max_drawdown_pct'], net_pnl,
        s['total_premium'], s['num_cycles'], s['num_action1'], json.dumps(s['state_counts']),
        s['buy_hold_annualized_pct'], s['buy_hold_max_drawdown_pct'],
        total_income, total_cost, s['total_margin_interest'],
        report_filename
    ))
    conn.commit()
    run_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return run_id


def get_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('''
        SELECT id, timestamp, dataset, ticker, params_json,
               annualized_return, total_return, max_drawdown, net_pnl,
               total_premium, num_cycles, num_action1, state_counts_json,
               bh_annualized, bh_max_drawdown, total_income, total_cost
        FROM runs ORDER BY id DESC LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    history = []
    for r in rows:
        raw_params = json.loads(r[4])
        # Support both old format (direct targets dict) and new format (with targets + advanced)
        if 'targets' in raw_params:
            targets = raw_params['targets']
            dte = raw_params.get('dte')
            put_iv = raw_params.get('put_iv')
            call_iv = raw_params.get('call_iv')
            margin_rate = raw_params.get('margin_rate')
        else:
            targets = raw_params
            dte = put_iv = call_iv = margin_rate = None
        history.append({
            'id': r[0], 'timestamp': r[1], 'dataset': r[2], 'ticker': r[3],
            'params': targets,
            'dte': dte, 'put_iv': put_iv, 'call_iv': call_iv, 'margin_rate': margin_rate,
            'annualized_return': r[5], 'total_return': r[6], 'max_drawdown': r[7],
            'net_pnl': r[8], 'total_premium': r[9], 'num_cycles': r[10],
            'num_action1': r[11], 'state_counts': json.loads(r[12]),
            'bh_annualized': r[13], 'bh_max_drawdown': r[14],
            'total_income': r[15], 'total_cost': r[16]
        })
    return history


def delete_run(run_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT report_filename FROM runs WHERE id=?', (run_id,)).fetchone()
    if row:
        report_path = os.path.join(REPORTS_DIR, row[0])
        if os.path.exists(report_path):
            os.remove(report_path)
    conn.execute('DELETE FROM runs WHERE id=?', (run_id,))
    conn.commit()
    conn.close()


# ============================================================
# API Routes
# ============================================================

@app.route('/')
def index():
    return HTML_PAGE


@app.route('/api/datasets')
def api_datasets():
    return jsonify(DATASETS)


@app.route('/api/run', methods=['POST'])
def api_run():
    data = request.json
    dataset_key = data.get('dataset', 'GOOGL')
    targets = data.get('targets', {})
    dte = data.get('dte', 18)
    put_iv = data.get('put_iv', 30)
    call_iv = data.get('call_iv', 22)
    margin_rate = data.get('margin_rate', 11)

    if dataset_key not in DATASETS:
        return jsonify({'error': f'Unknown dataset: {dataset_key}'}), 400

    ds = DATASETS[dataset_key]
    data_file = os.path.join(BASE_DIR, ds['file'])

    if not os.path.exists(data_file):
        return jsonify({'error': f'Data file not found: {ds["file"]}'}), 400

    # Generate report path
    report_filename = f'run_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{dataset_key}.html'
    report_path = os.path.join(REPORTS_DIR, report_filename)

    # Run backtest in subprocess to isolate memory
    runner_params = {
        'ticker': ds['ticker'],
        'data_file': data_file,
        'targets': targets,
        'dte': dte,
        'put_iv': put_iv,
        'call_iv': call_iv,
        'margin_rate': margin_rate,
        'report_path': report_path,
    }

    try:
        proc = subprocess.run(
            [PYTHON, RUNNER],
            input=json.dumps(runner_params),
            capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            return jsonify({'error': f'Runner failed: {proc.stderr[-500:]}'}), 500

        s = json.loads(proc.stdout.strip())
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Backtest timed out (60s)'}), 500
    except Exception as e:
        return jsonify({'error': f'Backtest failed: {str(e)}'}), 500

    # Save to history (include advanced params for Apply feature)
    run_id = save_run(dataset_key, ds['ticker'], targets, s, report_filename,
                      advanced={'dte': dte, 'put_iv': put_iv, 'call_iv': call_iv, 'margin_rate': margin_rate})

    net_pnl = s['final_value'] - s['initial_capital']
    total_income = s['total_premium'] + s['total_stock_gains']
    total_cost = s['total_stock_losses'] + s['total_margin_interest']
    state_dist = ' / '.join(f'{k}:{v}' for k, v in sorted(s['state_counts'].items()))

    summary = {
        'id': run_id,
        'dataset': dataset_key,
        'ticker': ds['ticker'],
        'annualized_return': s['annualized_return_pct'],
        'total_return': s['total_return_pct'],
        'max_drawdown': s['max_drawdown_pct'],
        'net_pnl': round(net_pnl, 2),
        'initial_capital': s['initial_capital'],
        'final_value': s['final_value'],
        'total_premium': s['total_premium'],
        'total_income': round(total_income, 2),
        'total_cost': round(total_cost, 2),
        'financing_cost': s['total_margin_interest'],
        'num_cycles': s['num_cycles'],
        'num_action1': s['num_action1'],
        'state_counts': s['state_counts'],
        'state_dist': state_dist,
        'bh_annualized': s['buy_hold_annualized_pct'],
        'bh_return': s['buy_hold_return_pct'],
        'bh_max_drawdown': s['buy_hold_max_drawdown_pct'],
        'report_url': f'/api/report/{run_id}'
    }
    return jsonify(summary)


@app.route('/api/history')
def api_history():
    return jsonify(get_history())


@app.route('/api/report/<int:run_id>')
def api_report(run_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT report_filename, dataset FROM runs WHERE id=?', (run_id,)).fetchone()
    conn.close()
    if not row:
        return 'Report not found', 404
    report_path = os.path.join(REPORTS_DIR, row[0])
    if not os.path.exists(report_path):
        return 'Report file missing', 404
    with open(report_path, 'r') as f:
        return Response(f.read(), mimetype='text/html')


@app.route('/api/download/<int:run_id>')
def api_download(run_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT report_filename, dataset FROM runs WHERE id=?', (run_id,)).fetchone()
    conn.close()
    if not row:
        return 'Report not found', 404
    report_path = os.path.join(REPORTS_DIR, row[0])
    if not os.path.exists(report_path):
        return 'Report file missing', 404
    with open(report_path, 'r') as f:
        content = f.read()
    filename = f'wheel_report_{row[1]}_{run_id}.html'
    return Response(
        content,
        mimetype='text/html',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/api/history/<int:run_id>', methods=['DELETE'])
def api_delete(run_id):
    delete_run(run_id)
    return jsonify({'status': 'deleted'})


# ============================================================
# Frontend HTML
# ============================================================

HTML_PAGE = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wheel Strategy Backtest</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; color: #333; }

.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; }
.header h1 { font-size: 24px; font-weight: 700; }
.header p { font-size: 13px; opacity: 0.85; margin-top: 4px; }

.container { max-width: 1400px; margin: 0 auto; padding: 20px; display: grid; grid-template-columns: 380px 1fr; gap: 20px; }

.left-panel { display: flex; flex-direction: column; gap: 16px; }
.right-panel { display: flex; flex-direction: column; gap: 16px; }

.card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card h2 { font-size: 15px; font-weight: 700; margin-bottom: 14px; color: #1a1a2e; }

/* Dataset selector */
.dataset-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.dataset-btn { padding: 12px 8px; border: 2px solid #e0e0e0; border-radius: 8px; background: white; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; text-align: center; }
.dataset-btn:hover { border-color: #667eea; }
.dataset-btn.active { border-color: #667eea; background: #667eea; color: white; }
.dataset-btn .ds-icon { font-size: 20px; display: block; margin-bottom: 4px; }

/* State params */
.state-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding: 10px; border-radius: 8px; background: #f8f9fa; }
.state-badge { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; color: white; flex-shrink: 0; }
.state-info { flex: 1; min-width: 0; }
.state-name { font-size: 12px; font-weight: 600; color: #333; }
.state-desc { font-size: 10px; color: #888; }
.param-group { display: flex; gap: 8px; }
.param-input { display: flex; align-items: center; gap: 3px; }
.param-input label { font-size: 10px; color: #888; }
.param-input input { width: 48px; padding: 4px 4px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; text-align: center; font-weight: 600; }
.param-input span { font-size: 10px; color: #aaa; }

/* Advanced params */
.adv-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.adv-row label { font-size: 12px; color: #666; }
.adv-row input { width: 70px; padding: 4px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; text-align: right; }

/* Preset buttons */
.preset-row { display: flex; gap: 6px; margin-top: 10px; }
.preset-btn { flex: 1; padding: 6px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; font-size: 11px; font-weight: 600; color: #667eea; }
.preset-btn:hover { background: #f0f0ff; }

/* Run button */
.run-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; border-radius: 10px; font-size: 15px; font-weight: 700; cursor: pointer; transition: all 0.2s; }
.run-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(102,126,234,0.4); }
.run-btn:active { transform: translateY(0); }
.run-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

/* Summary cards */
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.metric-card { background: white; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.metric-label { font-size: 11px; color: #888; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.metric-value { font-size: 22px; font-weight: 800; }
.metric-sub { font-size: 11px; color: #aaa; margin-top: 4px; }
.profit { color: #27ae60; }
.loss { color: #c0392b; }
.neutral { color: #667eea; }

/* Income/Cost */
.ic-section { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.ic-col { background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.ic-col h3 { font-size: 12px; color: #888; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
.ic-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.ic-total { border-top: 1px solid #eee; margin-top: 6px; padding-top: 8px; font-weight: 700; }

/* Report iframe */
.report-frame { width: 100%; height: 700px; border: none; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

/* History table */
.history-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.history-table th { text-align: left; padding: 8px 10px; background: #f8f9fa; color: #666; font-weight: 600; border-bottom: 2px solid #eee; white-space: nowrap; }
.history-table td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
.history-table tr:hover { background: #f8f9fa; cursor: pointer; }
.history-table .del-btn { color: #c0392b; cursor: pointer; font-size: 14px; }
.history-table .del-btn:hover { font-weight: 700; }
.history-table .apply-btn { color: #667eea; cursor: pointer; font-size: 11px; font-weight: 600; padding: 2px 6px; border: 1px solid #667eea; border-radius: 4px; }
.history-table .apply-btn:hover { background: #667eea; color: white; }
.state-tag { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 700; color: white; margin-right: 2px; }
.params-toggle { color: #667eea; cursor: pointer; font-size: 11px; }

/* Loading */
.loading-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.85); display: none; align-items: center; justify-content: center; z-index: 999; }
.loading-overlay.show { display: flex; }
.spinner { width: 40px; height: 40px; border: 4px solid #e0e0e0; border-top-color: #667eea; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { margin-top: 12px; color: #667eea; font-weight: 600; }

/* Empty state */
.empty { text-align: center; padding: 40px; color: #aaa; font-size: 14px; }

/* Params tooltip */
.params-detail { display: none; font-size: 10px; color: #888; margin-top: 4px; }
.params-detail.show { display: block; }
</style>
</head>
<body>

<div class="header">
  <h1>Wheel Strategy Backtest</h1>
  <p>Adjust state A-E parameters, select dataset, run backtest, and compare results</p>
</div>

<div class="container">
  <!-- Left Panel: Controls -->
  <div class="left-panel">
    <!-- Dataset -->
    <div class="card">
      <h2>1. Select Dataset</h2>
      <div class="dataset-grid" id="datasetGrid"></div>
    </div>

    <!-- State Parameters -->
    <div class="card">
      <h2>2. State Parameters (Put% / Call%)</h2>
      <div id="stateParams"></div>
      <div class="preset-row">
        <button class="preset-btn" onclick="applyPreset('aggressive')">Aggressive</button>
        <button class="preset-btn" onclick="applyPreset('balanced')">Balanced</button>
        <button class="preset-btn" onclick="applyPreset('conservative')">Conservative</button>
      </div>
    </div>

    <!-- Advanced -->
    <div class="card">
      <h2>3. Advanced Settings</h2>
      <div class="adv-row">
        <label>DTE (days)</label>
        <input type="number" id="dte" value="18" min="1" max="60">
      </div>
      <div class="adv-row">
        <label>Put IV</label>
        <input type="number" id="putIv" value="30" min="1" max="100" step="1">%
      </div>
      <div class="adv-row">
        <label>Call IV</label>
        <input type="number" id="callIv" value="22" min="1" max="100" step="1">%
      </div>
      <div class="adv-row">
        <label>Margin Rate</label>
        <input type="number" id="marginRate" value="11" min="0" max="50" step="0.5">%
      </div>
    </div>

    <!-- Run -->
    <button class="run-btn" id="runBtn" onclick="runBacktest()">Run Backtest</button>
  </div>

  <!-- Right Panel: Results -->
  <div class="right-panel">
    <!-- Summary Metrics -->
    <div id="summarySection" style="display:none;">
      <div class="summary-grid" id="summaryGrid"></div>
      <div class="ic-section" id="icSection"></div>
    </div>

    <!-- Empty state -->
    <div id="emptyState" class="card">
      <div class="empty">Run a backtest to see results here</div>
    </div>

    <!-- Report -->
    <div id="reportSection" style="display:none;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
        <a href="javascript:void(0)" onclick="goBack()" style="color:#667eea;font-size:14px;font-weight:600;text-decoration:none;cursor:pointer;">&larr; Back</a>
        <span id="reportTitle" style="font-size:13px;color:#888;flex:1;"></span>
        <a id="downloadLink" href="#" download="" style="display:none;color:#27ae60;font-size:13px;font-weight:600;text-decoration:none;cursor:pointer;">&darr; Download HTML</a>
      </div>
      <iframe class="report-frame" id="reportFrame"></iframe>
    </div>

    <!-- History -->
    <div class="card">
      <h2>History</h2>
      <div style="overflow-x:auto;">
        <table class="history-table" id="historyTable">
          <thead>
            <tr>
              <th>#</th>
              <th>Time</th>
              <th>Dataset</th>
              <th>Ann. Ret</th>
              <th>Max DD</th>
              <th>Net P&L</th>
              <th>Premium</th>
              <th>Cyc</th>
              <th>Act1</th>
              <th>States</th>
              <th>B&H Ann</th>
              <th>Apply</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="historyBody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- Loading -->
<div class="loading-overlay" id="loadingOverlay">
  <div style="text-align:center;">
    <div class="spinner"></div>
    <div class="loading-text">Running backtest...</div>
  </div>
</div>

<script>
const DATASETS = {
  'GOOGL': {label: 'Google', icon: 'G'},
  'QQQ': {label: 'QQQ', icon: 'Q'},
  'Tencent': {label: 'Tencent', icon: 'T'}
};
const STATE_INFO = {
  'A': {name: 'Low Volatility', desc: 'Both expired', color: '#667eea'},
  'B': {name: 'Big Gain', desc: 'Call assigned (Act1)', color: '#27ae60'},
  'C': {name: 'Volatile Down', desc: 'Put assigned (Act1)', color: '#e74c3c'},
  'D': {name: 'Gain Then Back', desc: 'Both expired (Act1)', color: '#f39c12'},
  'E': {name: 'Big Drop', desc: 'Put assigned', color: '#e67e22'}
};
const PRESETS = {
  aggressive: {A:{put:50,call:3}, B:{put:50,call:3}, C:{put:20,call:5}, D:{put:50,call:3}, E:{put:20,call:5}},
  balanced: {A:{put:40,call:3}, B:{put:40,call:3}, C:{put:10,call:10}, D:{put:40,call:3}, E:{put:10,call:10}},
  conservative: {A:{put:20,call:5}, B:{put:20,call:5}, C:{put:5,call:15}, D:{put:20,call:5}, E:{put:5,call:15}}
};
let selectedDataset = 'GOOGL';
let historyCache = [];

function initDatasets() {
  const grid = document.getElementById('datasetGrid');
  grid.innerHTML = '';
  Object.entries(DATASETS).forEach(([key, info]) => {
    const btn = document.createElement('div');
    btn.className = 'dataset-btn' + (key === selectedDataset ? ' active' : '');
    btn.innerHTML = `<span class="ds-icon">${info.icon}</span>${info.label}`;
    btn.onclick = () => {
      selectedDataset = key;
      document.querySelectorAll('.dataset-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    };
    grid.appendChild(btn);
  });
}

function initStateParams() {
  const container = document.getElementById('stateParams');
  container.innerHTML = '';
  const defaults = PRESETS.balanced;
  Object.entries(STATE_INFO).forEach(([state, info]) => {
    const row = document.createElement('div');
    row.className = 'state-row';
    row.innerHTML = `
      <div class="state-badge" style="background:${info.color}">${state}</div>
      <div class="state-info">
        <div class="state-name">${info.name}</div>
        <div class="state-desc">${info.desc}</div>
      </div>
      <div class="param-group">
        <div class="param-input">
          <label>P</label>
          <input type="number" id="put_${state}" value="${defaults[state].put}" min="0" max="100" step="1">
          <span>%</span>
        </div>
        <div class="param-input">
          <label>C</label>
          <input type="number" id="call_${state}" value="${defaults[state].call}" min="0" max="100" step="1">
          <span>%</span>
        </div>
      </div>
    `;
    container.appendChild(row);
  });
}

function applyPreset(name) {
  const p = PRESETS[name];
  ['A','B','C','D','E'].forEach(s => {
    document.getElementById('put_'+s).value = p[s].put;
    document.getElementById('call_'+s).value = p[s].call;
  });
}

async function runBacktest() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  document.getElementById('loadingOverlay').classList.add('show');

  const targets = {};
  ['A','B','C','D','E'].forEach(s => {
    targets[s] = {
      put: parseInt(document.getElementById('put_'+s).value) || 0,
      call: parseInt(document.getElementById('call_'+s).value) || 0
    };
  });

  const payload = {
    dataset: selectedDataset,
    targets,
    dte: parseInt(document.getElementById('dte').value) || 18,
    put_iv: parseInt(document.getElementById('putIv').value) || 30,
    call_iv: parseInt(document.getElementById('callIv').value) || 22,
    margin_rate: parseFloat(document.getElementById('marginRate').value) || 11
  };

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.error) {
      alert('Error: ' + data.error);
      return;
    }
    showSummary(data);
    document.getElementById('reportFrame').src = data.report_url;
    document.getElementById('reportTitle').textContent = `#${data.id} - ${data.dataset} - New Run`;
    document.getElementById('downloadLink').href = `/api/download/${data.id}`;
    document.getElementById('downloadLink').style.display = 'inline';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('reportSection').style.display = 'block';
    document.getElementById('summarySection').style.display = 'block';
    loadHistory();
  } catch(e) {
    alert('Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    document.getElementById('loadingOverlay').classList.remove('show');
  }
}

function showSummary(d) {
  const grid = document.getElementById('summaryGrid');
  const cls = d.annualized_return >= 0 ? 'profit' : 'loss';
  const pnlCls = d.net_pnl >= 0 ? 'profit' : 'loss';
  grid.innerHTML = `
    <div class="metric-card">
      <div class="metric-label">Annualized Return</div>
      <div class="metric-value ${cls}">${d.annualized_return >= 0 ? '+' : ''}${d.annualized_return}%</div>
      <div class="metric-sub">B&H: ${d.bh_annualized >= 0 ? '+' : ''}${d.bh_annualized}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value loss">${d.max_drawdown}%</div>
      <div class="metric-sub">B&H: ${d.bh_max_drawdown}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Net P&L</div>
      <div class="metric-value ${pnlCls}">${d.net_pnl >= 0 ? '+' : ''}$${d.net_pnl.toLocaleString()}</div>
      <div class="metric-sub">${d.num_cycles} cycles, ${d.num_action1} Act1</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Total Premium</div>
      <div class="metric-value profit">$${d.total_premium.toLocaleString()}</div>
      <div class="metric-sub">${d.state_dist}</div>
    </div>
  `;

  const ic = document.getElementById('icSection');
  ic.innerHTML = `
    <div class="ic-col">
      <h3>Income</h3>
      <div class="ic-row"><span>Premium</span><span class="profit">$${d.total_premium.toLocaleString()}</span></div>
      <div class="ic-row"><span>Stock gains</span><span class="profit">$${Math.round(d.total_income - d.total_premium).toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Total</span><span class="profit">$${Math.round(d.total_income).toLocaleString()}</span></div>
    </div>
    <div class="ic-col">
      <h3>Cost</h3>
      <div class="ic-row"><span>Stock losses</span><span class="loss">$${Math.round(d.total_cost - d.financing_cost).toLocaleString()}</span></div>
      <div class="ic-row"><span>Financing</span><span class="loss">$${d.financing_cost.toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Total</span><span class="loss">$${Math.round(d.total_cost).toLocaleString()}</span></div>
    </div>
    <div class="ic-col">
      <h3>Net</h3>
      <div class="ic-row ic-total"><span>P&L</span><span class="${pnlCls}">${d.net_pnl >= 0 ? '+' : ''}$${d.net_pnl.toLocaleString()}</span></div>
      <div class="ic-row"><span>Return</span><span class="${cls}">${d.total_return >= 0 ? '+' : ''}${d.total_return}%</span></div>
      <div class="ic-row"><span>Initial</span><span>$${d.initial_capital.toLocaleString()}</span></div>
      <div class="ic-row"><span>Final</span><span>$${d.final_value.toLocaleString()}</span></div>
    </div>
  `;
}

async function loadHistory() {
  const resp = await fetch('/api/history');
  const history = await resp.json();
  historyCache = history;
  const tbody = document.getElementById('historyBody');
  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:#aaa;padding:20px;">No runs yet</td></tr>';
    return;
  }
  tbody.innerHTML = history.map(h => {
    const annCls = h.annualized_return >= 0 ? 'profit' : 'loss';
    const pnlCls = h.net_pnl >= 0 ? 'profit' : 'loss';
    const bhCls = h.bh_annualized >= 0 ? 'profit' : 'loss';
    let statesHtml = '';
    if (h.state_counts) {
      Object.entries(h.state_counts).forEach(([s, c]) => {
        if (c > 0) statesHtml += `<span class="state-tag" style="background:${STATE_INFO[s].color}">${s}:${c}</span>`;
      });
    }
    let paramsStr = '';
    if (h.params) {
      ['A','B','C','D','E'].forEach(s => {
        if (h.params[s]) paramsStr += `${s}:${h.params[s].put}/${h.params[s].call} `;
      });
    }
    let advStr = '';
    if (h.dte) advStr += `DTE=${h.dte}`;
    if (h.put_iv) advStr += ` IV=${h.put_iv}/${h.call_iv}`;
    return `<tr onclick="loadReport(${h.id})">
      <td>${h.id}</td>
      <td>${h.timestamp}</td>
      <td>${h.dataset}</td>
      <td class="${annCls}">${h.annualized_return >= 0 ? '+' : ''}${h.annualized_return}%</td>
      <td class="loss">${h.max_drawdown}%</td>
      <td class="${pnlCls}">${h.net_pnl >= 0 ? '+' : ''}$${Math.round(h.net_pnl).toLocaleString()}</td>
      <td>$${Math.round(h.total_premium).toLocaleString()}</td>
      <td>${h.num_cycles}</td>
      <td>${h.num_action1}</td>
      <td>${statesHtml}</td>
      <td class="${bhCls}">${h.bh_annualized >= 0 ? '+' : ''}${h.bh_annualized}%</td>
      <td><span class="apply-btn" onclick="event.stopPropagation();applyParams(${h.id})" title="${paramsStr}${advStr}">Apply</span></td>
      <td><span class="del-btn" onclick="event.stopPropagation();deleteRun(${h.id})">x</span></td>
    </tr>`;
  }).join('');
}

function loadReport(id) {
  document.getElementById('reportFrame').src = `/api/report/${id}`;
  document.getElementById('downloadLink').href = `/api/download/${id}`;
  document.getElementById('downloadLink').style.display = 'inline';
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('reportSection').style.display = 'block';
  // Populate summary from cached history data
  const h = historyCache.find(r => r.id === id);
  if (h) {
    showHistorySummary(h);
    document.getElementById('reportTitle').textContent = `#${h.id} - ${h.dataset} - ${h.timestamp}`;
  } else {
    document.getElementById('reportTitle').textContent = `#${id}`;
  }
  // Scroll to top of right panel
  document.getElementById('reportSection').scrollIntoView({behavior:'smooth', block:'start'});
}

function goBack() {
  document.getElementById('reportSection').style.display = 'none';
  document.getElementById('summarySection').style.display = 'none';
  document.getElementById('emptyState').style.display = 'block';
  document.getElementById('reportFrame').src = '';
  document.getElementById('reportTitle').textContent = '';
  document.getElementById('downloadLink').style.display = 'none';
}

function showHistorySummary(h) {
  const grid = document.getElementById('summaryGrid');
  const cls = h.annualized_return >= 0 ? 'profit' : 'loss';
  const pnlCls = h.net_pnl >= 0 ? 'profit' : 'loss';
  const bhCls = h.bh_annualized >= 0 ? 'profit' : 'loss';
  grid.innerHTML = `
    <div class="metric-card">
      <div class="metric-label">Annualized Return</div>
      <div class="metric-value ${cls}">${h.annualized_return >= 0 ? '+' : ''}${h.annualized_return}%</div>
      <div class="metric-sub">B&H: ${h.bh_annualized >= 0 ? '+' : ''}${h.bh_annualized}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value loss">${h.max_drawdown}%</div>
      <div class="metric-sub">B&H: ${h.bh_max_drawdown}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Net P&L</div>
      <div class="metric-value ${pnlCls}">${h.net_pnl >= 0 ? '+' : ''}$${Math.round(h.net_pnl).toLocaleString()}</div>
      <div class="metric-sub">${h.num_cycles} cycles, ${h.num_action1} Act1</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Total Premium</div>
      <div class="metric-value profit">$${Math.round(h.total_premium).toLocaleString()}</div>
      <div class="metric-sub">${h.dataset}</div>
    </div>
  `;

  let stateDist = '';
  if (h.state_counts) {
    stateDist = Object.entries(h.state_counts).filter(([,c]) => c > 0).map(([s,c]) => `${s}:${c}`).join(' / ');
  }
  const ic = document.getElementById('icSection');
  ic.innerHTML = `
    <div class="ic-col">
      <h3>Income</h3>
      <div class="ic-row"><span>Premium</span><span class="profit">$${Math.round(h.total_premium).toLocaleString()}</span></div>
      <div class="ic-row"><span>Stock gains</span><span class="profit">$${Math.round(h.total_income - h.total_premium).toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Total</span><span class="profit">$${Math.round(h.total_income).toLocaleString()}</span></div>
    </div>
    <div class="ic-col">
      <h3>Cost</h3>
      <div class="ic-row"><span>Stock losses</span><span class="loss">$${Math.round(h.total_cost).toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Total</span><span class="loss">$${Math.round(h.total_cost).toLocaleString()}</span></div>
    </div>
    <div class="ic-col">
      <h3>Net</h3>
      <div class="ic-row ic-total"><span>P&L</span><span class="${pnlCls}">${h.net_pnl >= 0 ? '+' : ''}$${Math.round(h.net_pnl).toLocaleString()}</span></div>
      <div class="ic-row"><span>Return</span><span class="${cls}">${h.total_return >= 0 ? '+' : ''}${h.total_return}%</div>
      <div class="ic-row"><span>States</span><span>${stateDist}</span></div>
    </div>
  `;
  document.getElementById('summarySection').style.display = 'block';
}

function applyParams(id) {
  const h = historyCache.find(r => r.id === id);
  if (!h) return;
  // Apply state targets
  ['A','B','C','D','E'].forEach(s => {
    if (h.params && h.params[s]) {
      document.getElementById('put_'+s).value = h.params[s].put;
      document.getElementById('call_'+s).value = h.params[s].call;
    }
  });
  // Apply advanced settings
  if (h.dte) document.getElementById('dte').value = h.dte;
  if (h.put_iv) document.getElementById('putIv').value = h.put_iv;
  if (h.call_iv) document.getElementById('callIv').value = h.call_iv;
  if (h.margin_rate) document.getElementById('marginRate').value = h.margin_rate;
  // Select the dataset
  selectedDataset = h.dataset;
  document.querySelectorAll('.dataset-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.dataset-btn').forEach((b, i) => {
    if (Object.keys(DATASETS)[i] === h.dataset) b.classList.add('active');
  });
  // Scroll to top
  document.querySelector('.left-panel').scrollIntoView({behavior:'smooth', block:'start'});
}

async function deleteRun(id) {
  if (!confirm('Delete this run?')) return;
  await fetch(`/api/history/${id}`, {method: 'DELETE'});
  loadHistory();
}

// Init
initDatasets();
initStateParams();
loadHistory();
</script>
</body>
</html>
'''


if __name__ == '__main__':
    init_db()
    print(f"\n  Wheel Strategy Backtest App")
    print(f"  ===========================")
    print(f"  Open http://localhost:5566 in your browser")
    print(f"  Data dir: {BASE_DIR}")
    print(f"  Reports:  {REPORTS_DIR}")
    print(f"  Database: {DB_PATH}\n")
    app.run(host='0.0.0.0', port=5566, debug=False)
