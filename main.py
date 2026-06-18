from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, date, timedelta
from typing import Optional, List
import csv
from io import StringIO
from fastapi.responses import StreamingResponse

from models import (
    Base, SessionLocal, init_db, Clue, User, FollowupRecord, AssignmentRule,
    create_engine_and_session
)
from schemas import (
    ClueCreate, ClueUpdate, ClueResponse, ClueDetailResponse,
    FollowupRecordCreate, FollowupRecordResponse,
    UserCreate, UserResponse,
    AssignmentRuleCreate, AssignmentRuleResponse,
    ReassignRequest, DailyReportResponse
)
from assignment_engine import auto_assign_clue, validate_reassign

app = FastAPI(title="线索分派与跟进看板", description="FastAPI + SQLite 实现的线索管理系统")

app.state.engine, app.state.session_factory = create_engine_and_session()


def get_session_factory():
    return app.state.session_factory


def get_db():
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup_event():
    init_db(app.state.engine, app.state.session_factory)
    _check_overdue_internal(app.state.session_factory)


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>线索分派与跟进看板</title>
        <meta charset="utf-8">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #f5f7fa; }
            h1 { color: #2c3e50; }
            .card { background: white; border-radius: 8px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .kanban { display: flex; gap: 15px; flex-wrap: wrap; }
            .column { flex: 1; min-width: 250px; background: #eef2f7; border-radius: 8px; padding: 12px; }
            .column h3 { margin-top: 0; color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 8px; }
            .clue-card { background: white; border-radius: 6px; padding: 12px; margin: 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); cursor: pointer; }
            .clue-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,0.15); }
            .clue-title { font-weight: bold; color: #2c3e50; margin-bottom: 4px; }
            .clue-meta { font-size: 12px; color: #7f8c8d; }
            .overdue { border-left: 4px solid #e74c3c; }
            .warning { border-left: 4px solid #f39c12; }
            .priority-high { background: #ffebee; }
            .priority-medium { background: #fff8e1; }
            .priority-low { background: #e8f5e9; }
            .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
            .btn-primary { background: #3498db; color: white; }
            .btn-success { background: #27ae60; color: white; }
            .btn-danger { background: #e74c3c; color: white; }
            input, select, textarea { padding: 8px; border: 1px solid #ddd; border-radius: 4px; margin: 4px; }
            .form-row { margin: 8px 0; }
            label { display: inline-block; width: 100px; color: #555; }
            .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-right: 4px; }
            .badge-overdue { background: #e74c3c; color: white; }
            .badge-today { background: #f39c12; color: white; }
            .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; }
            .stat-card { background: white; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .stat-num { font-size: 28px; font-weight: bold; color: #2c3e50; }
            .stat-label { font-size: 13px; color: #7f8c8d; margin-top: 4px; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; }
            .modal-content { background: white; margin: 5% auto; padding: 20px; border-radius: 8px; width: 600px; max-width: 90%; max-height: 80vh; overflow-y: auto; }
            .close-btn { float: right; font-size: 24px; cursor: pointer; color: #aaa; }
            .close-btn:hover { color: #333; }
            .followup-item { border-left: 3px solid #3498db; padding: 8px 12px; margin: 8px 0; background: #f8f9fa; }
            .followup-time { font-size: 11px; color: #95a5a6; }
            .tabs { margin: 10px 0; border-bottom: 2px solid #eee; }
            .tab { display: inline-block; padding: 8px 16px; cursor: pointer; margin-right: 4px; }
            .tab.active { border-bottom: 2px solid #3498db; color: #3498db; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>📋 线索分派与跟进看板</h1>
        
        <div class="stat-grid" id="stats">
            <div class="stat-card"><div class="stat-num" id="stat-total">0</div><div class="stat-label">总线索</div></div>
            <div class="stat-card"><div class="stat-num" id="stat-new">0</div><div class="stat-label">今日新增</div></div>
            <div class="stat-card"><div class="stat-num" id="stat-followup">0</div><div class="stat-label">今日跟进</div></div>
            <div class="stat-card"><div class="stat-num" id="stat-overdue" style="color:#e74c3c">0</div><div class="stat-label">逾期未跟进</div></div>
        </div>

        <div class="card">
            <div class="tabs">
                <div class="tab active" onclick="switchTab('kanban')">看板</div>
                <div class="tab" onclick="switchTab('add')">录入线索</div>
                <div class="tab" onclick="switchTab('report')">日报</div>
                <div class="tab" onclick="switchTab('rules')">分派规则</div>
            </div>

            <div id="tab-kanban">
                <div style="margin: 10px 0;">
                    <button class="btn btn-primary" onclick="loadKanban()">🔄 刷新看板</button>
                    <button class="btn btn-success" onclick="exportDailyReport()">📊 导出日报</button>
                    <select id="filter-stage" onchange="loadKanban()">
                        <option value="">全部阶段</option>
                        <option value="new">新建</option>
                        <option value="contacted">已联系</option>
                        <option value="qualified">已确认意向</option>
                        <option value="negotiating">商务洽谈</option>
                        <option value="won">已成交</option>
                        <option value="lost">已流失</option>
                    </select>
                    <select id="filter-user" onchange="loadKanban()">
                        <option value="">全部负责人</option>
                    </select>
                </div>
                <div class="kanban" id="kanban-board"></div>
            </div>

            <div id="tab-add" style="display:none;">
                <h3>录入新线索</h3>
                <div class="form-row"><label>线索标题：</label><input type="text" id="new-title" style="width:300px;"></div>
                <div class="form-row"><label>客户姓名：</label><input type="text" id="new-customer"></div>
                <div class="form-row"><label>联系电话：</label><input type="text" id="new-phone"></div>
                <div class="form-row">
                    <label>线索来源：</label>
                    <select id="new-source">
                        <option value="官网">官网</option>
                        <option value="转介绍">转介绍</option>
                        <option value="展会">展会</option>
                        <option value="广告">广告</option>
                        <option value="其他">其他</option>
                    </select>
                </div>
                <div class="form-row">
                    <label>地区：</label>
                    <select id="new-region">
                        <option value="华北">华北</option>
                        <option value="华东">华东</option>
                        <option value="华南">华南</option>
                        <option value="华中">华中</option>
                        <option value="西南">西南</option>
                        <option value="西北">西北</option>
                        <option value="东北">东北</option>
                    </select>
                </div>
                <div class="form-row">
                    <label>优先级：</label>
                    <select id="new-priority">
                        <option value="high">高</option>
                        <option value="medium" selected>中</option>
                        <option value="low">低</option>
                    </select>
                </div>
                <div class="form-row"><label>详细描述：</label><textarea id="new-description" rows="3" style="width:400px;"></textarea></div>
                <div class="form-row">
                    <button class="btn btn-primary" onclick="createClue()">📝 保存并自动分派</button>
                </div>
                <div id="create-result" style="margin-top:10px;"></div>
            </div>

            <div id="tab-report" style="display:none;">
                <h3>日报统计</h3>
                <div class="form-row">
                    <label>日期：</label><input type="date" id="report-date" value="">
                    <button class="btn btn-primary" onclick="loadReport()">查询</button>
                    <button class="btn btn-success" onclick="exportDailyReport()">导出 CSV</button>
                </div>
                <div id="report-content"></div>
            </div>

            <div id="tab-rules" style="display:none;">
                <h3>分派规则配置</h3>
                <div id="rules-list"></div>
                <div style="margin-top:15px;">
                    <h4>添加规则</h4>
                    <div class="form-row">
                        <label>负责人：</label><select id="rule-user"></select>
                        <label>来源：</label><select id="rule-source"><option value="">全部</option><option value="官网">官网</option><option value="转介绍">转介绍</option><option value="展会">展会</option><option value="广告">广告</option></select>
                    </div>
                    <div class="form-row">
                        <label>地区：</label><select id="rule-region"><option value="">全部</option><option value="华北">华北</option><option value="华东">华东</option><option value="华南">华南</option><option value="华中">华中</option></select>
                        <label>优先级：</label><select id="rule-priority"><option value="">全部</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select>
                        <label>排序：</label><input type="number" id="rule-order" value="0" style="width:60px;">
                    </div>
                    <button class="btn btn-primary" onclick="addRule()">添加规则</button>
                </div>
            </div>
        </div>

        <div id="clue-modal" class="modal">
            <div class="modal-content">
                <span class="close-btn" onclick="closeModal()">&times;</span>
                <h2 id="modal-title">线索详情</h2>
                <div id="modal-body"></div>
            </div>
        </div>

        <script>
            const STAGES = [
                { key: 'new', label: '🆕 新建' },
                { key: 'contacted', label: '📞 已联系' },
                { key: 'qualified', label: '✅ 已确认意向' },
                { key: 'negotiating', label: '💼 商务洽谈' },
                { key: 'won', label: '🎉 已成交' },
                { key: 'lost', label: '❌ 已流失' }
            ];

            const STAGE_LABELS = {};
            STAGES.forEach(s => STAGE_LABELS[s.key] = s.label);

            function switchTab(tabName) {
                ['kanban', 'add', 'report', 'rules'].forEach(t => {
                    document.getElementById('tab-' + t).style.display = t === tabName ? 'block' : 'none';
                });
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                event.target.classList.add('active');
                if (tabName === 'kanban') loadKanban();
                if (tabName === 'report') loadReport();
                if (tabName === 'rules') loadRules();
            }

            async function loadUsers() {
                const res = await fetch('/api/users');
                const users = await res.json();
                const filterSel = document.getElementById('filter-user');
                const ruleSel = document.getElementById('rule-user');
                filterSel.innerHTML = '<option value="">全部负责人</option>';
                ruleSel.innerHTML = '';
                users.forEach(u => {
                    filterSel.innerHTML += `<option value="${u.id}">${u.name}</option>`;
                    ruleSel.innerHTML += `<option value="${u.id}">${u.name}</option>`;
                });
            }

            function formatTime(dt) {
                if (!dt) return '从未跟进';
                const d = new Date(dt);
                const now = new Date();
                const diff = now - d;
                const hours = Math.floor(diff / (1000 * 60 * 60));
                if (hours < 1) return '刚刚';
                if (hours < 24) return `${hours}小时前`;
                const days = Math.floor(hours / 24);
                return `${days}天前`;
            }

            function getReminderStatus(clue) {
                if (clue.is_overdue) return '<span class="badge badge-overdue">逾期</span>';
                if (clue.next_followup_at) {
                    const next = new Date(clue.next_followup_at);
                    const now = new Date();
                    const diff = next - now;
                    if (diff > 0 && diff < 24 * 60 * 60 * 1000) {
                        return '<span class="badge badge-today">今日待跟进</span>';
                    }
                }
                return '';
            }

            async function loadKanban() {
                const stage = document.getElementById('filter-stage').value;
                const user = document.getElementById('filter-user').value;
                let url = '/api/kanban?';
                if (stage) url += '&stage=' + stage;
                if (user) url += '&assignee_id=' + user;
                
                const res = await fetch(url);
                const data = await res.json();

                document.getElementById('stat-total').textContent = data.total;
                document.getElementById('stat-new').textContent = data.today_new;
                document.getElementById('stat-followup').textContent = data.today_followup;
                document.getElementById('stat-overdue').textContent = data.overdue_count;

                const board = document.getElementById('kanban-board');
                board.innerHTML = '';

                STAGES.forEach(stage => {
                    const clues = data.by_stage[stage.key] || [];
                    const col = document.createElement('div');
                    col.className = 'column';
                    col.innerHTML = `<h3>${stage.label} (${clues.length})</h3>`;
                    
                    clues.forEach(clue => {
                        const card = document.createElement('div');
                        let cls = 'clue-card priority-' + clue.priority;
                        if (clue.is_overdue) cls += ' overdue';
                        card.className = cls;
                        card.onclick = () => openClue(clue.id);
                        card.innerHTML = `
                            <div class="clue-title">${clue.title}</div>
                            <div class="clue-meta">客户：${clue.customer_name || '未填写'}</div>
                            <div class="clue-meta">负责人：${clue.assignee_name || '待分派'}</div>
                            <div class="clue-meta">最后跟进：${formatTime(clue.last_followup_at)}</div>
                            <div style="margin-top:4px;">${getReminderStatus(clue)}</div>
                        `;
                        col.appendChild(card);
                    });
                    
                    board.appendChild(col);
                });
            }

            async function createClue() {
                const data = {
                    title: document.getElementById('new-title').value,
                    customer_name: document.getElementById('new-customer').value,
                    phone: document.getElementById('new-phone').value,
                    source: document.getElementById('new-source').value,
                    region: document.getElementById('new-region').value,
                    priority: document.getElementById('new-priority').value,
                    description: document.getElementById('new-description').value
                };
                
                if (!data.title) {
                    alert('请填写线索标题');
                    return;
                }

                const res = await fetch('/api/clues', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await res.json();
                const resultDiv = document.getElementById('create-result');
                if (res.ok) {
                    resultDiv.innerHTML = `<div style="color:green; padding:10px; background:#e8f5e9; border-radius:4px;">
                        ✅ 线索创建成功！已分派给：${result.assignee_name || '无（请检查规则）'}
                        <br>线索ID：${result.id}
                    </div>`;
                    ['new-title', 'new-customer', 'new-phone', 'new-description'].forEach(id => {
                        document.getElementById(id).value = '';
                    });
                } else {
                    resultDiv.innerHTML = `<div style="color:red; padding:10px; background:#ffebee; border-radius:4px;">
                        ❌ 创建失败：${result.detail || '未知错误'}
                    </div>`;
                }
            }

            async function openClue(id) {
                const res = await fetch('/api/clues/' + id);
                const clue = await res.json();
                
                document.getElementById('modal-title').textContent = clue.title;
                let html = `
                    <p><strong>客户：</strong>${clue.customer_name || '未填写'} | 
                       <strong>电话：</strong>${clue.phone || '未填写'} | 
                       <strong>来源：</strong>${clue.source || '未填写'} | 
                       <strong>地区：</strong>${clue.region || '未填写'}</p>
                    <p><strong>阶段：</strong>${STAGE_LABELS[clue.stage] || clue.stage} | 
                       <strong>优先级：</strong>${clue.priority} | 
                       <strong>状态：</strong>${clue.status}</p>
                    <p><strong>负责人：</strong>${clue.assignee_name || '待分派'}</p>
                    <p><strong>描述：</strong>${clue.description || '无'}</p>
                    <p><strong>上次跟进：</strong>${clue.last_followup_at ? new Date(clue.last_followup_at).toLocaleString() : '从未跟进'}
                       <strong>下次跟进：</strong>${clue.next_followup_at ? new Date(clue.next_followup_at).toLocaleString() : '未设置'}
                       ${clue.is_overdue ? '<span class="badge badge-overdue">逾期</span>' : ''}</p>
                    
                    <div style="margin:15px 0; padding:10px; background:#f0f4f8; border-radius:6px;">
                        <h4>🔄 转派线索</h4>
                        <select id="reassign-user"></select>
                        <button class="btn btn-primary" onclick="reassignClue(${clue.id})">转派</button>
                        <div id="reassign-result"></div>
                    </div>

                    <div style="margin:15px 0; padding:10px; background:#f0f4f8; border-radius:6px;">
                        <h4>📝 添加跟进记录</h4>
                        <div class="form-row">
                            <label>跟进阶段：</label>
                            <select id="followup-stage">
                                ${STAGES.map(s => `<option value="${s.key}" ${s.key === clue.stage ? 'selected' : ''}>${s.label}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-row">
                            <label>下次跟进：</label>
                            <input type="datetime-local" id="followup-next">
                        </div>
                        <div class="form-row">
                            <label>跟进内容：</label>
                            <textarea id="followup-content" rows="3" style="width:400px;"></textarea>
                        </div>
                        <button class="btn btn-success" onclick="addFollowup(${clue.id})">保存跟进</button>
                        <div id="followup-result"></div>
                    </div>

                    <h4>📋 跟进历史</h4>
                    <div id="followup-list">
                `;

                if (clue.followups && clue.followups.length > 0) {
                    clue.followups.forEach(f => {
                        html += `<div class="followup-item">
                            <div class="followup-time">${new Date(f.created_at).toLocaleString()} - 阶段：${STAGE_LABELS[f.stage_after] || f.stage_after}</div>
                            <div>${f.content}</div>
                        </div>`;
                    });
                } else {
                    html += '<p>暂无跟进记录</p>';
                }

                html += '</div>';

                document.getElementById('modal-body').innerHTML = html;
                document.getElementById('clue-modal').style.display = 'block';

                const usersRes = await fetch('/api/users');
                const users = await usersRes.json();
                const sel = document.getElementById('reassign-user');
                sel.innerHTML = users.map(u => `<option value="${u.id}">${u.name}</option>`).join('');
            }

            async function reassignClue(clueId) {
                const userId = document.getElementById('reassign-user').value;
                const res = await fetch(`/api/clues/${clueId}/reassign`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target_user_id: parseInt(userId) })
                });
                const result = await res.json();
                const div = document.getElementById('reassign-result');
                if (res.ok) {
                    div.innerHTML = `<div style="color:green;">✅ 转派成功！新负责人：${result.assignee_name}</div>`;
                    setTimeout(() => { loadKanban(); openClue(clueId); }, 500);
                } else {
                    div.innerHTML = `<div style="color:red;">❌ 转派失败：${result.detail}</div>`;
                }
            }

            async function addFollowup(clueId) {
                const content = document.getElementById('followup-content').value;
                const stage_after = document.getElementById('followup-stage').value;
                const next = document.getElementById('followup-next').value;
                
                if (!content) {
                    alert('请填写跟进内容');
                    return;
                }

                const data = {
                    content,
                    stage_after,
                    next_followup_at: next || null
                };

                const res = await fetch(`/api/clues/${clueId}/followup`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await res.json();
                const div = document.getElementById('followup-result');
                if (res.ok) {
                    div.innerHTML = '<div style="color:green;">✅ 跟进记录已保存</div>';
                    setTimeout(() => { loadKanban(); openClue(clueId); }, 500);
                } else {
                    div.innerHTML = `<div style="color:red;">❌ 保存失败：${result.detail}</div>`;
                }
            }

            function closeModal() {
                document.getElementById('clue-modal').style.display = 'none';
            }

            window.onclick = function(event) {
                const modal = document.getElementById('clue-modal');
                if (event.target === modal) closeModal();
            }

            async function loadReport() {
                const date = document.getElementById('report-date').value || new Date().toISOString().split('T')[0];
                const res = await fetch('/api/reports/daily?date=' + date);
                const report = await res.json();

                let html = `
                    <div class="stat-grid">
                        <div class="stat-card"><div class="stat-num">${report.total_clues}</div><div class="stat-label">总线索</div></div>
                        <div class="stat-card"><div class="stat-num" style="color:#3498db;">${report.new_clues}</div><div class="stat-label">新增线索</div></div>
                        <div class="stat-card"><div class="stat-num" style="color:#27ae60;">${report.followed_up}</div><div class="stat-label">已跟进</div></div>
                        <div class="stat-card"><div class="stat-num" style="color:#e74c3c;">${report.overdue_clues}</div><div class="stat-label">逾期</div></div>
                    </div>
                    
                    <h4>按阶段统计</h4>
                    <table border="1" cellpadding="8" style="border-collapse:collapse; margin:10px 0;">
                        <tr>${Object.keys(report.by_stage).map(s => `<th>${STAGE_LABELS[s] || s}</th>`).join('')}</tr>
                        <tr>${Object.values(report.by_stage).map(v => `<td style="text-align:center;">${v}</td>`).join('')}</tr>
                    </table>

                    <h4>按负责人统计</h4>
                    <table border="1" cellpadding="8" style="border-collapse:collapse; margin:10px 0;">
                        <tr><th>负责人</th><th>线索数</th><th>已跟进</th><th>逾期</th></tr>
                `;

                Object.entries(report.by_user).forEach(([name, stats]) => {
                    html += `<tr><td>${name}</td><td>${stats.total}</td><td>${stats.followed}</td><td>${stats.overdue}</td></tr>`;
                });

                html += '</table></div>';
                document.getElementById('report-content').innerHTML = html;
            }

            async function exportDailyReport() {
                const date = document.getElementById('report-date')?.value || new Date().toISOString().split('T')[0];
                window.open('/api/reports/daily/export?date=' + date);
            }

            async function loadRules() {
                const res = await fetch('/api/assignment-rules');
                const rules = await res.json();
                
                let html = '<table border="1" cellpadding="8" style="border-collapse:collapse; width:100%;">';
                html += '<tr><th>负责人</th><th>来源</th><th>地区</th><th>优先级</th><th>排序</th><th>操作</th></tr>';
                
                rules.forEach(rule => {
                    html += `<tr>
                        <td>${rule.user ? rule.user.name : '未知'}</td>
                        <td>${rule.source || '全部'}</td>
                        <td>${rule.region || '全部'}</td>
                        <td>${rule.priority || '全部'}</td>
                        <td>${rule.priority_order}</td>
                        <td><button class="btn btn-danger" onclick="deleteRule(${rule.id})">删除</button></td>
                    </tr>`;
                });
                
                html += '</table>';
                document.getElementById('rules-list').innerHTML = html;
            }

            async function addRule() {
                const data = {
                    user_id: parseInt(document.getElementById('rule-user').value),
                    source: document.getElementById('rule-source').value,
                    region: document.getElementById('rule-region').value,
                    priority: document.getElementById('rule-priority').value,
                    priority_order: parseInt(document.getElementById('rule-order').value)
                };
                
                const res = await fetch('/api/assignment-rules', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (res.ok) {
                    loadRules();
                } else {
                    const err = await res.json();
                    alert('添加失败：' + err.detail);
                }
            }

            async function deleteRule(id) {
                if (confirm('确定删除此规则？')) {
                    await fetch('/api/assignment-rules/' + id, { method: 'DELETE' });
                    loadRules();
                }
            }

            document.getElementById('report-date').value = new Date().toISOString().split('T')[0];
            loadUsers().then(() => {
                loadKanban();
            });
        </script>
    </body>
    </html>
    """


@app.get("/api/users", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return users


@app.post("/api/users", response_model=UserResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.name == user.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名称已存在")
    db_user = User(name=user.name, email=user.email)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.get("/api/assignment-rules", response_model=List[AssignmentRuleResponse])
def list_rules(db: Session = Depends(get_db)):
    rules = db.query(AssignmentRule).order_by(AssignmentRule.priority_order).all()
    return rules


@app.post("/api/assignment-rules", response_model=AssignmentRuleResponse)
def create_rule(rule: AssignmentRuleCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == rule.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")
    db_rule = AssignmentRule(
        user_id=rule.user_id,
        source=rule.source,
        region=rule.region,
        priority=rule.priority,
        priority_order=rule.priority_order
    )
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@app.delete("/api/assignment-rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(AssignmentRule).filter(AssignmentRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    return {"message": "删除成功"}


@app.get("/api/clues", response_model=List[ClueResponse])
def list_clues(
    stage: Optional[str] = None,
    assignee_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Clue)
    if stage:
        query = query.filter(Clue.stage == stage)
    if assignee_id:
        query = query.filter(Clue.assignee_id == assignee_id)
    if status:
        query = query.filter(Clue.status == status)
    
    clues = query.order_by(desc(Clue.created_at)).all()
    
    result = []
    for clue in clues:
        clue_dict = clue.__dict__.copy()
        clue_dict['assignee_name'] = clue.assignee.name if clue.assignee else None
        result.append(clue_dict)
    
    return result


@app.get("/api/clues/{clue_id}", response_model=ClueDetailResponse)
def get_clue(clue_id: int, db: Session = Depends(get_db)):
    clue = db.query(Clue).filter(Clue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    
    clue_dict = clue.__dict__.copy()
    clue_dict['assignee_name'] = clue.assignee.name if clue.assignee else None
    followups = [f.__dict__ for f in clue.followups]
    clue_dict['followups'] = followups
    
    return clue_dict


@app.post("/api/clues", response_model=ClueResponse)
def create_clue(clue_data: ClueCreate, db: Session = Depends(get_db)):
    new_clue = Clue(
        title=clue_data.title,
        customer_name=clue_data.customer_name,
        phone=clue_data.phone,
        source=clue_data.source,
        region=clue_data.region,
        priority=clue_data.priority,
        description=clue_data.description,
        stage="new",
        status="active"
    )
    
    db.add(new_clue)
    db.flush()
    
    assigned_user, error = auto_assign_clue(db, new_clue)
    if assigned_user:
        new_clue.assignee_id = assigned_user.id
    
    db.commit()
    db.refresh(new_clue)
    
    result = new_clue.__dict__.copy()
    result['assignee_name'] = assigned_user.name if assigned_user else None
    
    return result


@app.post("/api/clues/{clue_id}/reassign", response_model=ClueResponse)
def reassign_clue(clue_id: int, request: ReassignRequest, db: Session = Depends(get_db)):
    valid, error_msg = validate_reassign(db, clue_id, request.target_user_id)
    if not valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    clue = db.query(Clue).filter(Clue.id == clue_id).first()
    target_user = db.query(User).filter(User.id == request.target_user_id).first()
    
    clue.assignee_id = target_user.id
    db.commit()
    db.refresh(clue)
    
    result = clue.__dict__.copy()
    result['assignee_name'] = target_user.name
    
    return result


@app.post("/api/clues/{clue_id}/followup", response_model=FollowupRecordResponse)
def add_followup(clue_id: int, followup_data: FollowupRecordCreate, db: Session = Depends(get_db)):
    clue = db.query(Clue).filter(Clue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    
    record = FollowupRecord(
        clue_id=clue_id,
        content=followup_data.content,
        stage_after=followup_data.stage_after or clue.stage,
        next_followup_at=followup_data.next_followup_at,
        created_by=followup_data.created_by
    )
    
    db.add(record)
    
    clue.last_followup_at = datetime.utcnow()
    if followup_data.stage_after:
        clue.stage = followup_data.stage_after
    if followup_data.next_followup_at:
        clue.next_followup_at = followup_data.next_followup_at
    
    _update_overdue_for_clue(clue)
    
    db.commit()
    db.refresh(record)
    
    return record


def _update_overdue_for_clue(clue: Clue):
    if clue.next_followup_at and clue.next_followup_at < datetime.utcnow():
        clue.is_overdue = True
    else:
        clue.is_overdue = False


def _check_overdue_internal(session_factory):
    db = session_factory()
    try:
        now = datetime.utcnow()
        clues = db.query(Clue).filter(
            Clue.status == "active",
            Clue.next_followup_at.isnot(None),
            Clue.next_followup_at < now
        ).all()
        for clue in clues:
            clue.is_overdue = True
        db.commit()
    finally:
        db.close()


@app.post("/api/clues/check-overdue")
def check_overdue(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    clues = db.query(Clue).filter(
        Clue.status == "active",
        Clue.next_followup_at.isnot(None),
        Clue.next_followup_at < now
    ).all()
    count = 0
    for clue in clues:
        if not clue.is_overdue:
            clue.is_overdue = True
            count += 1
    db.commit()
    return {"updated": count, "total_overdue": len(clues)}


@app.get("/api/clues/overdue/list", response_model=List[ClueResponse])
def list_overdue_clues(db: Session = Depends(get_db)):
    clues = db.query(Clue).filter(
        Clue.is_overdue == True,
        Clue.status == "active"
    ).order_by(Clue.next_followup_at).all()
    
    result = []
    for clue in clues:
        clue_dict = clue.__dict__.copy()
        clue_dict['assignee_name'] = clue.assignee.name if clue.assignee else None
        result.append(clue_dict)
    
    return result


@app.get("/api/kanban")
def get_kanban(
    stage: Optional[str] = None,
    assignee_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    now = datetime.utcnow()
    
    query = db.query(Clue).filter(Clue.status == "active")
    if stage:
        query = query.filter(Clue.stage == stage)
    if assignee_id:
        query = query.filter(Clue.assignee_id == assignee_id)
    
    clues = query.order_by(desc(Clue.created_at)).all()
    
    by_stage = {}
    stages = ["new", "contacted", "qualified", "negotiating", "won", "lost"]
    for s in stages:
        by_stage[s] = []
    
    total = len(clues)
    overdue_count = 0
    today_new = 0
    today_followup = 0
    
    today_start = date.today()
    today_datetime = datetime.combine(today_start, datetime.min.time())
    
    for clue in clues:
        if clue.is_overdue:
            overdue_count += 1
        if clue.created_at >= today_datetime:
            today_new += 1
        if clue.last_followup_at and clue.last_followup_at >= today_datetime:
            today_followup += 1
        
        clue_dict = clue.__dict__.copy()
        clue_dict['assignee_name'] = clue.assignee.name if clue.assignee else None
        
        stage_key = clue.stage if clue.stage in by_stage else "new"
        by_stage[stage_key].append(clue_dict)
    
    return {
        "total": total,
        "overdue_count": overdue_count,
        "today_new": today_new,
        "today_followup": today_followup,
        "by_stage": by_stage
    }


@app.get("/api/reports/daily", response_model=DailyReportResponse)
def daily_report(
    date_str: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_db)
):
    if date_str:
        report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        report_date = date.today()
    
    start_of_day = datetime.combine(report_date, datetime.min.time())
    end_of_day = datetime.combine(report_date + timedelta(days=1), datetime.min.time())
    
    all_clues = db.query(Clue).filter(Clue.status == "active").all()
    
    new_clues = [c for c in all_clues if start_of_day <= c.created_at < end_of_day]
    followed_up = [c for c in all_clues if c.last_followup_at and start_of_day <= c.last_followup_at < end_of_day]
    overdue_clues = [c for c in all_clues if c.is_overdue]
    
    by_stage = {}
    stages = ["new", "contacted", "qualified", "negotiating", "won", "lost"]
    for s in stages:
        by_stage[s] = len([c for c in all_clues if c.stage == s])
    
    by_user = {}
    for clue in all_clues:
        name = clue.assignee.name if clue.assignee else "待分派"
        if name not in by_user:
            by_user[name] = {"total": 0, "followed": 0, "overdue": 0}
        by_user[name]["total"] += 1
        if clue.last_followup_at and start_of_day <= clue.last_followup_at < end_of_day:
            by_user[name]["followed"] += 1
        if clue.is_overdue:
            by_user[name]["overdue"] += 1
    
    result_clues = []
    for clue in all_clues:
        clue_dict = clue.__dict__.copy()
        clue_dict['assignee_name'] = clue.assignee.name if clue.assignee else None
        result_clues.append(clue_dict)
    
    return {
        "date": report_date.isoformat(),
        "total_clues": len(all_clues),
        "new_clues": len(new_clues),
        "followed_up": len(followed_up),
        "overdue_clues": len(overdue_clues),
        "by_stage": by_stage,
        "by_user": by_user,
        "clues": result_clues
    }


@app.get("/api/reports/daily/export")
def export_daily_report(
    date_str: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_db)
):
    if date_str:
        report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        report_date = date.today()
    
    report = daily_report(date_str=report_date.isoformat(), db=db)
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow([f"线索管理日报 - {report['date']}"])
    writer.writerow([])
    writer.writerow(["统计摘要"])
    writer.writerow(["总线索数", report["total_clues"]])
    writer.writerow(["今日新增", report["new_clues"]])
    writer.writerow(["今日跟进", report["followed_up"]])
    writer.writerow(["逾期未跟进", report["overdue_clues"]])
    writer.writerow([])
    
    writer.writerow(["按阶段统计"])
    stage_labels = {"new": "新建", "contacted": "已联系", "qualified": "已确认意向", 
                    "negotiating": "商务洽谈", "won": "已成交", "lost": "已流失"}
    for stage_key, count in report["by_stage"].items():
        writer.writerow([stage_labels.get(stage_key, stage_key), count])
    writer.writerow([])
    
    writer.writerow(["按负责人统计"])
    writer.writerow(["负责人", "线索总数", "今日跟进", "逾期数"])
    for name, stats in report["by_user"].items():
        writer.writerow([name, stats["total"], stats["followed"], stats["overdue"]])
    writer.writerow([])
    
    writer.writerow(["线索明细"])
    writer.writerow(["ID", "标题", "客户", "来源", "地区", "优先级", "阶段", 
                     "负责人", "创建时间", "最后跟进时间", "下次跟进时间", "是否逾期"])
    for clue in report["clues"]:
        writer.writerow([
            clue["id"],
            clue["title"],
            clue.get("customer_name", ""),
            clue.get("source", ""),
            clue.get("region", ""),
            clue.get("priority", ""),
            stage_labels.get(clue.get("stage", ""), clue.get("stage", "")),
            clue.get("assignee_name", "待分派"),
            clue.get("created_at", ""),
            clue.get("last_followup_at", ""),
            clue.get("next_followup_at", ""),
            "是" if clue.get("is_overdue") else "否"
        ])
    
    output.seek(0)
    filename = f"daily_report_{report_date.isoformat()}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
