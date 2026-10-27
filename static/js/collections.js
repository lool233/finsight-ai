/* =====================================================================
   催还管理页面脚本：逾期扫描、LLM 生成催还记录、短信下发与重发
   ===================================================================== */
(function () {
    'use strict';

    const state = { page: 1, size: 10, selected: {}, canWrite: false, overdue: [] };

    function overdueFilters() {
        return {
            months: document.getElementById('f-months').value,
            dept: document.getElementById('f-dept').value,
            level: document.getElementById('f-level').value,
            keyword: document.getElementById('f-keyword').value.trim()
        };
    }

    async function loadStatus() {
        const st = await API.get('/api/collections/status');
        const llm = st.llm, sms = st.sms;
        const llmCls = llm.enabled ? 'green' : 'amber';
        const smsCls = sms.available ? 'green' : 'amber';
        document.getElementById('engine-status').innerHTML =
            '<b>运行配置：</b>　'
            + '<span class="tag ' + llmCls + '">LLM：' + UI.esc(llm.mode) + '</span>　'
            + '模型 <b>' + UI.esc(llm.model) + '</b>（' + UI.esc(llm.base_url) + '）　'
            + '<span class="tag ' + smsCls + '">短信：' + UI.esc(sms.description) + '</span><br>'
            + '<b>催还分级规则：</b>' + UI.esc(st.level_rules['一级']) + '；'
            + UI.esc(st.level_rules['二级']) + '；' + UI.esc(st.level_rules['三级'])
            + '。同一笔借资同级催还间隔 ' + st.dedupe_days + ' 天内不会重复生成（可勾选“强制重新催还”）。'
            + (llm.enabled ? '' : '<br><span class="text-sub">提示：在工程代码目录的 .env 中配置 '
                + 'LLM_API_KEY 后重启服务，即可调用真实大模型生成催还内容与智能答复。</span>');
        if (!llm.enabled && llm.fallback) {
            document.getElementById('engine-status').classList.remove('blue');
            document.getElementById('engine-status').classList.add('amber');
        }
    }

    function renderOverdue(data) {
        state.overdue = data.items;
        state.selected = {};
        document.getElementById('ov-count').textContent = data.total + ' 笔';
        document.getElementById('ov-amount').textContent = UI.money(data.amount);
        document.getElementById('ov-level').textContent =
            (data.level_stat['一级'] || 0) + ' / ' + (data.level_stat['二级'] || 0) + ' / ' + (data.level_stat['三级'] || 0);
        document.getElementById('tab-hint').textContent =
            '逾期借资 ' + data.total + ' 笔，涉及未还金额 ' + UI.money(data.amount) + ' 元';

        UI.renderTable('#table-overdue', [
            {
                key: 'sel', labelHtml: '<input type="checkbox" id="check-all" title="全选">',
                render: function (r) {
                    return '<input type="checkbox" class="row-check" data-id="' + r.loan_id + '">';
                }
            },
            { key: 'sales_name', label: '借款人' },
            { key: 'emp_no', label: '工号' },
            { key: 'dept', label: '部门' },
            { key: 'phone', label: '手机号' },
            { key: 'loan_no', label: '借资单号' },
            { key: 'amount', label: '借资金额', align: 'right', render: function (r) { return UI.money(r.amount); } },
            {
                key: 'unpaid_amount', label: '未还金额', align: 'right',
                render: function (r) { return '<b style="color:#dc2626">' + UI.money(r.unpaid_amount) + '</b>'; }
            },
            { key: 'loan_date', label: '借资日期', render: function (r) { return UI.dateOnly(r.loan_date); } },
            { key: 'repay_deadline', label: '约定还款日', render: function (r) { return UI.dateOnly(r.repay_deadline); } },
            { key: 'overdue_days', label: '逾期天数', align: 'right' },
            { key: 'collection_level', label: '催还级别', render: function (r) { return UI.levelTag(r.collection_level); } },
            {
                key: 'last_collection', label: '最近催还', render: function (r) {
                    if (!r.last_collection) { return '<span class="text-sub">未催还</span>'; }
                    return UI.sendTag(r.last_collection.send_status) + '<br><span class="text-sub" style="font-size:11px">'
                        + UI.esc(String(r.last_collection.created_at).slice(0, 16)) + '</span>';
                }
            },
            {
                key: 'op', label: '操作', render: function (r) {
                    return '<button class="btn sm ghost" data-act="preview" data-id="' + r.loan_id + '">预览</button>'
                        + '<button class="btn sm primary" data-act="run" data-id="' + r.loan_id + '">催还</button>';
                }
            }
        ], data.items, { empty: '当前没有逾期借资，台账状态良好' });

        const all = document.getElementById('check-all');
        if (all) {
            all.addEventListener('change', function () {
                document.querySelectorAll('.row-check').forEach(function (c) { c.checked = all.checked; });
                syncSelected();
            });
        }
        document.querySelectorAll('.row-check').forEach(function (c) {
            c.addEventListener('change', syncSelected);
        });
        syncSelected();
    }

    function syncSelected() {
        const ids = [];
        document.querySelectorAll('.row-check').forEach(function (c) { if (c.checked) { ids.push(Number(c.dataset.id)); } });
        state.selected = ids;
        const btn = document.getElementById('btn-run-selected');
        btn.disabled = !ids.length;
        btn.textContent = ids.length ? ('仅催还选中项（' + ids.length + '）') : '仅催还选中项';
    }

    async function scan() {
        let data;
        try { data = await API.get('/api/collections/overdue', overdueFilters()); }
        catch (e) { Toast.err('扫描失败：' + e.message); return; }
        renderOverdue(data);
        Toast.ok('扫描完成：发现 ' + data.total + ' 笔逾期借资');
    }

    async function runBatch(loanIds) {
        const payload = Object.assign(overdueFilters(), {
            force: document.getElementById('f-force').checked,
            channel: '短信'
        });
        if (loanIds && loanIds.length) { payload.loan_ids = loanIds; }
        try {
            const result = await API.post('/api/collections/run', payload);
            showResult(result);
            await scan();
            loadRecords(1);
            loadHistoryCount();
        } catch (e) { Toast.err(e.message); }
    }

    function showResult(result) {
        let html = '<div class="notice green">批次号 <b>' + UI.esc(result.batch_no) + '</b>　扫描 '
            + result.scanned + ' 笔，生成催还记录 <b>' + result.created + '</b> 条，下发成功 '
            + result.sent_ok + ' 条' + (result.sent_fail ? '，未成功 <b>' + result.sent_fail + '</b> 条' : '')
            + (result.skipped ? '，跳过重复 ' + result.skipped + ' 条' : '') + '</div>';
        html += '<div class="notice blue">内容来源：<b>' + UI.esc(result.llm.mode) + '</b>（模型 '
            + UI.esc(result.llm.model) + '）　短信通道：' + UI.esc(result.sms_provider.description) + '</div>';
        if (result.items && result.items.length) {
            html += '<table class="mini-table"><thead><tr><th>借款人</th><th>手机号</th><th>逾期天数</th>'
                + '<th>逾期金额</th><th>级别</th><th>内容来源</th><th>发送状态</th><th>催还短信内容</th></tr></thead><tbody>';
            result.items.forEach(function (it) {
                html += '<tr><td>' + UI.esc(it.sales_name) + '</td><td>' + UI.esc(it.phone) + '</td><td>'
                    + it.overdue_days + '</td><td>' + UI.money(it.overdue_amount) + '</td><td>'
                    + UI.levelTag(it.collection_level) + '</td><td>' + UI.esc(it.generated_by) + '</td><td>'
                    + UI.sendTag(it.send_status) + '</td><td style="white-space:normal;max-width:380px">'
                    + UI.esc(it.content) + '</td></tr>';
            });
            html += '</tbody></table>';
        } else {
            html += '<div class="empty-tip">本次没有生成新的催还记录</div>';
        }
        if (result.skipped_items && result.skipped_items.length) {
            html += '<details class="fold"><summary>查看跳过的 ' + result.skipped_items.length + ' 条记录</summary>';
            result.skipped_items.forEach(function (s) {
                html += '<div>· ' + UI.esc(s.sales_name) + ' / ' + UI.esc(s.loan_no) + '：' + UI.esc(s.reason) + '</div>';
            });
            html += '</details>';
        }
        document.getElementById('result-body').innerHTML = html;
        UI.openModal('modal-result');
    }

    async function loadRecords(page) {
        state.page = page || 1;
        let data;
        try {
            data = await API.get('/api/collections', {
                page: state.page, size: state.size,
                send_status: document.getElementById('c-status').value,
                start_date: document.getElementById('c-start').value,
                end_date: document.getElementById('c-end').value
            });
        } catch (e) { Toast.err('催还记录加载失败：' + e.message); return; }

        UI.renderTable('#table-records', [
            { key: 'batch_no', label: '批次号' },
            { key: 'created_at', label: '生成时间', render: function (r) { return UI.esc(String(r.created_at).slice(0, 19)); } },
            { key: 'sales_name', label: '催还对象' },
            { key: 'phone', label: '手机号' },
            { key: 'loan_no', label: '借资单号' },
            { key: 'overdue_days', label: '逾期天数', align: 'right' },
            { key: 'overdue_amount', label: '逾期金额', align: 'right', render: function (r) { return UI.money(r.overdue_amount); } },
            { key: 'collection_level', label: '级别', render: function (r) { return UI.levelTag(r.collection_level); } },
            { key: 'channel', label: '渠道' },
            { key: 'generated_by', label: '内容来源', render: function (r) { return UI.esc(r.generated_by); } },
            { key: 'send_status', label: '发送状态', render: function (r) { return UI.sendTag(r.send_status); } },
            {
                key: 'content', label: '催还短信内容', wrap: true,
                render: function (r) { return UI.esc(r.content); }
            },
            {
                key: 'op', label: '操作', render: function (r) {
                    return '<button class="btn sm ghost" data-act="resend" data-id="' + r.id + '">重发</button>'
                        + '<button class="btn sm ghost" style="color:#dc2626" data-act="del" data-id="' + r.id + '">删除</button>';
                }
            }
        ], data.items, { empty: '暂无催还记录，请先执行催还批处理' });
        UI.renderPager('#pager-records', data, loadRecords);
        document.getElementById('ov-history').textContent = (data.stat.total || 0) + ' 条';
    }

    async function loadHistoryCount() {
        try {
            const data = await API.get('/api/collections', { page: 1, size: 1 });
            document.getElementById('ov-history').textContent = (data.stat.total || 0) + ' 条';
        } catch (e) { /* 忽略 */ }
    }

    /* -------------------------- 事件 -------------------------- */
    document.getElementById('btn-scan').addEventListener('click', scan);
    document.getElementById('btn-run-all').addEventListener('click', function () {
        if (!confirm('将对当前筛选范围内所有逾期借资调用 LLM 生成催还记录并下发短信，是否继续？')) { return; }
        runBatch(null);
    });
    document.getElementById('btn-run-selected').addEventListener('click', function () {
        if (!state.selected.length) { return; }
        runBatch(state.selected);
    });
    document.getElementById('tab-overdue').addEventListener('click', function () {
        document.getElementById('panel-overdue').style.display = 'block';
        document.getElementById('panel-records').style.display = 'none';
        this.classList.add('primary');
        document.getElementById('tab-records').classList.remove('primary');
    });
    document.getElementById('tab-records').addEventListener('click', function () {
        document.getElementById('panel-overdue').style.display = 'none';
        document.getElementById('panel-records').style.display = 'block';
        this.classList.add('primary');
        document.getElementById('tab-overdue').classList.remove('primary');
        loadRecords(1);
    });
    document.getElementById('btn-search-records').addEventListener('click', function () { loadRecords(1); });
    document.getElementById('btn-export-records').addEventListener('click', async function () {
        try {
            const data = await API.get('/api/collections', {
                page: 1, size: 200,
                send_status: document.getElementById('c-status').value,
                start_date: document.getElementById('c-start').value,
                end_date: document.getElementById('c-end').value
            });
            const head = ['批次号', '生成时间', '催还对象', '手机号', '借资单号', '逾期天数', '逾期金额',
                '级别', '渠道', '内容来源', '发送状态', '催还短信内容'];
            const lines = [head.join(',')];
            data.items.forEach(function (r) {
                lines.push([r.batch_no, r.created_at, r.sales_name, r.phone, r.loan_no, r.overdue_days,
                    r.overdue_amount, r.collection_level, r.channel, r.generated_by, r.send_status,
                    '"' + String(r.content || '').replace(/"/g, '""') + '"'].join(','));
            });
            const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = '催还记录_' + UI.todayStr() + '.csv';
            a.click();
            Toast.ok('已导出 ' + data.items.length + ' 条催还记录');
        } catch (e) { Toast.err(e.message); }
    });

    document.getElementById('table-overdue').addEventListener('click', async function (e) {
        const btn = e.target.closest('button[data-act]');
        if (!btn) { return; }
        const id = btn.dataset.id;
        if (btn.dataset.act === 'run') { runBatch([Number(id)]); return; }
        if (btn.dataset.act === 'preview') {
            try {
                const data = await API.post('/api/collections/preview/' + id, {});
                alert('【' + data.loan.sales_name + '】逾期 ' + data.loan.overdue_days + ' 天（' + data.level + '催还）\n'
                    + '内容来源：' + data.generated_by + (data.model ? ' / ' + data.model : '') + '\n\n'
                    + data.content + '\n\n—— 风险分析 ——\n' + data.analysis + '\n\n—— 处理建议 ——\n' + data.suggestion
                    + (data.notice ? '\n\n提示：' + data.notice : ''));
            } catch (err) { Toast.err(err.message); }
        }
    });

    document.getElementById('table-records').addEventListener('click', async function (e) {
        const btn = e.target.closest('button[data-act]');
        if (!btn) { return; }
        const id = btn.dataset.id;
        if (btn.dataset.act === 'resend') {
            try {
                const r = await API.post('/api/collections/' + id + '/resend', {});
                Toast.ok('重发结果：' + r.send_status + '（' + r.detail + '）');
                loadRecords(state.page);
            } catch (err) { Toast.err(err.message); }
        } else if (btn.dataset.act === 'del') {
            if (!confirm('确认删除该条催还记录？')) { return; }
            try { await API.del('/api/collections/' + id); Toast.ok('已删除'); loadRecords(state.page); }
            catch (err) { Toast.err(err.message); }
        }
    });

    (async function init() {
        try {
            await loadStatus();
            const opt = await API.get('/api/sales/options');
            const sel = document.getElementById('f-dept');
            opt.depts.forEach(function (d) { sel.insertAdjacentHTML('beforeend', '<option>' + UI.esc(d) + '</option>'); });
            await scan();
            await loadHistoryCount();
        } catch (e) { Toast.err('初始化失败：' + e.message); }
    })();
})();
