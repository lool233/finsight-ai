/* =====================================================================
   统计报表页面脚本
   ===================================================================== */
(function () {
    'use strict';

    async function load() {
        const months = Number(document.getElementById('f-months').value);
        const top = Number(document.getElementById('f-top').value);

        let overview, dept, type, trend, aging, topRows;
        try {
            const results = await Promise.all([
                API.get('/api/stats/overview'),
                API.get('/api/stats/dept'),
                API.get('/api/stats/type'),
                API.get('/api/stats/trend', { months: months }),
                API.get('/api/stats/aging'),
                API.get('/api/stats/top', { limit: top })
            ]);
            overview = results[0]; dept = results[1]; type = results[2];
            trend = results[3]; aging = results[4]; topRows = results[5];
        } catch (e) {
            Toast.err('统计数据加载失败：' + e.message);
            return;
        }

        document.getElementById('s1').textContent = UI.money(overview.total_amount);
        document.getElementById('s2').textContent = UI.money(overview.repaid_amount);
        document.getElementById('s3').textContent = UI.money(overview.unpaid_amount);
        document.getElementById('s4').textContent = UI.money(overview.overdue_amount);
        document.getElementById('trend-hint').textContent = '近 ' + months + ' 个月';

        Charts.bar('#chart-dept', dept.map(function (d) {
            return { name: d.name, value: Number(d.total_amount) };
        }), { height: 260 });

        Charts.bar('#chart-type', type.map(function (d) {
            return { name: d.name, value: Number(d.total_amount) };
        }), { height: 260, color: Charts.palette });

        Charts.line('#chart-trend', trend.map(function (d) {
            return { name: d.name, value: Number(d.total_amount) };
        }), { height: 260 });

        Charts.hbar('#chart-aging', aging.map(function (d) {
            return { name: d.name, value: Number(d.unpaid_amount) };
        }), { color: ['#94a3b8', '#38bdf8', '#f59e0b', '#f97316', '#dc2626'] });

        UI.renderTable('#table-dept', [
            { key: 'name', label: '部门' },
            { key: 'loan_count', label: '笔数', align: 'right' },
            { key: 'total_amount', label: '借资总额', align: 'right', render: function (r) { return UI.money(r.total_amount); } },
            { key: 'repaid_amount', label: '已还', align: 'right', render: function (r) { return UI.money(r.repaid_amount); } },
            { key: 'unpaid_amount', label: '未还', align: 'right', render: function (r) { return UI.money(r.unpaid_amount); } },
            {
                key: 'progress', label: '回款进度', render: function (r) {
                    const total = Number(r.total_amount) || 1;
                    const pct = Math.min(100, Number(r.repaid_amount) / total * 100);
                    return '<div class="bar-track"><div class="bar-fill green" style="width:' + pct.toFixed(1) + '%"></div></div>'
                        + '<span class="text-sub" style="font-size:11px">' + pct.toFixed(1) + '%</span>';
                }
            }
        ], dept, { empty: '暂无部门统计数据' });

        UI.renderTable('#table-top', [
            { key: 'emp_no', label: '工号' },
            { key: 'name', label: '姓名' },
            { key: 'dept', label: '部门' },
            { key: 'phone', label: '手机号' },
            { key: 'loan_count', label: '借资笔数', align: 'right' },
            { key: 'total_amount', label: '借资总额', align: 'right', render: function (r) { return UI.money(r.total_amount); } },
            {
                key: 'unpaid_amount', label: '未还金额', align: 'right',
                render: function (r) { return '<b style="color:#dc2626">' + UI.money(r.unpaid_amount) + '</b>'; }
            },
            {
                key: 'op', label: '操作', render: function (r) {
                    return '<a class="btn sm ghost" href="/loans?keyword=' + encodeURIComponent(r.name) + '">台账</a>'
                        + ' <a class="btn sm ghost" href="/collections?keyword=' + encodeURIComponent(r.name) + '">催还</a>';
                }
            }
        ], topRows, { empty: '暂无未还金额数据' });
    }

    document.getElementById('btn-refresh').addEventListener('click', load);
    document.getElementById('btn-print').addEventListener('click', function () { window.print(); });
    document.getElementById('f-months').addEventListener('change', load);
    document.getElementById('f-top').addEventListener('change', load);
    load();
})();
