/* =====================================================================
   智析 FinSight AI —— 公共前端脚本
   包含：AJAX 封装、提示条、弹窗、表格渲染、分页、格式化工具
   ===================================================================== */
(function (global) {
    'use strict';

    /* ----------------------------- 请求封装 ----------------------------- */
    async function request(url, options) {
        const opts = Object.assign({ headers: {} }, options || {});
        if (opts.body && typeof opts.body !== 'string') {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(opts.body);
        }
        let resp;
        try {
            resp = await fetch(url, opts);
        } catch (e) {
            throw new Error('网络请求失败，请确认服务是否正常运行');
        }
        let json;
        try {
            json = await resp.json();
        } catch (e) {
            throw new Error('服务器返回内容异常（HTTP ' + resp.status + '）');
        }
        if (resp.status === 401) {
            Toast.show('登录状态已失效，请重新登录', 'err');
            setTimeout(function () { location.href = '/login'; }, 1200);
            throw new Error(json.message || '未登录');
        }
        if (!json.success) {
            throw new Error(json.message || '操作失败');
        }
        return json.data;
    }

    const API = {
        get: function (url, params) {
            if (params) {
                const qs = Object.keys(params)
                    .filter(function (k) { const v = params[k]; return v !== undefined && v !== null && v !== ''; })
                    .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
                    .join('&');
                if (qs) { url += (url.indexOf('?') >= 0 ? '&' : '?') + qs; }
            }
            return request(url);
        },
        post: function (url, body) { return request(url, { method: 'POST', body: body || {} }); },
        put: function (url, body) { return request(url, { method: 'PUT', body: body || {} }); },
        del: function (url) { return request(url, { method: 'DELETE' }); }
    };

    /* ----------------------------- 提示条 ----------------------------- */
    const Toast = {
        box: null,
        show: function (message, type, ms) {
            if (!this.box) {
                this.box = document.createElement('div');
                this.box.className = 'toast-box';
                document.body.appendChild(this.box);
            }
            const el = document.createElement('div');
            el.className = 'toast ' + (type || 'info');
            el.textContent = message;
            this.box.appendChild(el);
            setTimeout(function () {
                el.style.transition = 'opacity .3s';
                el.style.opacity = '0';
                setTimeout(function () { el.remove(); }, 320);
            }, ms || 2600);
        },
        ok: function (m) { this.show(m, 'ok'); },
        err: function (m) { this.show(m, 'err', 3600); },
        info: function (m) { this.show(m, 'info'); }
    };

    /* ----------------------------- 弹窗 ----------------------------- */
    function openModal(id) {
        const el = document.getElementById(id);
        if (el) { el.classList.add('show'); }
    }
    function closeModal(id) {
        const el = document.getElementById(id);
        if (el) { el.classList.remove('show'); }
    }
    function bindModalClose() {
        document.addEventListener('click', function (e) {
            if (e.target.classList && e.target.classList.contains('modal-mask')) {
                e.target.classList.remove('show');
            }
            if (e.target.dataset && e.target.dataset.close) {
                closeModal(e.target.dataset.close);
            }
        });
    }

    /* ----------------------------- 工具函数 ----------------------------- */
    function esc(text) {
        if (text === null || text === undefined) { return ''; }
        return String(text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function money(value) {
        const n = Number(value || 0);
        return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function dateOnly(value) { return value ? String(value).slice(0, 10) : ''; }
    function todayStr() {
        const d = new Date();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return d.getFullYear() + '-' + m + '-' + day;
    }
    function statusTag(status) {
        const map = {
            '待还款': 'orange', '部分还款': 'blue', '已还清': 'green', '已核销': 'gray',
            '在职': 'green', '离职': 'gray'
        };
        return '<span class="tag ' + (map[status] || 'gray') + '">' + esc(status) + '</span>';
    }
    function levelTag(level) {
        const map = { '一级': 'blue', '二级': 'orange', '三级': 'red' };
        return '<span class="tag ' + (map[level] || 'gray') + '">' + esc(level) + '催还</span>';
    }
    function sendTag(status) {
        const map = { '已发送': 'green', '待发送': 'orange', '发送失败': 'red', '无短信平台': 'purple' };
        return '<span class="tag ' + (map[status] || 'gray') + '">' + esc(status) + '</span>';
    }
    function roleName(role) {
        return { admin: '系统管理员', finance: '财务人员', sales: '销售人员', viewer: '只读用户' }[role] || role;
    }

    /* ----------------------------- 表格 ----------------------------- */
    /**
     * 渲染数据表格
     * @param {HTMLElement|string} target 容器
     * @param {Array} columns [{key,label,width,align,render(row)}]
     * @param {Array} rows 数据
     * @param {Object} opts {empty:'暂无数据'}
     */
    function renderTable(target, columns, rows, opts) {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) { return; }
        opts = opts || {};
        if (!rows || !rows.length) {
            el.innerHTML = '<div class="empty-tip">' + esc(opts.empty || '暂无数据') + '</div>';
            return;
        }
        let html = '<div class="table-wrap"><table class="data"><thead><tr>';
        columns.forEach(function (c) {
            const label = c.labelHtml ? c.labelHtml : esc(c.label);
            html += '<th' + (c.width ? ' style="width:' + c.width + '"' : '')
                + (c.align === 'right' ? ' class="right"' : '') + '>' + label + '</th>';
        });
        html += '</tr></thead><tbody>';
        rows.forEach(function (row, idx) {
            html += '<tr>';
            columns.forEach(function (c) {
                let cell;
                if (typeof c.render === 'function') {
                    cell = c.render(row, idx);
                } else {
                    cell = esc(row[c.key] === null || row[c.key] === undefined ? '' : row[c.key]);
                }
                const cls = (c.align === 'right' ? 'num' : '') + (c.wrap ? ' wrap' : '');
                html += '<td' + (cls ? ' class="' + cls.trim() + '"' : '') + '>' + cell + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        el.innerHTML = html;
    }

    /* ----------------------------- 分页 ----------------------------- */
    /**
     * 渲染分页控件
     * @param {string} target 容器选择器
     * @param {Object} pageData {total,page,size,pages}
     * @param {Function} onChange 页码变化回调
     */
    function renderPager(target, pageData, onChange) {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) { return; }
        const page = Number(pageData.page || 1);
        const pages = Math.max(1, Number(pageData.pages || 1));
        const total = Number(pageData.total || 0);
        let html = '<span>共 <b>' + total + '</b> 条，第 ' + page + ' / ' + pages + ' 页</span><span class="pages">';
        html += '<button data-page="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>';
        let start = Math.max(1, page - 2);
        let end = Math.min(pages, start + 4);
        start = Math.max(1, end - 4);
        for (let i = start; i <= end; i++) {
            html += '<button data-page="' + i + '"' + (i === page ? ' class="active"' : '') + '>' + i + '</button>';
        }
        html += '<button data-page="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + '>下一页</button>';
        html += '</span>';
        el.innerHTML = html;
        el.querySelectorAll('button[data-page]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const p = Number(this.dataset.page);
                if (p >= 1 && p <= pages && p !== page) { onChange(p); }
            });
        });
    }

    /* ----------------------------- 表单 ----------------------------- */
    function formData(formEl) {
        const data = {};
        formEl.querySelectorAll('[name]').forEach(function (input) {
            if (input.type === 'checkbox') { data[input.name] = input.checked; }
            else if (input.type === 'number') {
                data[input.name] = input.value === '' ? null : Number(input.value);
            } else { data[input.name] = input.value.trim(); }
        });
        return data;
    }
    function fillForm(formEl, row) {
        formEl.querySelectorAll('[name]').forEach(function (input) {
            const key = input.name;
            if (row[key] === undefined || row[key] === null) {
                if (input.type !== 'checkbox') { input.value = ''; }
                return;
            }
            if (input.type === 'checkbox') { input.checked = !!row[key]; }
            else { input.value = String(row[key]).slice(0, input.type === 'date' ? 10 : undefined); }
        });
    }
    function debounce(fn, wait) {
        let timer = null;
        return function () {
            const args = arguments, self = this;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(self, args); }, wait || 300);
        };
    }

    global.API = API;
    global.Toast = Toast;
    global.UI = {
        openModal: openModal, closeModal: closeModal, bindModalClose: bindModalClose,
        esc: esc, money: money, dateOnly: dateOnly, todayStr: todayStr,
        statusTag: statusTag, levelTag: levelTag, sendTag: sendTag, roleName: roleName,
        renderTable: renderTable, renderPager: renderPager,
        formData: formData, fillForm: fillForm, debounce: debounce
    };

    document.addEventListener('DOMContentLoaded', bindModalClose);
})(window);
