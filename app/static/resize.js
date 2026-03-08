/* ── MASTER CONTROL — Resize Handles ─────────────────────────── */

(function() {
    /* Horizontal resize: between hex grid and bottom panels */
    const hHandle = document.getElementById('resize-handle-h');
    const mainDisplay = document.getElementById('main-display');
    const bottomPanels = document.getElementById('bottom-panels');
    let isResizingH = false;

    hHandle.addEventListener('mousedown', (e) => {
        isResizingH = true;
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizingH) return;
        const headerHeight = document.querySelector('header').offsetHeight;
        const handleHeight = hHandle.offsetHeight;
        const mainHeight = e.clientY - headerHeight;
        const bottomHeight = window.innerHeight - e.clientY - handleHeight;
        if (mainHeight > 150 && bottomHeight > 100) {
            mainDisplay.style.flex = 'none';
            mainDisplay.style.height = mainHeight + 'px';
            bottomPanels.style.flex = 'none';
            bottomPanels.style.height = bottomHeight + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizingH) {
            isResizingH = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });

    /* Vertical resize: between panel columns */
    const colHandles = document.querySelectorAll('.col-resize-handle');
    let activeColHandle = null;
    let leftPanel = null;
    let rightPanel = null;
    let startX = 0;
    let startLeftWidth = 0;
    let startRightWidth = 0;

    colHandles.forEach(handle => {
        handle.addEventListener('mousedown', (e) => {
            activeColHandle = handle;
            leftPanel = handle.previousElementSibling;
            rightPanel = handle.nextElementSibling;
            startX = e.clientX;
            startLeftWidth = leftPanel.offsetWidth;
            startRightWidth = rightPanel.offsetWidth;
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
    });

    document.addEventListener('mousemove', (e) => {
        if (!activeColHandle) return;
        const dx = e.clientX - startX;
        const newLeft = startLeftWidth + dx;
        const newRight = startRightWidth - dx;
        if (newLeft > 80 && newRight > 80) {
            leftPanel.style.flex = 'none';
            leftPanel.style.width = newLeft + 'px';
            rightPanel.style.flex = 'none';
            rightPanel.style.width = newRight + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        if (activeColHandle) {
            activeColHandle = null;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
})();
