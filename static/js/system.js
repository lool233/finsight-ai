/* =====================================================================
   系统状态页面脚本
   ===================================================================== */
(function () {
    'use strict';

    function card(title, value, foot, cls) {
        return '<div class="stat ' + (cls || '') + '"><div class="label">' + UI.esc(title)
            + '</div><div class="value ' + (cls === 'ok' ? 'ok' : cls === 'danger' ? 'danger' : '')
            + '" style="font-size:17px">' + UI.esc(value) + '</div>'
            + '<div class="foot">' + UI.esc(foot) + '</div></div>';
    }

    (async function load() {
        let data;
        try { data = await API.get('/api/stats/system'); }
        catch (e) { Toast.err('系统状态加载失败：' + e.message); return; }

        const dbInfo = data.database, llm = data.llm, sms = data.sms;
        document.getElementById('status-cards').innerHTML =
            card('数据库连接', dbInfo.connected ? '正常' : '异常',
                (dbInfo.dialect === 'mysql' ? 'MySQL ' : 'SQLite ') + (dbInfo.version || '')
                + ' · ' + (dbInfo.database || ''), dbInfo.connected ? 'ok' : 'danger')
            + card('大模型（LLM）', llm.enabled ? '已接入' : '未配置',
                llm.model + ' · ' + llm.mode, llm.enabled ? 'ok' : 'warn')
            + card('短信平台', sms.available ? '已接入' : '未接入',
                sms.description, sms.available ? 'ok' : 'warn');

        UI.renderTable('#table-db', [
            { key: 'k', label: '配置项' }, { key: 'v', label: '值' }
        ], [
            { k: '数据库方言', v: dbInfo.dialect },
            { k: '数据库版本', v: dbInfo.version || '-' },
            { k: '数据库 / 文件', v: dbInfo.database || '-' },
            { k: '主机', v: dbInfo.host || '-' },
            { k: '数据表', v: (dbInfo.tables || []).join('、') },
            { k: '应用版本', v: data.app.name + ' v' + data.app.version }
        ], { empty: '无数据' });

        UI.renderTable('#table-biz', [
            { key: 'k', label: '业务参数' }, { key: 'v', label: '取值' }
        ], [
            { k: '逾期判定阈值', v: '借资超过 ' + data.business.overdue_months + ' 个月未还' },
            { k: '催还防重复间隔', v: data.business.collection_interval_days + ' 天' },
            { k: '二级催还阈值', v: '逾期 > ' + data.business.level2_days + ' 天' },
            { k: '三级催还阈值', v: '逾期 > ' + data.business.level3_days + ' 天' },
            { k: 'LLM 接口地址', v: llm.base_url },
            { k: 'LLM 降级策略', v: llm.fallback ? '已开启（无密钥时使用内置规则引擎）' : '未开启' },
            { k: '短信签名', v: sms.sign_name || '-' }
        ], { empty: '无数据' });

        UI.renderTable('#table-logs', [
            { key: 'created_at', label: '时间' },
            { key: 'username', label: '操作人' },
            { key: 'module', label: '模块' },
            { key: 'action', label: '操作' },
            { key: 'target', label: '对象' },
            { key: 'detail', label: '详情', wrap: true },
            { key: 'ip', label: 'IP' }
        ], data.logs, { empty: '暂无操作日志' });
    })();
})();
