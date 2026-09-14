// Platform colors are shared between the graph (node fill) and the
// Connection Layers checkboxes in index.html's topic-network panel (swatch
// color), so this is exposed on window rather than kept private to the
// D3 closure below.
const PLATFORM_NODE_COLORS = {
    twitter: "#1d9bf0", facebook: "#1877f2", instagram: "#e1306c",
    whatsapp: "#25d366", youtube: "#ff0000", unknown: "#3b82f6"
};
window.platformLayerColor = function(platform) {
    return PLATFORM_NODE_COLORS[(platform || "unknown").toLowerCase()] || PLATFORM_NODE_COLORS.unknown;
};

const SENTIMENT_EDGE_COLORS = { positive: "#16a34a", negative: "#dc2626", neutral: "#64748b" };

// Social Connection Layers (real user<->user edges from /network/connections)
// — distinct from SENTIMENT_EDGE_COLORS above, which colors topic<->user
// edges. Shared with index.html/nodeanalysis.html's connection-layer
// checkboxes the same way PLATFORM_NODE_COLORS is shared for their swatches.
const CONNECTION_TYPE_EDGE_COLORS = {
    follower: "#38bdf8", following: "#6366f1",
    retweet: "#22c55e", like: "#ec4899",
    quote: "#a855f7", reply: "#f59e0b"
};
window.connectionTypeColor = function(type) {
    return CONNECTION_TYPE_EDGE_COLORS[(type || "").toLowerCase()] || "#4b5563";
};

// Inline SVG icons (Lucide-style paths) instead of Font Awesome — the
// buttons previously used `<i class="fas fa-plus">` etc, but this app never
// loads Font Awesome (only Lucide, via <script src="unpkg.com/lucide">), so
// those icons rendered as nothing and the buttons were unstyled/invisible
// (no `.btn`/`.btn-sm`/`.btn-outline-primary` CSS exists anywhere either).
const GRAPH_ICON_ZOOM_IN = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const GRAPH_ICON_ZOOM_OUT = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const GRAPH_ICON_FIT = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>';
const GRAPH_ICON_EXTERNAL = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';

window.buildNetworkGraph = function(data) {
    const containerEl = document.getElementById("network-graph-container");
    containerEl.innerHTML = `
        <div class="graph-toolbar">
            <button id="zoomInBtn" class="graph-tool-btn" title="Zoom in">${GRAPH_ICON_ZOOM_IN}</button>
            <button id="zoomOutBtn" class="graph-tool-btn" title="Zoom out">${GRAPH_ICON_ZOOM_OUT}</button>
            <button id="fitZoomBtn" class="graph-tool-btn" title="Fit to screen">${GRAPH_ICON_FIT}</button>
            <button id="openGraphNewTabBtn" class="graph-tool-btn" title="Open this graph in a new tab">${GRAPH_ICON_EXTERNAL}</button>
        </div>
        <svg id="network-svg" width="100%" height="100%" style="background: #0f172a;"></svg>
    `;

    // "Open in new tab" — the graph only exists as in-memory D3 state in this
    // page, so hand the data to the new tab via localStorage (shared across
    // same-origin tabs, unlike sessionStorage) and let /graph-viewer read it
    // back and call this same buildNetworkGraph() full-screen.
    //
    // Snapshot nodes/links BEFORE the simulation below mutates them in place
    // (d3-force replaces link.source/target strings with full node object
    // references, and adds x/y/vx/vy/index onto every node) — serializing
    // the live `data` object after that would embed a full duplicate node
    // inside every link instead of a plain id.
    const graphSnapshot = {
        nodes: data.nodes.map(n => ({ ...n })),
        links: data.links.map(l => ({
            ...l,
            source: typeof l.source === "object" ? l.source.id : l.source,
            target: typeof l.target === "object" ? l.target.id : l.target
        }))
    };
    d3.select("#openGraphNewTabBtn").on("click", () => {
        try {
            localStorage.setItem("_networkGraphViewerData", JSON.stringify(graphSnapshot));
            window.open("/graph-viewer", "_blank");
        } catch (e) {
            console.error("Failed to open graph in new tab:", e);
        }
    });

    // Node details render into a static box BELOW the graph (in the normal
    // page flow, in the white space) instead of a floating tooltip inside
    // containerEl — the container has overflow:hidden so a mouse-position
    // tooltip near an edge gets clipped and unreadable. Reuse the info box
    // if buildNetworkGraph is called again (e.g. a new search), otherwise
    // create it once as containerEl's next sibling so this works both here
    // and for the chat-embedded graph in script.js's renderChartsAndGraphs().
    let infoBox = containerEl.nextElementSibling;
    if (!infoBox || !infoBox.classList.contains("network-node-info")) {
        infoBox = document.createElement("div");
        infoBox.className = "network-node-info";
        containerEl.after(infoBox);
    }
    infoBox.innerHTML = '<span class="network-node-info-placeholder">Hover a node to see its details here, or click one to see its source posts.</span>';

    const svg = d3.select("#network-svg");
    const width = containerEl.clientWidth || 800;
    const height = containerEl.clientHeight || 600;
    
    let simulation;

    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
            container.attr("transform", event.transform);
        });

    const container = svg.append("g");
    svg.call(zoom);

    d3.select("#zoomInBtn").on("click", () => svg.transition().duration(200).call(zoom.scaleBy, 1.25));
    d3.select("#zoomOutBtn").on("click", () => svg.transition().duration(200).call(zoom.scaleBy, 0.8));
    d3.select("#fitZoomBtn").on("click", () => {
        const bounds = container.node().getBBox();
        const dx = bounds.width, dy = bounds.height, x = bounds.x + dx / 2, y = bounds.y + dy / 2;
        const scale = Math.max(0.1, Math.min(4, 0.9 / Math.max(dx / width, dy / height)));
        const translate = [width / 2 - scale * x, height / 2 - scale * y];
        svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale));
    });


    const CATEGORY_PALETTE = {
        topic: { fill: ["#f59e0b", "#d97706"], text: "#fff" },
        user:  { fill: ["#3b82f6", "#2563eb"], text: "#fff" },
        unknown: { fill: ["#6b7280", "#4b5563"], text: "#fff" }
    };

    function getPalette(d) {
        return CATEGORY_PALETTE[d.type] || CATEGORY_PALETTE.unknown;
    }

    // User nodes are colored by platform (Connection Layers' "Platform" layer)
    // when a recognized platform is present; topic nodes keep their fixed
    // orange, and anything else falls back to the generic palette above.
    function nodeFill(d) {
        if (d.type === "user") return window.platformLayerColor(d.platform);
        return getPalette(d).fill[0];
    }

    // Edges carry a sentiment when they came from the topic-network graph
    // (Connection Layers' "Sentiment" layer), or a connectionType when they
    // came from the social Connection Layers graph (/network/connections);
    // other graphs (manual entity search, Top 20 Topics) set neither, so
    // they keep the neutral gray.
    function linkStroke(d) {
        if (d.connectionType) return window.connectionTypeColor(d.connectionType);
        return d.sentiment ? (SENTIMENT_EDGE_COLORS[d.sentiment] || SENTIMENT_EDGE_COLORS.neutral) : "#4b5563";
    }

    // Social connection edges (follower/following/retweet/like/quote/reply)
    // are inherently directional — unlike the undirected topic<->user
    // sentiment edges — so they get an arrowhead pointing at the target.
    // One <marker> per connection type so the arrowhead color matches its edge.
    const defs = svg.append("defs");
    Object.keys(CONNECTION_TYPE_EDGE_COLORS).forEach(type => {
        defs.append("marker")
            .attr("id", `arrow-${type}`)
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 18)
            .attr("refY", 0)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("d", "M0,-5L10,0L0,5")
            .attr("fill", CONNECTION_TYPE_EDGE_COLORS[type]);
    });
    function linkMarkerEnd(d) {
        return d.connectionType ? `url(#arrow-${d.connectionType})` : null;
    }

    const nodeCount = data.nodes.length;
    const repulsionStrength = Math.min(-300, -100 - nodeCount * 5);
    const linkDist = Math.min(200, 80 + nodeCount * 2);

    simulation = d3.forceSimulation(data.nodes)
        .force("link", d3.forceLink(data.links).id(d => d.id).distance(linkDist))
        .force("charge", d3.forceManyBody().strength(repulsionStrength))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(d => d.type === "topic" ? 50 : 25));

    const link = container.append("g")
        .selectAll("line")
        .data(data.links)
        .join("line")
        .attr("stroke", linkStroke)
        .attr("stroke-width", d => Math.min(Math.sqrt((d.weight || 1)) + 0.8, 5))
        .attr("stroke-opacity", 0.6)
        .attr("marker-end", linkMarkerEnd);

    // Quick summary shown on hover (kept short — full post list is a click away).
    function summaryHtml(d) {
        let html = `<strong>${d.label || d.name || d.username || d.id}</strong><br/>`;
        html += `Type: <span style="text-transform:capitalize;">${d.type}</span><br/>`;
        if (d.type === 'topic') {
            html += `Total Posts: ${d.postCount || d.total_posts || 0}`;
        } else {
            html += `Platform: <span style="text-transform:capitalize;">${d.platform || 'unknown'}</span><br/>`;
            html += `Followers: ${d.followersCount || 0}<br/>`;
            html += `Category: ${d.handleCategory || 'Others'}<br/>`;
            html += `Involved Posts: ${d.userPostCount || 1}`;
        }
        return html;
    }

    // Full detail shown on click — same summary, plus the actual source
    // posts (with their URLs) behind this node, when the graph was built
    // with per-node `posts` data (see index.html's renderTopicNetworkGraph).
    // Capped at 20 so one heavily-posting node doesn't blow out the panel.
    const SENTIMENT_BADGE_CLASS = { positive: 'positive', negative: 'negative', neutral: 'neutral' };
    function escapeHtml(s) {
        return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }
    // "Expand Connections" is an optional hook a host page defines
    // (index.html / nodeanalysis.html) to open the social Connection Layers
    // panel for this user (see /network/connections). Pages that don't
    // define it (e.g. the read-only graph-viewer.html snapshot) simply
    // don't get the button.
    function connectionsButtonHtml(d) {
        if (d.type !== "user" || typeof window.onExpandUserConnections !== "function") return "";
        const uid = String(d.id).replace(/^user-/, "");
        return `<button type="button" class="network-quick-btn" style="margin-top:8px;"
                    onclick='window.onExpandUserConnections(${JSON.stringify({ id: uid, name: d.name, username: d.username, platform: d.platform })})'>
                    Expand Connections
                </button>`;
    }

    function detailHtml(d) {
        let html = summaryHtml(d) + connectionsButtonHtml(d);
        if (!Array.isArray(d.posts) || !d.posts.length) return html;

        const shown = d.posts.slice(0, 20);
        html += `<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border-color, #e5e7eb);font-weight:600;font-size:12px;">Source Posts (${d.posts.length})</div>`;
        html += '<div style="max-height:220px;overflow-y:auto;margin-top:6px;display:flex;flex-direction:column;gap:8px;">';
        html += shown.map(p => {
            const badgeClass = SENTIMENT_BADGE_CLASS[p.sentiment] || 'neutral';
            const text = escapeHtml((p.text || '').substring(0, 140));
            const link = p.url
                ? `<a href="${p.url}" target="_blank" rel="noopener" class="feed-card-link">View Source →</a>`
                : '<span style="color:var(--text-secondary,#94a3b8);font-size:11.5px;">No URL on record</span>';
            return `<div style="font-size:12px;line-height:1.4;">
                <span class="feed-badge ${badgeClass}" style="margin-right:6px;">${p.sentiment || 'neutral'}</span>
                ${text}${text.length >= 140 ? '…' : ''}
                <div style="margin-top:3px;">${link}</div>
            </div>`;
        }).join('');
        if (d.posts.length > shown.length) {
            html += `<div style="font-size:11px;color:var(--text-secondary,#94a3b8);">+${d.posts.length - shown.length} more not shown</div>`;
        }
        html += '</div>';
        return html;
    }

    // Clicking a node "pins" its full detail (with post links) so it survives
    // mouseout; hovering other nodes still previews them, but mouseout
    // restores the pinned node's detail instead of the empty placeholder.
    // Clicking empty canvas, or the same node again, unpins.
    let pinnedNode = null;

    function highlightConnections(d) {
        const connected = new Set([d.id]);
        data.links.forEach(l => {
            if (l.source.id === d.id) connected.add(l.target.id);
            if (l.target.id === d.id) connected.add(l.source.id);
        });
        node.attr("opacity", n => connected.has(n.id) ? 1 : 0.1);
        link.attr("stroke-opacity", l => (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.05);
    }

    function clearHighlight() {
        node.attr("opacity", 1);
        link.attr("stroke-opacity", 0.6);
    }

    svg.on("click", () => {
        pinnedNode = null;
        infoBox.innerHTML = '<span class="network-node-info-placeholder">Hover a node to see its details here, or click one to see its source posts.</span>';
        clearHighlight();
    });

    const node = container.append("g")
        .selectAll(".node")
        .data(data.nodes)
        .join("g")
        .attr("class", "node")
        .call(d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended))
        .on("mouseover", (event, d) => {
            if (pinnedNode) return; // pinned detail stays until unpinned
            infoBox.innerHTML = summaryHtml(d);
            highlightConnections(d);
        })
        .on("mouseout", () => {
            if (pinnedNode) {
                infoBox.innerHTML = detailHtml(pinnedNode);
                highlightConnections(pinnedNode);
            } else {
                infoBox.innerHTML = '<span class="network-node-info-placeholder">Hover a node to see its details here, or click one to see its source posts.</span>';
                clearHighlight();
            }
        })
        .on("click", (event, d) => {
            event.stopPropagation();
            if (pinnedNode === d) {
                pinnedNode = null;
                infoBox.innerHTML = '<span class="network-node-info-placeholder">Hover a node to see its details here, or click one to see its source posts.</span>';
                clearHighlight();
                return;
            }
            pinnedNode = d;
            infoBox.innerHTML = detailHtml(d);
            highlightConnections(d);
        });

    node.append("circle")
        .attr("r", d => {
            if (d.type === "topic") {
                return Math.min(50, Math.max(25, (d.total_posts || 10) / 2));
            } else {
                return Math.min(25, Math.max(10, (d.userPostCount || 1) * 3));
            }
        })
        .attr("fill", nodeFill)
        .attr("stroke", d => d.isSeed ? "#facc15" : "#fff")
        .attr("stroke-width", d => d.isSeed ? 3.5 : 1.5);

    node.append("text")
        .text(d => {
            let t = d.label || d.name || d.username || d.id;
            return t.length > 15 ? t.substring(0,12) + "..." : t;
        })
        .attr("text-anchor", "middle")
        .attr("dy", d => d.type === "topic" ? 45 : 25)
        .style("fill", "#e2e8f0")
        .style("font-size", "10px")
        .style("pointer-events", "none");

    simulation.on("tick", () => {
        link
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);
        node
            .attr("transform", d => `translate(${d.x},${d.y})`);
    });

    function dragstarted(event) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
    }
    function dragged(event) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
    }
    function dragended(event) {
        if (!event.active) simulation.alphaTarget(0);
        event.subject.fx = null;
        event.subject.fy = null;
    }
    
    // Automatically fit to zoom after a small delay to let force layout settle
    setTimeout(() => {
        d3.select("#fitZoomBtn").node().click();
    }, 500);
};