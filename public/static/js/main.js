// ===== ADMIN DASHBOARD FUNCTIONS =====

// Show section
function showSection(sectionId) {
    // Hide all sections
    document.querySelectorAll('.section-content').forEach(section => {
        section.classList.remove('active');
    });
    
    // Show selected section
    const target = document.getElementById(sectionId);
    if (target) {
        target.classList.add('active');
    }
    
    // Update sidebar active link
    document.querySelectorAll('.sidebar-nav a').forEach(link => {
        link.classList.remove('active');
    });
    const activeLink = document.querySelector(`.sidebar-nav a[data-section="${sectionId}"]`);
    if (activeLink) {
        activeLink.classList.add('active');
    }
}

// Show add form
function showAddForm(type) {
    document.getElementById('modalTitle').textContent = `Add ${type.charAt(0).toUpperCase() + type.slice(1)}`;
    document.getElementById('itemType').value = type;
    document.getElementById('itemId').value = '';
    document.getElementById('formTitle').value = '';
    document.getElementById('formDescription').value = '';
    
    // Add extra fields based on type
    const extraFields = document.getElementById('extraFields');
    extraFields.innerHTML = '';
    
    if (type === 'event') {
        extraFields.innerHTML = `
            <div class="form-group">
                <label>Date</label>
                <input type="date" id="formDate" required>
            </div>
            <div class="form-group">
                <label>Location</label>
                <input type="text" id="formLocation" placeholder="Event location">
            </div>
        `;
    } else if (type === 'service') {
        extraFields.innerHTML = `
            <div class="form-group">
                <label>Contact Number</label>
                <input type="text" id="formContact" placeholder="Contact number">
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="formEmergency"> Emergency Service
                </label>
            </div>
        `;
    } else if (type === 'announcement') {
        extraFields.innerHTML = `
            <div class="form-group">
                <label>Date</label>
                <input type="date" id="formDate" required>
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="formImportant"> Important Announcement
                </label>
            </div>
        `;
    } else if (type === 'complaint') {
        extraFields.innerHTML = `
            <div class="form-group">
                <label>Location</label>
                <input type="text" id="formLocation" placeholder="Location of complaint">
            </div>
            <div class="form-group">
                <label>Status</label>
                <select id="formStatus">
                    <option value="Pending">Pending</option>
                    <option value="In Progress">In Progress</option>
                    <option value="Resolved">Resolved</option>
                </select>
            </div>
        `;
    }
    
    document.getElementById('modal').classList.add('active');
}

// Edit item
function editItem(type, id) {
    showAddForm(type);
    document.getElementById('itemId').value = id;
    document.getElementById('modalTitle').textContent = `Edit ${type.charAt(0).toUpperCase() + type.slice(1)}`;
    
    // Fetch item data and populate form
    fetch(`/api/${type}s/${id}`)
        .then(response => response.json())
        .then(data => {
            document.getElementById('formTitle').value = data.title;
            document.getElementById('formDescription').value = data.description || data.content;
            
            if (type === 'event') {
                document.getElementById('formDate').value = data.date;
                document.getElementById('formLocation').value = data.location || '';
            } else if (type === 'service') {
                document.getElementById('formContact').value = data.contact || '';
                document.getElementById('formEmergency').checked = data.is_emergency || false;
            } else if (type === 'announcement') {
                document.getElementById('formDate').value = data.date;
                document.getElementById('formImportant').checked = data.is_important || false;
            } else if (type === 'complaint') {
                document.getElementById('formLocation').value = data.location || '';
                document.getElementById('formStatus').value = data.status || 'Pending';
            }
        })
        .catch(error => console.error('Error:', error));
}

// Delete item
function deleteItem(type, id) {
    if (confirm(`Are you sure you want to delete this ${type}?`)) {
        fetch(`/api/${type}s/${id}`, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload();
            }
        })
        .catch(error => console.error('Error:', error));
    }
}

// Close modal
function closeModal() {
    document.getElementById('modal').classList.remove('active');
}

// Handle form submission
document.addEventListener('DOMContentLoaded', function() {
    const modalForm = document.getElementById('modalForm');
    
    modalForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const type = document.getElementById('itemType').value;
        const id = document.getElementById('itemId').value;
        const title = document.getElementById('formTitle').value;
        const description = document.getElementById('formDescription').value;
        
        let data = { title, description };
        
        if (type === 'event') {
            data.date = document.getElementById('formDate').value;
            data.location = document.getElementById('formLocation').value;
        } else if (type === 'service') {
            data.contact = document.getElementById('formContact').value;
            data.is_emergency = document.getElementById('formEmergency').checked;
        } else if (type === 'announcement') {
            data.content = description;
            data.date = document.getElementById('formDate').value;
            data.is_important = document.getElementById('formImportant').checked;
            delete data.description;
        } else if (type === 'complaint') {
            data.location = document.getElementById('formLocation').value;
            data.status = document.getElementById('formStatus').value;
        }
        
        const url = id ? `/api/${type}s/${id}` : `/api/${type}s`;
        const method = id ? 'PUT' : 'POST';
        
        fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload();
            }
        })
        .catch(error => console.error('Error:', error));
    });
    
    // Close modal on outside click
    window.onclick = function(event) {
        const modal = document.getElementById('modal');
        if (event.target === modal) {
            closeModal();
        }
    };
});

// ===== PUBLIC PAGE FUNCTIONS =====
// Smooth scrolling for navigation links
document.querySelectorAll('nav a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});