/**
 * Resizable Sidebars
 * Adds a draggable handle to panels to adjust their width.
 */
document.addEventListener('DOMContentLoaded', () => {
    // Select the panels to make resizable
    const panels = [
        { id: 'appSidebar', edge: 'right', minWidth: 64 },      // Main left sidebar
        { id: 'historyPanel', edge: 'right', minWidth: 250 },   // Chat history panel
        { id: 'tracePanel', edge: 'left', minWidth: 250 },      // Right panel, resize from left edge
        { id: 'relatedPanel', edge: 'left', minWidth: 250 }
    ];

    panels.forEach(panelData => {
        const panel = document.getElementById(panelData.id);
        if (!panel) return;

        // Create the drag handle
        const handle = document.createElement('div');
        handle.classList.add('resize-handle');
        handle.classList.add(`resize-${panelData.edge}`);
        
        // Add double click to reset
        handle.addEventListener('dblclick', () => {
            panel.style.width = '';
            panel.style.minWidth = '';
            panel.style.maxWidth = '';
        });

        panel.appendChild(handle);

        let isResizing = false;
        let startX;
        let startWidth;

        handle.addEventListener('mousedown', (e) => {
            isResizing = true;
            startX = e.clientX;
            // Get current computed width
            startWidth = parseFloat(getComputedStyle(panel, null).getPropertyValue('width'));
            document.body.style.cursor = 'col-resize';
            // Prevent text selection while dragging
            document.body.style.userSelect = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            
            let newWidth;
            if (panelData.edge === 'left') {
                // Dragging the left edge of a right-side panel
                newWidth = startWidth - (e.clientX - startX);
            } else {
                // Dragging the right edge of a left-side panel
                newWidth = startWidth + (e.clientX - startX);
            }
            
            // Constrain width
            const minW = panelData.minWidth || 250;
            if (newWidth < minW) newWidth = minW;
            if (newWidth > window.innerWidth * 0.8) newWidth = window.innerWidth * 0.8;
            
            panel.style.width = `${newWidth}px`;
            panel.style.minWidth = `${newWidth}px`; // Override any css min-widths temporarily
            panel.style.maxWidth = `${newWidth}px`; // Override any css max-widths temporarily
        });

        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    });
});
