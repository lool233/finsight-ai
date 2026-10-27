/* =====================================================================
   数据看板页面脚本
   ===================================================================== */
(function () {
    'use strict';

    async function load() {
        let data;
        try {
            data = await API.get('/api/stats/dashboard');
        } catch (e) {
            Toast.err('看板数据加载失败：' + e.message);
            return;
        }

        const ov = data.overview;
        document.getElementById('s-total').textContent = UI.money(ov.total_amount);
        document.getElementById('s-total-foot').textContent = '共 ' + ov.loan_count + ' 笔借资';
        document.getElementById('s-unpaid').textContent = UI.money(ov.unpaid_amount);
        document.getElementById('s-unpaid-foot').textContent = '涉及 ' + ov.debtor_count + ' 名销售人员';
        document.getElementById('s-overdue').textContent = UI.money(ov.overdue_amount);
        document.getElementById('s-overdue-foot').textContent = '逾期 ' + ov.overdue_count + ' 笔 / '
            + ov.overdue_person + ' 人，已生成催还记录 ' + ov.collection_total + ' 条';
        document.getElementById('s-rate').textContent = ov.collection_rate + '%';
        document.getElementById('s-rate-foot').textContent = '已还 ' + UI.money(ov.repaid_amount) + ' 元';

        Charts.bar('#chart-dept', data.dept.map(function (d) {
            return { name: d.name, value: Number(d.total_amount) };
        }), { height: 250 });

        Charts.donut('#chart-type', data.type.map(function (d) {
            return { name: d.name, value: Number(d.total_amount) };
        }));

        Charts.line('#chart-trend', data.trend.map(function (d) {
            return { name: d.name.slice(2), value: Number(d.total_amount) };
        }), { height: 250 });

        Charts.hbar('#chart-aging', data.aging.map(function (d) {
            return { name: d.name, value: Number(d.unpaid_amount) };
        }), { color: ['#94a3b8', '#38bdf8', '#f59e0b', '#f97316', '#dc2626'] });

        UI.renderTable('#table-top', [
            { key: 'name', label: '姓名' },
            { key: 'dept', label: '部门' },
            { key: 'loan_count', label: '笔数', align: 'right' },
            {
                key: 'unpaid_amount', label: '未还金额（元）', align: 'right',
                render: function (r) { return UI.money(r.unpaid_amount); }
            },
            {
                key: 'id', label: '操作', render: function (r) {
                    return '<a class="btn sm ghost" href="/loans?keyword=' + encodeURIComponent(r.name) + '">查看借资</a>';
                }
            }
        ], data.top, { empty: '暂无欠款数据' });

        UI.renderTable('#table-collection', [
            { key: 'sales_name', label: '催还对象' },
            { key: 'loan_no', label: '借资单号' },
            { key: 'overdue_days', label: '逾期天数', align: 'right' },
            {
                key: 'overdue_amount', label: '逾期金额', align: 'right',
                render: function (r) { return UI.money(r.overdue_amount); }
            },
            { key: 'collection_level', label: '级别', render: function (r) { return UI.levelTag(r.collection_level); } },
            { key: 'send_status', label: '发送状态', render: function (r) { return UI.sendTag(r.send_status); } }
        ], data.recent_collections, { empty: '尚未生成催还记录，可点击上方按钮一键生成' });

        UI.renderTable('#table-loan', [
            { key: 'loan_no', label: '借资单号' },
            { key: 'sales_name', label: '借款人' },
            { key: 'dept', label: '部门' },
            {
                key: 'amount', label: '借资金额（元）', align: 'right',
                render: function (r) { return UI.money(r.amount); }
            },
            {
                key: 'unpaid_amount', label: '未还金额（元）', align: 'right',
                render: function (r) { return UI.money(r.unpaid_amount); }
            },
            { key: 'loan_date', label: '借资日期', render: function (r) { return UI.dateOnly(r.loan_date); } },
            { key: 'status', label: '状态', render: function (r) { return UI.statusTag(r.status); } }
        ], data.recent_loans, { empty: '暂无借资记录' });
    }

    document.getElementById('btn-run-collection').addEventListener('click', async function () {
        const btn = this;
        if (!confirm('将扫描全部借资台账，对超过 3 个月未还的借资调用 LLM 生成催还记录并下发短信，是否继续？')) {
            return;
        }
        btn.disabled = true;
        btn.innerHTML = '<span class="loading"></span> 正在分析并生成…';
        try {
            const result = await API.post('/api/collections/run', {});
            let msg = '扫描 ' + result.scanned + ' 笔，生成催还记录 ' + result.created + ' 条，'
                + '下发成功 ' + result.sent_ok + ' 条';
            if (result.sent_fail) { msg += '，未成功 ' + result.sent_fail + ' 条'; }
            if (result.skipped) { msg += '，跳过重复 ' + result.skipped + ' 条'; }
            Toast.ok(msg);
            if (result.created && result.items.length) {
                const first = result.items[0];
                console.log('催还短信示例：', first.content);
                alert('催还批处理完成：' + msg + '\n\n催还短信示例（' + first.sales_name + '）：\n'
                    + first.content + '\n\n内容来源：' + first.generated_by
                    + '，发送状态：' + first.send_status + '\n（' + first.send_detail + '）');
            }
            await load();
        } catch (e) {
            Toast.err(e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = '⚡ 一键生成催还记录';
        }
    });

    load();
})();
