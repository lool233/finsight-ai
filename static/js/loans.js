/* =====================================================================
   借资管理页面脚本：增删改查、还款登记、单笔催还
   ===================================================================== */
(function () {
    'use strict';

    const state = { page: 1, size: 10, canWrite: false, meta: {}, current: null, previewLoanId: null };
    const LAST_PAGE_KEY = 'loans_last_filters';

    function filters() {
        return {
            keyword: document.getElementById('f-keyword').value.trim(),
            dept: document.getElementById('f-dept').value,
            loan_type: document.getElementById('f-type').value,
            status: document.getElementById('f-status').value,
            start_date: document.getElementById('f-start').value,
            end_date: document.getElementById('f-end').value,
            min_amount: document.getElementById('f-min').value,
            max_amount: document.getElementById('f-max').value,
            overdue_only: document.getElementById('f-overdue').checked ? 1 : ''
        };
    }

    function persistFilters() {
        try { sessionStorage.setItem(LAST_PAGE_KEY, JSON.stringify(filters())); } catch (e) { /* 忽略 */ }
    }

    function restoreFilters() {
        const url = new URLSearchParams(location.search);
        let saved = {};
        try { saved = JSON.parse(sessionStorage.getItem(LAST_PAGE_KEY) || '{}'); } catch (e) { saved = {}; }
        const data = Object.assign({}, saved, {
            keyword: url.get('keyword') !== null ? url.get('keyword') : saved.keyword
        });
        ['keyword', 'dept', 'loan_type', 'status', 'start_date', 'end_date', 'min_amount', 'max_amount']
            .forEach(function (key) {
                const map = {
                    keyword: 'f-keyword', dept: 'f-dept', loan_type: 'f-type', status: 'f-status',
                    start_date: 'f-start', end_date: 'f-end', min_amount: 'f-min', max_amount: 'f-max'
                };
                const el = document.getElementById(map[key]);
                if (el && data[key]) { el.value = data[key]; }
            });
        if (data.overdue_only) { document.getElementById('f-overdue').checked = true; }
    }

    async function loadMeta() {
        state.meta = await API.get('/api/loans/meta');
        state.canWrite = !!state.meta.can_write;

        const deptSel = document.getElementById('f-dept');
        state.meta.depts.forEach(function (d) {
            deptSel.insertAdjacentHTML('beforeend', '<option>' + UI.esc(d) + '</option>');
        });
        const typeSel = document.getElementById('f-type');
        state.meta.loan_types.forEach(function (t) {
            typeSel.insertAdjacentHTML('beforeend', '<option>' + UI.esc(t) + '</option>');
        });
        const statusSel = document.getElementById('f-status');
        state.meta.status_list.forEach(function (s) {
            statusSel.insertAdjacentHTML('beforeend', '<option>' + UI.esc(s) + '</option>');
        });
        const formType = document.getElementById('sel-type');
        state.meta.loan_types.forEach(function (t) {
            formType.insertAdjacentHTML('beforeend', '<option>' + UI.esc(t) + '</option>');
        });
        const formStatus = document.getElementById('sel-status');
        state.meta.status_list.forEach(function (s) {
            formStatus.insertAdjacentHTML('beforeend', '<option>' + UI.esc(s) + '</option>');
        });

        const sales = await API.get('/api/sales', { page: 1, size: 200, status: '在职' });
        const sel = document.getElementById('sel-sales');
        sel.innerHTML = '<option value="">请选择销售人员</option>';
        sales.items.forEach(function (s) {
            sel.insertAdjacentHTML('beforeend', '<option value="' + s.id + '">' + UI.esc(s.name)
                + '（' + UI.esc(s.emp_no) + ' / ' + UI.esc(s.dept) + '）</option>');
        });

        if (!state.canWrite) {
            document.getElementById('btn-add').disabled = true;
            document.getElementById('btn-add').title = '当前角色无维护权限';
        }
    }

    async function loadList(page) {
        state.page = page || 1;
        persistFilters();
        let data;
        try {
            data = await API.get('/api/loans', Object.assign(filters(), {
                page: state.page, size: state.size
            }));
        } catch (e) {
            Toast.err('借资列表加载失败：' + e.message);
            return;
        }

        document.getElementById('sum-total').textContent = UI.money(data.summary.total_amount);
        document.getElementById('sum-repaid').textContent = UI.money(data.summary.repaid_amount);
        document.getElementById('sum-unpaid').textContent = UI.money(data.summary.unpaid_amount);
        document.getElementById('sum-count').textContent = data.total + ' 条';
        document.getElementById('list-hint').textContent =
            '逾期口径：约定还款日已过，或借资日至今超过 ' + (state.meta.overdue_months || 3) + ' 个月';

        const columns = [
            { key: 'loan_no', label: '借资单号' },
            { key: 'sales_name', label: '借款人' },
            { key: 'dept', label: '部门' },
            { key: 'amount', label: '借资金额', align: 'right', render: function (r) { return UI.money(r.amount); } },
            { key: 'repaid_amount', label: '已还', align: 'right', render: function (r) { return UI.money(r.repaid_amount); } },
            {
                key: 'unpaid_amount', label: '未还', align: 'right',
                render: function (r) {
                    const color = Number(r.unpaid_amount) > 0 ? 'color:#dc2626;font-weight:600' : 'color:#16a34a';
                    return '<span style="' + color + '">' + UI.money(r.unpaid_amount) + '</span>';
                }
            },
            { key: 'loan_date', label: '借资日期', render: function (r) { return UI.dateOnly(r.loan_date); } },
            { key: 'repay_deadline', label: '约定还款日', render: function (r) { return UI.dateOnly(r.repay_deadline); } },
            { key: 'status', label: '状态', render: function (r) { return UI.statusTag(r.status); } },
            {
                key: 'overdue_days', label: '逾期天数', align: 'right',
                render: function (r) {
                    if (!r.is_overdue) { return '<span class="text-sub">-</span>'; }
                    const cls = r.overdue_days > 180 ? 'red' : (r.overdue_days > 90 ? 'orange' : 'blue');
                    return '<span class="tag ' + cls + '">' + r.overdue_days + ' 天</span>';
                }
            },
            {
                key: 'op', label: '操作', render: function (r) {
                    let html = '<button class="btn sm ghost" data-act="detail" data-id="' + r.id + '">详情</button>';
                    if (state.canWrite) {
                        html += ' <button class="btn sm ghost" data-act="edit" data-id="' + r.id + '">编辑</button>';
                        if (Number(r.unpaid_amount) > 0) {
                            html += ' <button class="btn sm ghost" data-act="repay" data-id="' + r.id + '">还款</button>';
                        }
                        if (r.is_overdue) {
                            html += ' <button class="btn sm ghost" data-act="collect" data-id="' + r.id + '">催还</button>';
                        }
                        html += ' <button class="btn sm ghost" style="color:#dc2626" data-act="del" data-id="' + r.id + '">删除</button>';
                    }
                    return html;
                }
            }
        ];
        UI.renderTable('#table-loans', columns, data.items, { empty: '没有符合条件的借资记录' });
        UI.renderPager('#pager', data, loadList);
    }

    /* -------------------------- 借资表单 -------------------------- */
    function openCreate() {
        const form = document.getElementById('form-loan');
        form.reset();
        form.querySelector('[name=id]').value = '';
        document.getElementById('loan-modal-title').textContent = '登记借资信息';
        document.getElementById('edit-status-box').style.display = 'none';
        form.querySelector('[name=loan_date]').value = UI.todayStr();
        UI.openModal('modal-loan');
    }

    async function openEdit(id) {
        const data = await API.get('/api/loans/' + id);
        const loan = data.loan;
        const form = document.getElementById('form-loan');
        form.reset();
        UI.fillForm(form, loan);
        form.querySelector('[name=id]').value = loan.id;
        form.querySelector('[name=loan_no]').value = loan.loan_no;
        document.getElementById('loan-modal-title').textContent = '编辑借资信息（' + loan.loan_no + '）';
        document.getElementById('edit-status-box').style.display = 'block';
        UI.openModal('modal-loan');
    }

    async function saveLoan() {
        const form = document.getElementById('form-loan');
        const data = UI.formData(form);
        const id = data.id;
        delete data.id;
        if (!data.sales_id) { Toast.err('请选择销售人员'); return; }
        if (!data.amount || Number(data.amount) <= 0) { Toast.err('请输入正确的借资金额'); return; }
        if (!data.loan_date) { Toast.err('请选择借资日期'); return; }
        try {
            if (id) {
                await API.put('/api/loans/' + id, data);
                Toast.ok('借资信息已更新');
            } else {
                await API.post('/api/loans', data);
                Toast.ok('借资信息登记成功');
            }
            UI.closeModal('modal-loan');
            loadList(state.page);
        } catch (e) { Toast.err(e.message); }
    }

    /* -------------------------- 详情 / 还款 -------------------------- */
    async function openDetail(id) {
        let data;
        try { data = await API.get('/api/loans/' + id); } catch (e) { Toast.err(e.message); return; }
        state.current = data.loan;
        const loan = data.loan;

        let html = '<div class="grid cols-2">'
            + '<div><table class="mini-table">'
            + row('借资单号', UI.esc(loan.loan_no))
            + row('借款人', UI.esc(loan.sales_name) + '（' + UI.esc(loan.emp_no) + '）')
            + row('部门 / 区域', UI.esc(loan.dept) + ' / ' + UI.esc(loan.region || '-'))
            + row('联系电话', UI.esc(loan.phone))
            + row('借资类型', UI.esc(loan.loan_type))
            + row('借资用途', UI.esc(loan.purpose || '-'))
            + '</table></div><div><table class="mini-table">'
            + row('借资金额', UI.money(loan.amount) + ' 元')
            + row('已还金额', UI.money(loan.repaid_amount) + ' 元')
            + row('未还金额', '<b style="color:#dc2626">' + UI.money(loan.unpaid_amount) + '</b> 元')
            + row('借资日期', UI.dateOnly(loan.loan_date))
            + row('约定还款日', UI.dateOnly(loan.repay_deadline))
            + row('当前状态', UI.statusTag(loan.status)
                + (loan.is_overdue ? ' <span class="tag red">逾期 ' + loan.overdue_days + ' 天</span>' : ''))
            + row('登记人 / 时间', UI.esc(loan.created_by || '-') + '<br>' + UI.esc(loan.created_at || ''))
            + '</table></div></div>';

        html += '<div class="card mt12 mb0"><div class="card-head"><h2>还款流水（'
            + data.repayments.length + ' 条）</h2></div><div class="card-body tight">';
        if (data.repayments.length) {
            html += '<table class="mini-table"><thead><tr><th>还款日期</th><th>金额（元）</th>'
                + '<th>方式</th><th>经办人</th><th>备注</th>' + (state.canWrite ? '<th>操作</th>' : '') + '</tr></thead><tbody>';
            data.repayments.forEach(function (r) {
                html += '<tr><td>' + UI.dateOnly(r.repay_date) + '</td><td>' + UI.money(r.repay_amount)
                    + '</td><td>' + UI.esc(r.repay_method) + '</td><td>' + UI.esc(r.operator || '')
                    + '</td><td>' + UI.esc(r.remark || '') + '</td>'
                    + (state.canWrite ? '<td><button class="btn sm ghost" style="color:#dc2626" data-del-repay="'
                        + r.id + '">删除</button></td>' : '') + '</tr>';
            });
            html += '</tbody></table>';
        } else {
            html += '<div class="empty-tip">暂无还款流水</div>';
        }
        html += '</div></div>';

        html += '<div class="card mt12 mb0"><div class="card-head"><h2>催还记录（'
            + data.collections.length + ' 条）</h2></div><div class="card-body tight">';
        if (data.collections.length) {
            html += '<table class="mini-table"><thead><tr><th>生成时间</th><th>级别</th><th>逾期天数</th>'
                + '<th>逾期金额</th><th>来源</th><th>发送状态</th><th>催还短信内容</th></tr></thead><tbody>';
            data.collections.forEach(function (c) {
                html += '<tr><td>' + UI.esc(c.created_at) + '</td><td>' + UI.levelTag(c.collection_level)
                    + '</td><td>' + c.overdue_days + '</td><td>' + UI.money(c.overdue_amount)
                    + '</td><td>' + UI.esc(c.generated_by) + '</td><td>' + UI.sendTag(c.send_status)
                    + '</td><td style="white-space:normal;max-width:360px">' + UI.esc(c.content) + '</td></tr>';
            });
            html += '</tbody></table>';
        } else {
            html += '<div class="empty-tip">该笔借资尚未生成催还记录</div>';
        }
        html += '</div></div>';

        document.getElementById('detail-body').innerHTML = html;
        document.getElementById('btn-repay').style.display =
            (state.canWrite && Number(loan.unpaid_amount) > 0) ? 'inline-flex' : 'none';
        document.querySelectorAll('#detail-body [data-del-repay]').forEach(function (btn) {
            btn.addEventListener('click', async function () {
                if (!confirm('确认删除该条还款流水？删除后将重新计算借资状态。')) { return; }
                try {
                    await API.del('/api/loans/repayments/' + this.dataset.delRepay);
                    Toast.ok('还款流水已删除');
                    openDetail(id);
                    loadList(state.page);
                } catch (e) { Toast.err(e.message); }
            });
        });
        UI.openModal('modal-detail');
    }

    function row(label, value) {
        return '<tr><th style="width:100px;background:#f8fafc">' + label + '</th><td>' + value + '</td></tr>';
    }

    async function openRepay(loanId) {
        let data;
        try { data = await API.get('/api/loans/' + loanId); } catch (e) { Toast.err(e.message); return; }
        state.current = data.loan;
        const form = document.getElementById('form-repay');
        form.reset();
        form.querySelector('[name=loan_id]').value = data.loan.id;
        form.querySelector('[name=repay_amount]').value = Number(data.loan.unpaid_amount).toFixed(2);
        form.querySelector('[name=repay_date]').value = UI.todayStr();
        document.getElementById('repay-info').innerHTML =
            '借资单号 <b>' + UI.esc(data.loan.loan_no) + '</b>　借款人 <b>' + UI.esc(data.loan.sales_name)
            + '</b><br>借资金额 ' + UI.money(data.loan.amount) + ' 元，已还 ' + UI.money(data.loan.repaid_amount)
            + ' 元，<b style="color:#dc2626">未还 ' + UI.money(data.loan.unpaid_amount) + ' 元</b>';
        UI.openModal('modal-repay');
    }

    async function saveRepay() {
        const form = document.getElementById('form-repay');
        const data = UI.formData(form);
        const loanId = data.loan_id;
        delete data.loan_id;
        try {
            await API.post('/api/loans/' + loanId + '/repayments', data);
            Toast.ok('还款登记成功，借资状态已自动更新');
            UI.closeModal('modal-repay');
            loadList(state.page);
            if (document.getElementById('modal-detail').classList.contains('show')) {
                openDetail(loanId);
            }
        } catch (e) { Toast.err(e.message); }
    }

    /* -------------------------- 单笔催还 -------------------------- */
    async function previewCollection(loanId) {
        let data;
        try { data = await API.post('/api/collections/preview/' + loanId, {}); }
        catch (e) { Toast.err(e.message); return; }
        state.previewLoanId = loanId;
        document.getElementById('preview-body').innerHTML =
            '<div class="notice blue">借款人 <b>' + UI.esc(data.loan.sales_name) + '</b>（'
            + UI.esc(data.loan.phone) + '）　逾期 <b>' + data.loan.overdue_days + '</b> 天　催还级别 '
            + UI.levelTag(data.level) + '<br>' + UI.esc(data.level_desc) + '</div>'
            + '<div class="field"><label>催还短信内容（来源：' + UI.esc(data.generated_by)
            + (data.model ? ' / ' + UI.esc(data.model) : '') + '）</label>'
            + '<textarea rows="5" readonly>' + UI.esc(data.content) + '</textarea></div>'
            + '<div class="field"><label>LLM 风险分析</label><div class="notice amber">'
            + UI.esc(data.analysis) + '</div></div>'
            + '<div class="field"><label>处理建议</label><div class="notice green">'
            + UI.esc(data.suggestion) + '</div></div>'
            + (data.notice ? '<div class="notice red">提示：' + UI.esc(data.notice) + '</div>' : '');
        UI.openModal('modal-preview');
    }

    /* -------------------------- 导出 -------------------------- */
    async function exportCsv() {
        try {
            const data = await API.get('/api/loans', Object.assign(filters(), { page: 1, size: 200 }));
            const head = ['借资单号', '借款人', '工号', '部门', '借资金额', '已还金额', '未还金额',
                '借资日期', '约定还款日', '类型', '状态', '逾期天数', '用途'];
            const lines = [head.join(',')];
            data.items.forEach(function (r) {
                lines.push([r.loan_no, r.sales_name, r.emp_no, r.dept, r.amount, r.repaid_amount,
                    r.unpaid_amount, UI.dateOnly(r.loan_date), UI.dateOnly(r.repay_deadline),
                    r.loan_type, r.status, r.overdue_days, (r.purpose || '').replace(/,/g, '，')
                ].join(','));
            });
            const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = '借资台账_' + UI.todayStr() + '.csv';
            a.click();
            Toast.ok('已导出 ' + data.items.length + ' 条记录');
        } catch (e) { Toast.err(e.message); }
    }

    /* -------------------------- 事件绑定 -------------------------- */
    document.getElementById('btn-search').addEventListener('click', function () { loadList(1); });
    document.getElementById('btn-reset').addEventListener('click', function () {
        document.querySelectorAll('.toolbar input, .toolbar select').forEach(function (el) {
            if (el.type === 'checkbox') { el.checked = false; } else if (el.tagName === 'SELECT') { el.value = ''; }
            else { el.value = ''; }
        });
        loadList(1);
    });
    document.getElementById('f-keyword').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { loadList(1); }
    });
    document.getElementById('btn-add').addEventListener('click', openCreate);
    document.getElementById('btn-save-loan').addEventListener('click', saveLoan);
    document.getElementById('btn-save-repay').addEventListener('click', saveRepay);
    document.getElementById('btn-export').addEventListener('click', exportCsv);
    document.getElementById('btn-repay').addEventListener('click', function () {
        if (state.current) { UI.closeModal('modal-detail'); openRepay(state.current.id); }
    });
    document.getElementById('btn-send-preview').addEventListener('click', async function () {
        if (!state.previewLoanId) { return; }
        const btn = this;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading"></span> 处理中…';
        try {
            const result = await API.post('/api/collections/run', {
                loan_ids: [state.previewLoanId], force: true
            });
            const item = (result.items || [])[0];
            if (item) {
                Toast.ok('催还记录已生成，发送状态：' + item.send_status);
                alert('催还短信已生成\n\n发送状态：' + item.send_status + '\n说明：' + item.send_detail);
            } else {
                Toast.info('未生成催还记录（该借资可能已还清）');
            }
            UI.closeModal('modal-preview');
            loadList(state.page);
        } catch (e) {
            Toast.err(e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = '确认生成并发送催还';
        }
    });

    document.getElementById('table-loans').addEventListener('click', async function (e) {
        const btn = e.target.closest('button[data-act]');
        if (!btn) { return; }
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        if (act === 'detail') { openDetail(id); }
        else if (act === 'edit') { openEdit(id); }
        else if (act === 'repay') { openRepay(id); }
        else if (act === 'collect') { previewCollection(id); }
        else if (act === 'del') {
            if (!confirm('确认删除该笔借资记录？（逻辑删除，可在数据库中恢复）')) { return; }
            try { await API.del('/api/loans/' + id); Toast.ok('借资记录已删除'); loadList(state.page); }
            catch (err) { Toast.err(err.message); }
        }
    });

    (async function init() {
        try {
            await loadMeta();
            restoreFilters();
            await loadList(1);
        } catch (e) {
            Toast.err('初始化失败：' + e.message);
        }
    })();
})();
