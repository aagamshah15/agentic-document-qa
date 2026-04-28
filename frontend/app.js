document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const statusMsg = document.getElementById('upload-status');
    const chatForm = document.getElementById('chat-form');
    const queryInput = document.getElementById('query-input');
    const chatBox = document.getElementById('chat-box');

    // 1. Handle Uploads
    const handleFile = async (file) => {
        if (!file || file.type !== 'application/pdf') {
            showStatus('Please upload a valid PDF file.', 'error');
            return;
        }

        showStatus('Uploading and embedding document...', 'success');
        dropZone.style.pointerEvents = 'none';
        dropZone.style.opacity = '0.5';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                showStatus(data.message, 'success');
            } else {
                showStatus(data.detail || 'Upload failed.', 'error');
            }
        } catch (error) {
            showStatus('Network error during upload.', 'error');
        } finally {
            dropZone.style.pointerEvents = 'auto';
            dropZone.style.opacity = '1';
        }
    };

    const showStatus = (msg, type) => {
        statusMsg.textContent = msg;
        statusMsg.className = `status-message ${type}`;
    };

    // Drag and Drop events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
    });

    dropZone.addEventListener('drop', (e) => {
        const file = e.dataTransfer.files[0];
        handleFile(file);
    });

    // Click to upload
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', function() {
        handleFile(this.files[0]);
    });

    // 2. Handle Chat
    const appendMessage = (content, sender) => {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}-message slide-in`;
        
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = sender === 'user' ? 'U' : 'AI';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = content;

        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatBox.appendChild(msgDiv);

        // Scroll to bottom
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    const appendTypingIndicator = () => {
        const msgDiv = document.createElement('div');
        msgDiv.id = 'typing-indicator';
        msgDiv.className = `message assistant-message slide-in`;
        
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = 'AI';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        const indicator = document.createElement('div');
        indicator.className = 'typing-indicator';
        indicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';

        contentDiv.appendChild(indicator);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatBox.appendChild(msgDiv);
        
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    const removeTypingIndicator = () => {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    };

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = queryInput.value.trim();
        if (!query) return;

        // Display user message
        appendMessage(query, 'user');
        queryInput.value = '';
        
        // Show typing indicator
        appendTypingIndicator();

        try {
            const response = await fetch('/api/query', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ query })
            });

            const data = await response.json();
            removeTypingIndicator();

            if (response.ok) {
                appendMessage(data.answer, 'assistant');
            } else {
                appendMessage('Error: ' + (data.detail || 'Failed to get a response.'), 'assistant');
            }
        } catch (error) {
            removeTypingIndicator();
            appendMessage('Network error while querying the agent.', 'assistant');
        }
    });
});
