/* =====================================================================
   智析 FinSight AI —— 轻量级图表库（纯 SVG 实现，无第三方依赖 / 可离线运行）
   提供：柱状图 bar、横向条形图 hbar、折线图 line、环形图 donut
   ===================================================================== */
(function (global) {
    'use strict';

    const PALETTE = ['#2f6fed', '#16a34a', '#f59e0b', '#dc2626', '#0891b2',
        '#7c3aed', '#db2777', '#65a30d', '#0ea5e9', '#f97316'];

    function pick(selector) {
        return typeof selector === 'string' ? document.querySelector(selector) : selector;
    }
    function esc(t) {
        return String(t === null || t === undefined ? '' : t)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function num(v) { const n = Number(v || 0); return isNaN(n) ? 0 : n; }
    function short(v) {
        const n = num(v);
        if (Math.abs(n) >= 100000000) { return (n / 100000000).toFixed(2) + '亿'; }
        if (Math.abs(n) >= 10000) { return (n / 10000).toFixed(1) + '万'; }
        if (Math.abs(n) >= 1000) { return n.toFixed(0); }
        return n.toFixed(0);
    }
    function niceMax(max) {
        if (max <= 0) { return 100; }
        const exp = Math.pow(10, Math.floor(Math.log10(max)));
        const base = max / exp;
        const step = base <= 1 ? 1 : base <= 2 ? 2 : base <= 2.5 ? 2.5 : base <= 5 ? 5 : 10;
        return step * exp;
    }

    /* ------------------------------ 柱状图 ------------------------------ */
    function bar(selector, data, opts) {
        const el = pick(selector);
        if (!el) { return; }
        opts = opts || {};
        const items = (data || []).map(function (d) {
            return { name: String(d[opts.labelKey || 'name'] || ''), value: num(d[opts.valueKey || 'value']) };
        });
        if (!items.length) { el.innerHTML = '<div class="empty-tip">暂无数据</div>'; return; }

        const W = 820, H = opts.height || 250;
        const padL = 54, padR = 16, padT = 16, padB = 40;
        const innerW = W - padL - padR, innerH = H - padT - padB;
        const max = niceMax(Math.max.apply(null, items.map(function (d) { return d.value; })));
        const slot = innerW / items.length;
        const bw = Math.min(slot * 0.55, 54);
        const color = opts.color || '#2f6fed';
        const fmt = opts.formatter || short;

        let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">';
        for (let i = 0; i <= 4; i++) {
            const y = padT + innerH - (innerH * i / 4);
            svg += '<line class="grid-line" x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y + '"/>';
            svg += '<text x="' + (padL - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + fmt(max * i / 4) + '</text>';
        }
        items.forEach(function (d, i) {
            const h = max > 0 ? innerH * d.value / max : 0;
            const x = padL + slot * i + (slot - bw) / 2;
            const y = padT + innerH - h;
            const fill = Array.isArray(color) ? color[i % color.length] : color;
            svg += '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + Math.max(h, 1)
                + '" rx="3" fill="' + fill + '" opacity="0.92"><title>' + esc(d.name) + '：' + fmt(d.value) + '</title></rect>';
            if (d.value > 0) {
                svg += '<text x="' + (x + bw / 2) + '" y="' + (y - 5) + '" text-anchor="middle">' + fmt(d.value) + '</text>';
            }
            svg += '<text x="' + (padL + slot * i + slot / 2) + '" y="' + (H - padB + 18)
                + '" text-anchor="middle">' + esc(d.name.length > 9 ? d.name.slice(0, 8) + '…' : d.name) + '</text>';
        });
        svg += '<line class="axis" x1="' + padL + '" y1="' + (padT + innerH) + '" x2="' + (W - padR)
            + '" y2="' + (padT + innerH) + '"/>';
        svg += '</svg>';
        el.innerHTML = svg;
    }

    /* ------------------------------ 横向条形图 ------------------------------ */
    function hbar(selector, data, opts) {
        const el = pick(selector);
        if (!el) { return; }
        opts = opts || {};
        const items = (data || []).map(function (d) {
            return { name: String(d[opts.labelKey || 'name'] || ''), value: num(d[opts.valueKey || 'value']) };
        });
        if (!items.length) { el.innerHTML = '<div class="empty-tip">暂无数据</div>'; return; }
        const rowH = 30, W = 820, padL = 130, padR = 90;
        const H = items.length * rowH + 16;
        const innerW = W - padL - padR;
        const max = Math.max.apply(null, items.map(function (d) { return d.value; })) || 1;
        const color = opts.color || '#2f6fed';
        const fmt = opts.formatter || short;

        let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
        items.forEach(function (d, i) {
            const y = i * rowH + 8;
            const w = Math.max(innerW * d.value / max, 2);
            const fill = Array.isArray(color) ? color[i % color.length] : color;
            svg += '<text x="' + (padL - 10) + '" y="' + (y + 14) + '" text-anchor="end">'
                + esc(d.name.length > 10 ? d.name.slice(0, 9) + '…' : d.name) + '</text>';
            svg += '<rect x="' + padL + '" y="' + y + '" width="' + innerW + '" height="15" rx="7" fill="#f1f5f9"/>';
            svg += '<rect x="' + padL + '" y="' + y + '" width="' + w + '" height="15" rx="7" fill="' + fill
                + '" opacity="0.9"><title>' + esc(d.name) + '：' + fmt(d.value) + '</title></rect>';
            svg += '<text x="' + (padL + innerW + 8) + '" y="' + (y + 13) + '">' + fmt(d.value) + '</text>';
        });
        svg += '</svg>';
        el.innerHTML = svg;
    }

    /* ------------------------------ 折线图 ------------------------------ */
    function line(selector, data, opts) {
        const el = pick(selector);
        if (!el) { return; }
        opts = opts || {};
        const items = (data || []).map(function (d) {
            return { name: String(d[opts.labelKey || 'name'] || ''), value: num(d[opts.valueKey || 'value']) };
        });
        if (!items.length) { el.innerHTML = '<div class="empty-tip">暂无数据</div>'; return; }
        const W = 820, H = opts.height || 250;
        const padL = 56, padR = 20, padT = 16, padB = 38;
        const innerW = W - padL - padR, innerH = H - padT - padB;
        const max = niceMax(Math.max.apply(null, items.map(function (d) { return d.value; })));
        const fmt = opts.formatter || short;
        const color = opts.color || '#2f6fed';

        const step = items.length > 1 ? innerW / (items.length - 1) : 0;
        let points = [];
        items.forEach(function (d, i) {
            const x = padL + step * i + (items.length === 1 ? innerW / 2 : 0);
            const y = padT + innerH - (max > 0 ? innerH * d.value / max : 0);
            points.push([x, y]);
        });

        let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
        for (let i = 0; i <= 4; i++) {
            const y = padT + innerH - (innerH * i / 4);
            svg += '<line class="grid-line" x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y + '"/>';
            svg += '<text x="' + (padL - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + fmt(max * i / 4) + '</text>';
        }
        const areaPath = 'M' + points.map(function (p) { return p[0] + ',' + p[1]; }).join(' L')
            + ' L' + points[points.length - 1][0] + ',' + (padT + innerH)
            + ' L' + points[0][0] + ',' + (padT + innerH) + ' Z';
        svg += '<path d="' + areaPath + '" fill="' + color + '" opacity="0.10"/>';
        svg += '<polyline fill="none" stroke="' + color + '" stroke-width="2.4" stroke-linejoin="round" points="'
            + points.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') + '"/>';
        points.forEach(function (p, i) {
            svg += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="4" fill="#fff" stroke="' + color
                + '" stroke-width="2"><title>' + esc(items[i].name) + '：' + fmt(items[i].value) + '</title></circle>';
            svg += '<text x="' + p[0] + '" y="' + (p[1] - 10) + '" text-anchor="middle">' + fmt(items[i].value) + '</text>';
            svg += '<text x="' + p[0] + '" y="' + (H - padB + 18) + '" text-anchor="middle">' + esc(items[i].name) + '</text>';
        });
        svg += '<line class="axis" x1="' + padL + '" y1="' + (padT + innerH) + '" x2="' + (W - padR)
            + '" y2="' + (padT + innerH) + '"/>';
        svg += '</svg>';
        el.innerHTML = svg;
    }

    /* ------------------------------ 环形图 ------------------------------ */
    function donut(selector, data, opts) {
        const el = pick(selector);
        if (!el) { return; }
        opts = opts || {};
        const items = (data || []).map(function (d) {
            return { name: String(d[opts.labelKey || 'name'] || ''), value: num(d[opts.valueKey || 'value']) };
        }).filter(function (d) { return d.value > 0; });
        if (!items.length) { el.innerHTML = '<div class="empty-tip">暂无数据</div>'; return; }

        const size = 220, cx = size / 2, cy = size / 2, r = 74, sw = 26;
        const total = items.reduce(function (s, d) { return s + d.value; }, 0);
        const C = 2 * Math.PI * r;
        let offset = 0;
        let svg = '<svg viewBox="0 0 ' + size + ' ' + size + '" style="max-width:220px;margin:0 auto">';
        svg += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="#f1f5f9" stroke-width="' + sw + '"/>';
        items.forEach(function (d, i) {
            const len = C * d.value / total;
            const color = PALETTE[i % PALETTE.length];
            svg += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + color
                + '" stroke-width="' + sw + '" stroke-dasharray="' + len + ' ' + (C - len)
                + '" stroke-dashoffset="' + (-offset) + '" transform="rotate(-90 ' + cx + ' ' + cy + ')">'
                + '<title>' + esc(d.name) + '：' + d.value.toFixed(2) + '</title></circle>';
            offset += len;
        });
        svg += '<text x="' + cx + '" y="' + (cy - 2) + '" text-anchor="middle" style="font-size:13px;fill:#64748b">合计</text>';
        svg += '<text x="' + cx + '" y="' + (cy + 18) + '" text-anchor="middle" style="font-size:15px;font-weight:700;fill:#1f2937">'
            + short(total) + '</text>';
        svg += '</svg><div class="legend">';
        items.forEach(function (d, i) {
            svg += '<span><i style="background:' + PALETTE[i % PALETTE.length] + '"></i>' + esc(d.name)
                + ' ' + (total ? (d.value / total * 100).toFixed(1) : 0) + '%</span>';
        });
        svg += '</div>';
        el.innerHTML = svg;
    }

    global.Charts = { bar: bar, hbar: hbar, line: line, donut: donut, palette: PALETTE };
})(window);
