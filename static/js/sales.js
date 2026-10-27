/* =====================================================================
   销售人员管理页面脚本
   ===================================================================== */
(function () {
    'use strict';

    const state = { page: 1, size: 10, canWrite: false };

    function filters() {
        return {
            keyword: document.getElementById('f-keyword').value.trim(),
            dept: document.getElementById('f-dept').value,
            status: document.getElementById('f-status').value
        };
    }

    async function loadOptions() {
        const opt = await API.get('/api/sales/options');
        state.canWrite = !!opt.can_write;
        const sel = document.getElementById('f-dept');
        sel.innerHTML = '<option value="">全部部门</option>';
        const datalist = document.getElementById('dept-list');
        datalist.innerHTML = '';
        opt.depts.forEach(function (d) {
            sel.insertAdjacentHTML('beforeend', '<option>' + UI.esc(d) + '</option>');
            datalist.insertAdjacentHTML('beforeend', '<option value="' + UI.esc(d) + '">');
        });
        if (!state.canWrite) {
            document.getElementById('btn-add').disabled = true;
            document.getElementById('btn-add').title = '当前角色无维护权限';
        }
    }

    async function loadList(page) {
        state.page = page || 1;
        let data;
        try {
            data = await API.get('/api/sales', Object.assign(filters(), { page: state.page, size: state.size }));
        } catch (e) { Toast.err('销售人员加载失败：' + e.message); return; }

        UI.renderTable('#table-sales', [
            { key: 'emp_no', label: '工号' },
            { key: 'name', label: '姓名' },
            { key: 'gender', label: '性别' },
            { key: 'phone', label: '手机号' },
            { key: 'dept', label: '部门' },
            { key: 'region', label: '区域' },
            { key: 'job_title', label: '岗位' },
            { key: 'entry_date', label: '入职日期', render: function (r) { return UI.dateOnly(r.entry_date); } },
            { key: 'status', label: '状态', render: function (r) { return UI.statusTag(r.status); } },
            { key: 'loan_count', label: '借资笔数', align: 'right' },
            {
                key: 'unpaid_amount', label: '未还金额（元）', align: 'right',
                render: function (r) {
                    const v = Number(r.unpaid_amount);
                    return '<b style="color:' + (v > 0 ? '#dc2626' : '#16a34a') + '">' + UI.money(v) + '</b>';
                }
            },
            {
                key: 'overdue_count', label: '逾期笔数', align: 'right',
                render: function (r) {
                    return Number(r.overdue_count) > 0
                        ? '<span class="tag red">' + r.overdue_count + ' 笔</span>'
                        : '<span class="text-sub">0</span>';
                }
            },
            {
                key: 'op', label: '操作', render: function (r) {
                    let html = '<a class="btn sm ghost" href="/loans?keyword=' + encodeURIComponent(r.name) + '">借资台账</a>';
                    if (state.canWrite) {
                        html += ' <button class="btn sm ghost" data-act="edit" data-id="' + r.id + '">编辑</button>'
                            + ' <button class="btn sm ghost" style="color:#dc2626" data-act="del" data-id="' + r.id + '">删除</button>';
                    }
                    return html;
                }
            }
        ], data.items, { empty: '暂无销售人员数据' });
        UI.renderPager('#pager', data, loadList);
    }

    function openCreate() {
        const form = document.getElementById('form-sales');
        form.reset();
        form.querySelector('[name=id]').value = '';
        form.querySelector('[name=position]').value = '销售代表';
        form.querySelector('[name=entry_date]').value = UI.todayStr();
        document.getElementById('sales-modal-title').textContent = '新增销售人员';
        UI.openModal('modal-sales');
    }

    async function openEdit(id) {
        const row = await API.get('/api/sales/' + id);
        const form = document.getElementById('form-sales');
        form.reset();
        UI.fillForm(form, row);
        form.querySelector('[name=id]').value = row.id;
        document.getElementById('sales-modal-title').textContent = '编辑销售人员（' + row.name + '）';
        UI.openModal('modal-sales');
    }

    async function save() {
        const form = document.getElementById('form-sales');
        const data = UI.formData(form);
        const id = data.id;
        delete data.id;
        if (!data.emp_no || !data.name || !data.phone || !data.dept) {
            Toast.err('工号、姓名、手机号、部门为必填项');
            return;
        }
        try {
            if (id) { await API.put('/api/sales/' + id, data); Toast.ok('销售人员信息已更新'); }
            else { await API.post('/api/sales', data); Toast.ok('销售人员新增成功'); }
            UI.closeModal('modal-sales');
            loadOptions();
            loadList(state.page);
        } catch (e) { Toast.err(e.message); }
    }

    document.getElementById('btn-search').addEventListener('click', function () { loadList(1); });
    document.getElementById('btn-reset').addEventListener('click', function () {
        document.getElementById('f-keyword').value = '';
        document.getElementById('f-dept').value = '';
        document.getElementById('f-status').value = '';
        loadList(1);
    });
    document.getElementById('f-keyword').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { loadList(1); }
    });
    document.getElementById('btn-add').addEventListener('click', openCreate);
    document.getElementById('btn-save-sales').addEventListener('click', save);

    document.getElementById('table-sales').addEventListener('click', async function (e) {
        const btn = e.target.closest('button[data-act]');
        if (!btn) { return; }
        const id = btn.dataset.id;
        if (btn.dataset.act === 'edit') { openEdit(id); }
        else if (btn.dataset.act === 'del') {
            if (!confirm('确认删除该销售人员？（若存在借资记录将不允许删除）')) { return; }
            try { await API.del('/api/sales/' + id); Toast.ok('销售人员已删除'); loadList(state.page); }
            catch (err) { Toast.err(err.message); }
        }
    });

    (async function init() {
        try { await loadOptions(); await loadList(1); }
        catch (e) { Toast.err('初始化失败：' + e.message); }
    })();
})();
