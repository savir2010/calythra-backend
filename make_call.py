import os
import sys

# Configure library paths for WeasyPrint on macOS
if sys.platform == 'darwin':
    # Common Homebrew library paths
    homebrew_prefix = '/opt/homebrew' if os.path.exists('/opt/homebrew') else '/usr/local'
    lib_paths = [
        f'{homebrew_prefix}/lib',
        f'{homebrew_prefix}/opt/cairo/lib',
        f'{homebrew_prefix}/opt/pango/lib',
        f'{homebrew_prefix}/opt/gdk-pixbuf/lib',
        f'{homebrew_prefix}/opt/libffi/lib',
        f'{homebrew_prefix}/opt/gobject-introspection/lib',
    ]
    
    # Add to DYLD_LIBRARY_PATH if not already set
    current_dyld = os.environ.get('DYLD_LIBRARY_PATH', '')
    new_paths = [p for p in lib_paths if os.path.exists(p) and p not in current_dyld]
    if new_paths:
        os.environ['DYLD_LIBRARY_PATH'] = ':'.join(new_paths + [current_dyld]).strip(':')
    
    # Set PKG_CONFIG_PATH for pkg-config
    pkg_config_paths = [
        f'{homebrew_prefix}/lib/pkgconfig',
        f'{homebrew_prefix}/opt/cairo/lib/pkgconfig',
        f'{homebrew_prefix}/opt/pango/lib/pkgconfig',
        f'{homebrew_prefix}/opt/gdk-pixbuf/lib/pkgconfig',
        f'{homebrew_prefix}/opt/libffi/lib/pkgconfig',
        f'{homebrew_prefix}/opt/gobject-introspection/lib/pkgconfig',
    ]
    current_pkg = os.environ.get('PKG_CONFIG_PATH', '')
    new_pkg_paths = [p for p in pkg_config_paths if os.path.exists(p) and p not in current_pkg]
    if new_pkg_paths:
        os.environ['PKG_CONFIG_PATH'] = ':'.join(new_pkg_paths + [current_pkg]).strip(':')

from jinja2 import Template
from weasyprint import HTML

# Example user data
resume_data = {
    "name": "Savir Dillikar",
    "title": "Software Engineer / Tutor",
    "contact": {
        "email": "savir.1614@gmail.com",
        "phone": "+14086892766",
    },
    "summary": "High school student and tutor with experience in Python and Calculus.",
    "experience": [
        {
            "role": "Tutor",
            "company": "Weller Elementary School",
            "dates": "2025 - Present",
            "details": "Tutored students in Math and Coding for 3-4th graders."
        }
    ],
    "education": [
        {
            "degree": "High School Diploma",
            "school": "Milpitas High School",
            "dates": "2023 - Present"
        }
    ],
    "skills": ["Python", "AI/ML", "Full-stack Development", "Data Analysis", "Hackathons"]
}

# HTML Template
html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1 { font-size: 36px; margin-bottom: 0; }
        h2 { font-size: 24px; margin-bottom: 5px; color: #333; }
        p { font-size: 16px; margin: 5px 0; }
        .section { margin-top: 25px; }
        .experience, .education { margin-bottom: 15px; }
        .skills span { display: inline-block; background: #eee; padding: 5px 10px; margin: 3px; border-radius: 5px; }
        hr { border: 1px solid #ddd; margin-top: 15px; }
    </style>
</head>
<body>
    <h1>{{ name }}</h1>
    <p><strong>{{ title }}</strong></p>
    <p>Email: {{ contact.email }} | Phone: {{ contact.phone }}</p>
    
    <div class="section">
        <h2>Summary</h2>
        <p>{{ summary }}</p>
    </div>
    
    <div class="section">
        <h2>Experience</h2>
        {% for job in experience %}
        <div class="experience">
            <p><strong>{{ job.role }}</strong> - {{ job.company }} ({{ job.dates }})</p>
            <p>{{ job.details }}</p>
        </div>
        {% endfor %}
    </div>
    
    <div class="section">
        <h2>Education</h2>
        {% for edu in education %}
        <div class="education">
            <p><strong>{{ edu.degree }}</strong> - {{ edu.school }} ({{ edu.dates }})</p>
        </div>
        {% endfor %}
    </div>
    
    <div class="section">
        <h2>Skills</h2>
        <div class="skills">
            {% for skill in skills %}
            <span>{{ skill }}</span>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

# Render HTML with Jinja2
template = Template(html_template)
html_content = template.render(**resume_data)

# Generate PDF
HTML(string=html_content).write_pdf("resume.pdf")
print("Resume generated as resume.pdf")
