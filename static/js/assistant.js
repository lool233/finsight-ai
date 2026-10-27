/* =====================================================================
   AI 智能助手页面脚本（NL2SQL + RAG + 多工具 Agent）
   展示：答复、数据表、制度依据（带出处与相关度得分）、Agent 执行轨迹
   ===================================================================== */
(function () {
    'use strict';

    const body = document.getElementById('chat-body');

    function scrollBottom() { body.scrollTop = body.scrollHeight; }

    /* ---------------------- 轻量 Markdown 渲染 ---------------------- */
    function mdLite(text) {
        if (!text) { return ''; }
        let html = UI.esc(text).replace(/\r\n/g, '\n');

        // 表格：连续以 | 开头的行
        html = html.replace(/(?:^\|.*\|\s*$\n?){2,}/gm, function (block) {
            const lines = block.trim().split('\n').map(function (l) { return l.trim(); });
            const rows = lines.filter(function (l) { return !/^\|[\s:|-]+\|$/.test(l); });
            if (!rows.length) { return block; }
            let out = '<table class="mini-table"><tbody>';
            rows.forEach(function (line, idx) {
                const cells = line.replace(/^\|/, '').replace(/\|$/, '').split('|');
                out += '<tr>' + cells.map(function (cell) {
                    const tag = idx === 0 ? 'th' : 'td';
                    return '<' + tag + '>' + cell.trim() + '</' + tag + '>';
                }).join('') + '</tr>';
            });
            return out + '</tbody></table>';
        });

        // 标题
        html = html.replace(/^###\s+(.*)$/gm, '<div class="md-h3">$1</div>');
        html = html.replace(/^##\s+(.*)$/gm, '<div class="md-h2">$1</div>');
        // 加粗与行内代码
        html = html.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        // 无序列表
        html = html.replace(/(?:^[-·]\s+.*$\n?){2,}/gm, function (block) {
            const items = block.trim().split('\n').map(function (l) {
                return '<li>' + l.replace(/^[-·]\s+/, '') + '</li>';
            }).join('');
            return '<ul style="margin:6px 0 6px 18px;padding:0">' + items + '</ul>';
        });
        // 段落
        return html.split(/\n{2,}/).map(function (part) {
            const trimmed = part.trim();
            if (!trimmed) { return ''; }
            if (/^<(table|ul|div|p)/.test(trimmed)) { return trimmed; }
            return '<p style="margin:6px 0">' + trimmed.replace(/\n/g, '<br>') + '</p>';
        }).join('');
    }

    /* ---------------------- 消息渲染 ---------------------- */
    function appendUser(text) {
        const el = document.createElement('div');
        el.className = 'msg user';
        el.innerHTML = '<div class="who">我</div><div class="bubble">' + UI.esc(text) + '</div>';
        body.appendChild(el);
        scrollBottom();
    }

    function appendLoading() {
        const el = document.createElement('div');
        el.className = 'msg ai';
        el.id = 'msg-loading';
        el.innerHTML = '<div class="who">AI</div><div class="bubble">'
            + '正在规划工具并检索数据…<br><span class="text-sub" style="font-size:12px">'
            + '（可能需要 3～8 秒：意图识别 → 数据/制度检索 → 综合作答）</span></div>';
        body.appendChild(el);
        scrollBottom();
        return el;
    }

    function renderDataTable(data) {
        if (!data || !data.columns || !data.columns.length || !data.rows || !data.rows.length) { return ''; }
        let html = '<div style="overflow-x:auto"><table class="mini-table"><thead><tr>';
        data.columns.forEach(function (c) { html += '<th>' + UI.esc(c.label) + '</th>'; });
        html += '</tr></thead><tbody>';
        data.rows.slice(0, 30).forEach(function (row) {
            html += '<tr>';
            data.columns.forEach(function (c) {
                const v = row[c.key];
                html += '<td>' + UI.esc(v === null || v === undefined ? '' : v) + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        if (data.rows.length > 30) {
            html += '<div class="text-sub" style="font-size:11.5px;margin-top:4px">仅展示前 30 行，共 '
                + data.rows.length + ' 行</div>';
        }
        return html;
    }

    function renderEvidence(evidence) {
        if (!evidence || !evidence.length) { return ''; }
        let html = '<div class="md-h3" style="margin-top:12px">📚 制度依据（RAG 检索结果，'
            + evidence.length + ' 条）</div>';
        evidence.forEach(function (item, idx) {
            html += '<div class="evidence-card">'
                + '<div class="evidence-head">'
                + '<b>【' + (idx + 1) + '】《' + UI.esc(item.doc_title) + '》</b>'
                + '<span class="tag blue">' + UI.esc(item.heading) + '</span>'
                + '<span class="tag ' + (item.score > 0.5 ? 'green' : 'orange') + '">相关度 '
                + item.score + '</span>'
                + '<span class="text-sub" style="font-size:11px">BM25 ' + item.bm25
                + ' / 余弦 ' + item.cosine + '</span>'
                + '</div>'
                + '<div class="evidence-body">' + mdLite(item.content) + '</div>'
                + '</div>';
        });
        return html;
    }

    function renderTrace(trace, method) {
        if (!trace || !trace.length) { return ''; }
        let html = '<details class="fold"><summary>🧭 Agent 执行轨迹（' + trace.length
            + ' 步 · ' + UI.esc(method || '') + '）</summary>';
        trace.forEach(function (step) {
            html += '<div class="trace-step">'
                + '<span class="tag purple">第 ' + step.step + ' 步</span> '
                + '<b>' + UI.esc(step.action_label) + '</b>'
                + ' <code style="font-size:11px">' + UI.esc(step.action) + '</code>'
                + ' <span class="text-sub" style="font-size:11px">' + step.elapsed_ms + ' ms</span>'
                + '<div class="text-sub" style="font-size:11.5px;margin:3px 0">入参：'
                + UI.esc(JSON.stringify(step.args)) + '</div>'
                + '<div style="font-size:12px">' + UI.esc(step.brief) + '…</div>'
                + '</div>';
        });
        return html + '</details>';
    }

    function appendAnswer(result) {
        const el = document.createElement('div');
        el.className = 'msg ai';

        const answer = result.answer || '';
        const answerHtml = mdLite(answer);
        const hasMdTable = answer.indexOf('|---') >= 0;
        let html = '<div class="who">AI</div><div class="bubble">';
        html += '<div>' + answerHtml + '</div>';
        if (!hasMdTable) {
            if (result.title) {
                html += '<div style="margin-top:8px;font-weight:600">' + UI.esc(result.title) + '</div>';
            }
            html += renderDataTable(result.data);
        }
        html += renderEvidence(result.evidence);

        html += '<div class="meta">';
        if (result.route_name) {
            const routeCls = { statistics: 'blue', policy: 'cyan', mixed: 'purple', other: 'gray' };
            html += '<span class="tag ' + (routeCls[result.route] || 'gray') + '">'
                + UI.esc(result.route_name) + '</span>';
        }
        html += '<span class="tag ' + (result.is_statistics_query ? 'green' : 'gray') + '">意图：'
            + UI.esc(result.intent_name) + '</span>'
            + '<span class="tag blue">规划：' + UI.esc(result.method || '-') + '</span>'
            + '<span class="tag ' + (result.answer_source === 'LLM' ? 'purple' : 'gray') + '">答复：'
            + UI.esc(result.answer_source) + '</span>'
            + '<span class="text-sub">耗时 ' + result.elapsed_ms + ' ms</span>';
        if (result.slots && Object.keys(result.slots).length) {
            html += '<span class="text-sub">识别条件：' + UI.esc(JSON.stringify(result.slots)) + '</span>';
        }
        html += '</div>';

        html += renderTrace(result.trace, result.method);
        if (result.sql) {
            html += '<details class="fold"><summary>查看白名单参数化 SQL</summary>'
                + '<div class="sql-box">' + UI.esc(result.sql) + '</div></details>';
        }
        html += '</div>';

        el.innerHTML = html;
        body.appendChild(el);
        scrollBottom();
    }

    /* ---------------------- 提问 ---------------------- */
    async function ask(text) {
        const input = document.getElementById('question');
        const question = (text || input.value || '').trim();
        if (!question) { Toast.err('请输入您的问题'); return; }
        const btn = document.getElementById('btn-ask');
        btn.disabled = true;
        appendUser(question);
        if (!text) { input.value = ''; }
        const loading = appendLoading();
        try {
            const result = await API.post('/api/assistant/ask', { question: question });
            loading.remove();
            appendAnswer(result);
        } catch (e) {
            loading.remove();
            const el = document.createElement('div');
            el.className = 'msg ai';
            el.innerHTML = '<div class="who">AI</div><div class="bubble">处理失败：' + UI.esc(e.message) + '</div>';
            body.appendChild(el);
            scrollBottom();
        } finally {
            btn.disabled = false;
        }
    }

    document.getElementById('btn-ask').addEventListener('click', function () { ask(); });
    document.getElementById('question').addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
    });

    /* ---------------------- 初始化 ---------------------- */
    (async function init() {
        try {
            const data = await API.get('/api/assistant/samples');
            const kb = data.knowledge || {};
            document.getElementById('llm-mode').textContent = '当前模式：' + data.llm.mode
                + '（' + data.llm.model + '）· 工具 ' + (data.tools || []).length + ' 个'
                + ' · 制度知识库 ' + (kb.docs || []).length + ' 份 / ' + (kb.chunks || 0)
                + ' 个知识块 · 检索 Top' + (kb.top_k || 4) + (kb.rerank ? ' + LLM 重排' : '');

            const box = document.getElementById('samples');
            const groups = [
                { title: '统计查询', items: data.samples || [] },
                { title: '制度问答', items: data.policy_samples || [] }
            ];
            groups.forEach(function (group) {
                const label = document.createElement('span');
                label.className = 'text-sub';
                label.style.cssText = 'font-size:11.5px;align-self:center;margin-right:2px';
                label.textContent = group.title + '：';
                box.appendChild(label);
                group.items.forEach(function (q) {
                    const chip = document.createElement('span');
                    chip.className = 'sample-chip';
                    chip.textContent = q;
                    chip.addEventListener('click', function () { ask(q); });
                    box.appendChild(chip);
                });
            });

            const welcome = document.createElement('div');
            welcome.className = 'msg ai';
            welcome.innerHTML = '<div class="who">AI</div><div class="bubble">'
                + '<b>您好，我是智析 FinSight AI 的智能助手。</b><br><br>'
                + '我采用「<b>多工具 Agent</b>」工作方式：先判断您的问题需要哪些工具，'
                + '再依次执行，最后把结果组织成答复。<br><br>'
                + '<b>我可以调用三类工具：</b><br>'
                + '1. <b>数据统计</b> —— 借资总额、未还、逾期、部门/类型/趋势、欠款排名、个人台账<br>'
                + '2. <b>制度检索</b> —— 从公司财务制度知识库检索条款并标注出处（RAG）<br>'
                + '3. <b>人员台账</b> —— 指定销售人员的借资明细、还款流水与催还次数<br><br>'
                + '<b>试试这种混合问题：</b>「许曼逾期229天，按制度该怎么处理？」'
                + '我会先查制度条款、再查她的实际台账，然后给出结论与依据。<br><br>'
                + '<span class="text-sub">当前模式：' + UI.esc(data.llm.mode) + '；'
                + (data.llm.enabled ? '真实大模型已接入' : '未配置密钥，使用内置规则引擎')
                + '</span></div>';
            body.appendChild(welcome);
            scrollBottom();
        } catch (e) {
            Toast.err('初始化失败：' + e.message);
        }
    })();
})();
