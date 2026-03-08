/* ── MASTER CONTROL — SVG Hex Grid with D3 ──────────────────── */
/* Flat grid with elevation cues, tag-based cluster regions, zoom/pan */

const HexGrid = (() => {
    const HEX_RADIUS = 153;
    const HEX_GAP = 4;
    const CLUSTER_PADDING = 18;
    const CLUSTER_LABEL_OFFSET = -12;

    let svg, g, zoom;
    let projects = [];
    let selectedId = null;
    let filterTag = null;

    /* Hex geometry (flat-top) */
    function hexPoints(cx, cy, r) {
        const pts = [];
        for (let i = 0; i < 6; i++) {
            const angle = (Math.PI / 180) * (60 * i);
            pts.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)]);
        }
        return pts.map(p => p.join(',')).join(' ');
    }

    function hexWidth(r) { return r * 2; }
    function hexHeight(r) { return r * Math.sqrt(3); }

    /* Cluster layout: grid-based regions */
    function computeLayout(projects) {
        // Group by primary tag
        const clusters = {};
        projects.forEach(p => {
            const tag = getPrimaryTag(p.tags);
            if (!clusters[tag]) clusters[tag] = [];
            clusters[tag].push(p);
        });

        // Arrange clusters in a grid of cluster regions
        const clusterNames = Object.keys(clusters).sort((a, b) =>
            clusters[b].length - clusters[a].length
        );

        const COLS_PER_CLUSTER = 4;
        const hw = hexWidth(HEX_RADIUS) + HEX_GAP;
        const hh = hexHeight(HEX_RADIUS) + HEX_GAP;

        let clusterCol = 0;
        let clusterRow = 0;
        const MAX_CLUSTERS_PER_ROW = 3;

        const positions = [];
        const clusterLabels = [];

        clusterNames.forEach((tag, ci) => {
            const items = clusters[tag];
            const cols = Math.min(items.length, COLS_PER_CLUSTER);
            const rows = Math.ceil(items.length / cols);

            const clusterX = clusterCol * (COLS_PER_CLUSTER * hw + CLUSTER_PADDING * 2);
            const clusterY = clusterRow * (4 * hh + CLUSTER_PADDING * 2);

            clusterLabels.push({
                tag,
                x: clusterX + (cols * hw) / 2,
                y: clusterY + CLUSTER_LABEL_OFFSET,
                count: items.length,
            });

            items.forEach((p, i) => {
                const col = i % cols;
                const row = Math.floor(i / cols);
                const offsetX = (row % 2) * (hw / 2);
                positions.push({
                    project: p,
                    x: clusterX + col * hw + offsetX + HEX_RADIUS,
                    y: clusterY + row * hh + HEX_RADIUS + 10,
                });
            });

            clusterCol++;
            if (clusterCol >= MAX_CLUSTERS_PER_ROW) {
                clusterCol = 0;
                clusterRow++;
            }
        });

        return { positions, clusterLabels };
    }

    function init(svgElement) {
        svg = d3.select(svgElement);
        const parent = svgElement.parentElement;
        const width = parent.clientWidth;
        const height = parent.clientHeight - (document.getElementById('tag-filter-bar')?.offsetHeight || 32);

        svg.attr('width', width).attr('height', Math.max(height, 200));

        zoom = d3.zoom()
            .scaleExtent([0.3, 3])
            .on('zoom', (event) => g.attr('transform', event.transform));
        svg.call(zoom);

        g = svg.append('g');
    }

    function render(data) {
        projects = data;
        if (!g) return;

        g.selectAll('*').remove();
        const { positions, clusterLabels } = computeLayout(projects);

        // Cluster labels
        g.selectAll('.cluster-label')
            .data(clusterLabels)
            .enter()
            .append('text')
            .attr('class', 'cluster-label')
            .attr('x', d => d.x)
            .attr('y', d => d.y)
            .attr('text-anchor', 'middle')
            .attr('fill', d => getTagColor(d.tag))
            .attr('font-size', '65px')
            .attr('font-weight', '700')
            .attr('opacity', 0.85)
            .text(d => `${d.tag.toUpperCase()} (${d.count})`);

        // Hex groups
        const hexGroups = g.selectAll('.hex-group')
            .data(positions)
            .enter()
            .append('g')
            .attr('class', 'hex-group')
            .attr('transform', d => `translate(${d.x}, ${d.y})`)
            .style('cursor', 'pointer');

        // Hex polygons
        hexGroups.append('polygon')
            .attr('class', 'hex-polygon')
            .attr('points', hexPoints(0, 0, HEX_RADIUS))
            .attr('fill', d => {
                const tag = getPrimaryTag(d.project.tags);
                const color = getTagColor(tag);
                return color + '33';  // 20% opacity fill
            })
            .attr('stroke', d => getTagColor(getPrimaryTag(d.project.tags)))
            .attr('stroke-width', 1.5)
            .attr('filter', d => d.project.id === selectedId ? 'url(#glow)' : 'none');

        // Project name inside hex (word-wrapped)
        hexGroups.each(function(d) {
            const maxWidth = HEX_RADIUS * 1.5;
            const lineHeight = 36;
            const name = d.project.name;
            const words = name.replace(/[_-]/g, ' ').split(/\s+/);
            const lines = [];
            let cur = '';
            words.forEach(w => {
                const test = cur ? cur + ' ' + w : w;
                if (test.length > 12 && cur) {
                    lines.push(cur);
                    cur = w;
                } else {
                    cur = test;
                }
            });
            if (cur) lines.push(cur);

            const totalH = lines.length * lineHeight;
            const startY = -totalH / 2 + lineHeight * 0.35;

            const text = d3.select(this).append('text')
                .attr('class', 'hex-label')
                .attr('text-anchor', 'middle')
                .attr('fill', '#ffffff')
                .attr('font-size', '32px')
                .attr('font-weight', '600');

            lines.forEach((line, i) => {
                text.append('tspan')
                    .attr('x', 0)
                    .attr('dy', i === 0 ? startY + 'px' : lineHeight + 'px')
                    .text(line);
            });
        });

        // Status line at top of hex
        hexGroups.append('text')
            .attr('class', 'hex-status')
            .attr('text-anchor', 'middle')
            .attr('y', -HEX_RADIUS * 0.65)
            .attr('fill', '#90a4ae')
            .attr('font-size', '16px')
            .text(d => formatDate(d.project.last_modified));

        // Secondary tag dots along bottom edge
        hexGroups.each(function(d) {
            const secondaryTags = d.project.tags.slice(1, 4);
            secondaryTags.forEach((tag, i) => {
                d3.select(this).append('circle')
                    .attr('cx', -30 + i * 35)
                    .attr('cy', HEX_RADIUS * 0.65)
                    .attr('r', 15)
                    .attr('fill', getTagColor(tag));
            });
        });

        // Interactions
        hexGroups
            .on('mouseenter', function(event, d) {
                d3.select(this).select('.hex-polygon')
                    .transition().duration(150)
                    .attr('stroke-width', 2.5)
                    .attr('fill', getTagColor(getPrimaryTag(d.project.tags)) + '55');
                d3.select(this)
                    .transition().duration(150)
                    .attr('transform', `translate(${d.x}, ${d.y - 4})`);
                showTooltip(event, d.project);
            })
            .on('mouseleave', function(event, d) {
                d3.select(this).select('.hex-polygon')
                    .transition().duration(300)
                    .attr('stroke-width', d.project.id === selectedId ? 2.5 : 1.5)
                    .attr('fill', getTagColor(getPrimaryTag(d.project.tags)) + '33');
                d3.select(this)
                    .transition().duration(300)
                    .attr('transform', `translate(${d.x}, ${d.y})`);
                hideTooltip();
            })
            .on('click', function(event, d) {
                selectedId = d.project.id;
                render(projects);  // re-render to update selection glow
                if (typeof onProjectSelected === 'function') {
                    onProjectSelected(d.project);
                }
            });

        // Apply filter dimming
        if (filterTag) {
            hexGroups.attr('opacity', d =>
                d.project.tags.includes(filterTag) ? 1 : 0.2
            );
        }

        // Auto-fit: zoom/pan so all content is visible
        fitToView();

        // SVG filter for selection glow
        if (!svg.select('defs').node()) {
            const defs = svg.append('defs');
            const filter = defs.append('filter').attr('id', 'glow');
            filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur');
            filter.append('feFlood').attr('flood-color', '#4fc3f7').attr('flood-opacity', '0.6');
            filter.append('feComposite').attr('in2', 'blur').attr('operator', 'in');
            const merge = filter.append('feMerge');
            merge.append('feMergeNode');
            merge.append('feMergeNode').attr('in', 'SourceGraphic');
        }
    }

    function showTooltip(event, project) {
        const tooltip = document.getElementById('tooltip');
        const tags = project.tags.map(t =>
            `<span class="tag-pill" style="background:${getTagColor(t)}33;color:${getTagColor(t)};border:1px solid ${getTagColor(t)}">${t}</span>`
        ).join(' ');
        tooltip.innerHTML = `
            <div class="tooltip-name">${project.name}</div>
            <div class="tooltip-tags">${tags}</div>
            <div class="tooltip-info">
                <span>${project.status}</span>
                <span class="sep">|</span>
                <span>${formatDate(project.last_modified)}</span>
                <span class="sep">|</span>
                <span>${project.file_count} files</span>
            </div>
            ${project.git_branch ? `<div class="tooltip-git">${project.git_branch}${project.git_dirty ? ' *' : ''}</div>` : ''}
        `;
        tooltip.style.display = 'block';
        tooltip.style.left = (event.pageX + 15) + 'px';
        tooltip.style.top = (event.pageY - 10) + 'px';
    }

    function hideTooltip() {
        document.getElementById('tooltip').style.display = 'none';
    }

    function setFilter(tag) {
        filterTag = tag === filterTag ? null : tag;
        render(projects);
    }

    function fitToView() {
        if (!g || !svg) return;
        const bbox = g.node().getBBox();
        if (bbox.width === 0 || bbox.height === 0) return;

        const svgW = parseFloat(svg.attr('width'));
        const svgH = parseFloat(svg.attr('height'));
        const pad = 30;

        const scale = Math.min(
            (svgW - pad * 2) / bbox.width,
            (svgH - pad * 2) / bbox.height,
            1.2  // don't zoom in beyond 1.2x even if few projects
        );
        const tx = (svgW - bbox.width * scale) / 2 - bbox.x * scale;
        const ty = (svgH - bbox.height * scale) / 2 - bbox.y * scale;

        svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }

    function getSelectedId() { return selectedId; }

    function selectProject(project) {
        selectedId = project.id;
        render(projects);
    }

    return { init, render, setFilter, getSelectedId, selectProject };
})();
